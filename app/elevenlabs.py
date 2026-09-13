"""The three ElevenLabs calls I use: add a voice, speak, read the quota.
"""
import json
from datetime import datetime, timezone

import requests

from ingest.personas import CONFIG_DIR, require_key

API_ROOT = "https://api.elevenlabs.io/v1"
VOICE_STORE = CONFIG_DIR / "voice_id.json"

# My key deliberately has no Voices read scope, so I cannot list the account
# to check for an existing clone. The saved voice_id file is the only guard.
PERMISSION_HINT = (
    "This project only uses Text to Speech, Voices write, Models access, User access "
    "and History read. If this failed with a permission error, the key is missing one "
    "of those, not because more scopes are needed."
)


def load_store():
    if not VOICE_STORE.exists():
        return {}
    try:
        return json.loads(VOICE_STORE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_store(store):
    VOICE_STORE.parent.mkdir(parents=True, exist_ok=True)
    VOICE_STORE.write_text(
        json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def get_voice_id(persona):
    entry = load_store().get(persona)
    if isinstance(entry, dict):
        return entry.get("voice_id")
    return entry


def record_voice_id(persona, voice_id, name, sources, requires_verification=None):
    store = load_store()
    store[persona] = {
        "voice_id": voice_id,
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_files": sources,
        "requires_verification": requires_verification,
    }
    save_store(store)
    return store[persona]


def api_key(runtime_cfg):
    env_name = runtime_cfg.get("tts", {}).get("api_key_env", "ELEVENLABS_API_KEY")
    return require_key(env_name)


def _fail(response, action):
    detail = response.text[:600]
    if response.status_code == 401:
        raise SystemExit(f"ElevenLabs rejected the key while {action}. {PERMISSION_HINT}")
    if response.status_code == 403:
        raise SystemExit(
            f"ElevenLabs returned 403 while {action}. {PERMISSION_HINT}\n{detail}"
        )
    if response.status_code == 429:
        raise SystemExit(f"ElevenLabs rate limit or quota exhausted while {action}.\n{detail}")
    raise SystemExit(f"ElevenLabs returned {response.status_code} while {action}:\n{detail}")


def add_voice(key, name, files, description=None, labels=None, timeout=300):
    handles = []
    payload = []
    try:
        for path in files:
            handle = open(path, "rb")
            handles.append(handle)
            payload.append(("files", (path.name, handle, "audio/mpeg")))
        data = {"name": name}
        if description:
            data["description"] = description
        if labels:
            data["labels"] = json.dumps(labels)
        response = requests.post(
            f"{API_ROOT}/voices/add",
            headers={"xi-api-key": key},
            data=data,
            files=payload,
            timeout=timeout,
        )
    finally:
        for handle in handles:
            handle.close()

    if response.status_code not in (200, 201):
        _fail(response, "creating the voice clone")
    return response.json()


def text_to_speech(key, voice_id, text, model_id, output_format, voice_settings, timeout=180):
    response = requests.post(
        f"{API_ROOT}/text-to-speech/{voice_id}",
        headers={"xi-api-key": key, "Content-Type": "application/json"},
        params={"output_format": output_format},
        data=json.dumps(
            {
                "text": text,
                "model_id": model_id,
                "voice_settings": voice_settings,
            }
        ).encode("utf-8"),
        timeout=timeout,
    )
    if response.status_code != 200:
        _fail(response, "generating speech")
    return response.content


def subscription(key, timeout=30):
    response = requests.get(
        f"{API_ROOT}/user/subscription", headers={"xi-api-key": key}, timeout=timeout
    )
    if response.status_code != 200:
        _fail(response, "reading the subscription")
    return response.json()
