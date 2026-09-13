"""Thin client for any OpenAI-compatible chat endpoint.

I used requests directly instead of the openai package so there is one less
dependency and I can see exactly what goes over the wire.
"""
import json

import requests

from ingest.personas import load_runtime, require_key

# Different OpenAI-compatible endpoints disagree on parameter names. Rather
# than maintain a table I retry once with the other name when the error
# message tells me which one it wanted.
UNSUPPORTED_HINTS = ("unsupported", "not supported", "unrecognized", "unknown parameter")


# Profiles let me flip between the prompted baseline and a fine tuned model
# by changing one string in the config.
def resolve_profile(cfg, name=None):
    profiles = cfg.get("profiles") or {}
    if not profiles:
        return cfg, cfg.get("profile", "default")
    chosen = name or cfg.get("profile")
    if chosen not in profiles:
        raise SystemExit(
            f"chat profile {chosen!r} not found; available: {sorted(profiles)}"
        )
    merged = {k: v for k, v in cfg.items() if k not in ("profiles", "profile")}
    merged.update(profiles[chosen])
    return merged, chosen


class ChatClient:
    def __init__(
        self, runtime_cfg=None, model=None, base_url=None, timeout=120, profile=None
    ):
        raw = (runtime_cfg or load_runtime())["chat"]
        cfg, self.profile = resolve_profile(raw, profile)
        self.base_url = (base_url or cfg["base_url"]).rstrip("/")
        self.model = model or cfg["model"]
        self.temperature = cfg.get("temperature", 0.9)
        self.max_output_tokens = cfg.get("max_output_tokens", 300)
        self.use_system_prompt = cfg.get("use_system_prompt", True)
        self.api_key = require_key(cfg.get("api_key_env", "OPENAI_API_KEY"))
        self.timeout = timeout
        self._token_param = "max_completion_tokens"
        self._send_temperature = True
        self.last_usage = {}

    def _payload(self, messages):
        payload = {
            "model": self.model,
            "messages": messages,
            self._token_param: self.max_output_tokens,
        }
        if self._send_temperature:
            payload["temperature"] = self.temperature
        return payload

    def _post(self, payload):
        return requests.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            data=json.dumps(payload).encode("utf-8"),
            timeout=self.timeout,
        )

    def complete(self, messages):
        for attempt in range(4):
            response = self._post(self._payload(messages))
            if response.status_code == 200:
                break
            detail = response.text[:600]
            lowered = detail.lower()
            if response.status_code == 400 and any(h in lowered for h in UNSUPPORTED_HINTS):
                if "max_completion_tokens" in lowered and self._token_param != "max_tokens":
                    self._token_param = "max_tokens"
                    continue
                if "max_tokens" in lowered and self._token_param != "max_completion_tokens":
                    self._token_param = "max_completion_tokens"
                    continue
                if "temperature" in lowered and self._send_temperature:
                    self._send_temperature = False
                    continue
            if response.status_code == 401:
                raise SystemExit(
                    "Authentication failed against "
                    f"{self.base_url}. Check the key in .env."
                )
            if attempt == 3 or response.status_code < 500:
                raise SystemExit(
                    f"{self.base_url} returned {response.status_code}: {detail}"
                )
        else:
            raise SystemExit("request failed after retries")

        body = response.json()
        self.last_usage = body.get("usage", {}) or {}
        choices = body.get("choices") or []
        if not choices:
            raise SystemExit(f"no choices in response: {json.dumps(body)[:400]}")
        return (choices[0].get("message", {}).get("content") or "").strip()

    def describe(self):
        return f"{self.profile}: {self.model} @ {self.base_url}"
