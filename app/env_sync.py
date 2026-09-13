"""Writes .env.local, .env.example and VERCEL_ENV.txt from one place.
"""
import argparse
import base64
import json
import secrets

from app.export_web import build_pack_list, build_packs_b64
from ingest.personas import CONFIG_DIR, ROOT, load_env

ENV_LOCAL = ROOT / "web" / ".env.local"
ENV_EXAMPLE = ROOT / "web" / ".env.example"
VERCEL_FILE = ROOT / "VERCEL_ENV.txt"
VALUES_DIR = ROOT / ".vercel-values"
DEV_VARS = ROOT / "web" / ".dev.vars"
KV_DIR = ROOT / "web" / ".kv"
SECRETS = ("OPENAI_API_KEY", "ELEVENLABS_API_KEY", "ECHO_ADMIN_TOKEN", "ECHO_TOTP_GRANTS")
GRANTS_PATH = CONFIG_DIR / "totp_grants.json"

DEFAULTS = {
    "OPENAI_BASE_URL": "https://api.openai.com/v1",
    "OPENAI_MODEL": "gpt-5.6-terra",
    "ECHO_DAILY_MESSAGE_CAP": "80",
    "ECHO_IP_BURST": "6",
    "ECHO_SHARED_VOICE_CAP": "25",
}

ORDER = [
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
    "ELEVENLABS_API_KEY",
    "ECHO_PERSONAS_B64",
    "ECHO_DAILY_MESSAGE_CAP",
    "ECHO_IP_BURST",
    "ECHO_SHARED_VOICE_CAP",
    "ECHO_ADMIN_TOKEN",
    "ECHO_TOTP_GRANTS",
]

NOTES = {
    "OPENAI_API_KEY": "server side only, never reaches the browser",
    "OPENAI_BASE_URL": "any OpenAI compatible endpoint",
    "OPENAI_MODEL": "model name for the chat calls",
    "ELEVENLABS_API_KEY": "omit and the site falls back to browser speech",
    "ECHO_PERSONAS_B64": "style cards, public and private tiers",
    "ECHO_DAILY_MESSAGE_CAP": "global messages per day",
    "ECHO_IP_BURST": "messages per minute per visitor",
    "ECHO_SHARED_VOICE_CAP": "shared library voices added per day",
    "ECHO_ADMIN_TOKEN": "unlocks the admin panel",
    "ECHO_TOTP_GRANTS": "who may unlock private mode",
}


def read_pairs(path):
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def grants_blob():
    if not GRANTS_PATH.exists():
        return ""
    try:
        grants = json.loads(GRANTS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ""
    payload = [
        {k: v for k, v in grant.items() if k in ("id", "secret", "expires")}
        for grant in grants
    ]
    if not payload:
        return ""
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


# One source of truth. I had .env.local and VERCEL_ENV.txt drift apart once
# and spent an evening debugging a "deployment" problem that was a stale
# file, so now they are always written together.
def collect():
    load_env()
    root_env = read_pairs(ROOT / ".env")
    existing = read_pairs(ENV_LOCAL)

    values = {}
    for key in ORDER:
        values[key] = existing.get(key, "") or root_env.get(key, "") or DEFAULTS.get(key, "")

    for key in ("OPENAI_API_KEY", "ELEVENLABS_API_KEY"):
        if root_env.get(key):
            values[key] = root_env[key]

    for key, default in DEFAULTS.items():
        if not values[key]:
            values[key] = default

    if not values["ECHO_ADMIN_TOKEN"]:
        values["ECHO_ADMIN_TOKEN"] = secrets.token_urlsafe(32)

    values["ECHO_TOTP_GRANTS"] = grants_blob()
    values["ECHO_PERSONAS_B64"] = build_packs_b64()
    return values


def write_local(values):
    lines = [f'{key}="{values[key]}"' for key in ORDER if values[key]]
    ENV_LOCAL.parent.mkdir(parents=True, exist_ok=True)
    ENV_LOCAL.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_example():
    lines = ["# Copy to .env.local and fill in. Never commit real values.", ""]
    for key in ORDER:
        lines.append(f"# {NOTES[key]}")
        default = DEFAULTS.get(key, "")
        lines.append(f'{key}="{default}"')
        lines.append("")
    ENV_EXAMPLE.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_vercel(values, already_set):
    unchanged = [k for k in ORDER if k in already_set and k != "ECHO_PERSONAS_B64"]
    replace = ["ECHO_PERSONAS_B64"]
    add = [k for k in ORDER if k not in already_set and k != "ECHO_PERSONAS_B64"]

    lines = [
        "# Vercel environment variables for echo-persona.",
        "# This file holds real secrets. It is gitignored. Do not commit or share it.",
        "# Settings > Environment Variables. Tick Production, Preview AND Development.",
        "# Environment changes only take effect after a redeploy.",
        "",
        "# ---------------------------------------------------------------",
        "# ALREADY IN VERCEL, leave these alone",
        "# ---------------------------------------------------------------",
    ]
    for key in unchanged:
        lines.append(f"{key}={values[key]}")

    lines += [
        "",
        "# ---------------------------------------------------------------",
        "# REPLACE the existing value with this one",
        "# ---------------------------------------------------------------",
    ]
    for key in replace:
        lines.append(f"{key}={values[key]}")

    lines += [
        "",
        "# ---------------------------------------------------------------",
        "# ADD these, they are not in Vercel yet",
        "# ---------------------------------------------------------------",
    ]
    for key in add:
        if values[key]:
            lines.append(f"{key}={values[key]}")

    VERCEL_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return unchanged, replace, add


# Cloudflare side. Secrets go in .dev.vars for local dev and are pushed with
# wrangler secret put. The personas are plain JSON in .kv/ and go into KV.
def write_cloudflare(values):
    DEV_VARS.parent.mkdir(parents=True, exist_ok=True)
    lines = [f'{key}="{values[key]}"' for key in SECRETS if values.get(key)]
    DEV_VARS.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
    KV_DIR.mkdir(parents=True, exist_ok=True)
    (KV_DIR / "personas.json").write_text(
        json.dumps(build_pack_list(), ensure_ascii=False), encoding="utf-8"
    )


def write_values_dir(values):
    VALUES_DIR.mkdir(parents=True, exist_ok=True)
    for key in ORDER:
        if values[key]:
            (VALUES_DIR / key).write_text(values[key], encoding="utf-8", newline="")


def main():
    parser = argparse.ArgumentParser(
        description="Regenerate .env.local, .env.example and VERCEL_ENV.txt from one source."
    )
    parser.add_argument(
        "--already-set",
        nargs="*",
        default=["OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL", "ELEVENLABS_API_KEY"],
        help="variables already configured in Vercel",
    )
    args = parser.parse_args()

    values = collect()
    write_local(values)
    write_example()
    unchanged, replace, add = write_vercel(values, set(args.already_set))
    write_values_dir(values)
    write_cloudflare(values)

    print(f"wrote {ENV_LOCAL.relative_to(ROOT)}")
    print(f"wrote {ENV_EXAMPLE.relative_to(ROOT)}")
    print(f"wrote {VERCEL_FILE.relative_to(ROOT)}")
    print(f"wrote {VALUES_DIR.relative_to(ROOT)}/ (one file per variable)")
    print(f"wrote {DEV_VARS.relative_to(ROOT)} and {KV_DIR.relative_to(ROOT)}/personas.json for Cloudflare")
    print("")
    print("unchanged in Vercel:")
    for key in unchanged:
        print(f"  {key}")
    print("")
    print("REPLACE:")
    for key in replace:
        print(f"  {key}  ({len(values[key]):,} chars)")
    print("")
    print("ADD:")
    for key in add:
        if values[key]:
            shown = values[key] if len(values[key]) <= 8 else f"{len(values[key]):,} chars"
            print(f"  {key}  {shown}")
    print("")
    print("Then redeploy. Environment changes need a new deployment to take effect.")


if __name__ == "__main__":
    main()
