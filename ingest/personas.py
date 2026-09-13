"""Paths and config loading shared by every stage.

All the per-persona output lives under data/<name>/ so two people never
collide.
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
PERSONA_DIR = CONFIG_DIR / "personas"
DATA_DIR = ROOT / "data"


def list_personas():
    return sorted(p.stem for p in PERSONA_DIR.glob("*.json"))


# With more than one persona I refuse to guess. It bit me once when the
# alphabetically first one had no voice folder.
def default_persona():
    names = list_personas()
    if not names:
        raise SystemExit(f"no persona configs found in {PERSONA_DIR}")
    env = os.environ.get("ECHO_PERSONA")
    if env:
        if env not in names:
            raise SystemExit(f"ECHO_PERSONA={env!r} not in {names}")
        return env
    if len(names) == 1:
        return names[0]
    configured = load_runtime().get("default_persona")
    if configured in names:
        return configured
    raise SystemExit(
        f"several personas exist ({', '.join(names)}); pass --persona NAME, "
        "set ECHO_PERSONA, or set default_persona in config/runtime.json"
    )


def load_persona(name=None):
    name = name or default_persona()
    path = PERSONA_DIR / f"{name}.json"
    if not path.exists():
        raise SystemExit(
            f"persona {name!r} not found; available: {list_personas()}"
        )
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["_path"] = str(path)
    cfg.setdefault("persona", name)
    return cfg


def load_runtime():
    return json.loads((CONFIG_DIR / "runtime.json").read_text(encoding="utf-8"))


def voice_path(cfg):
    voice_cfg = cfg.get("voice") or {}
    return ROOT / voice_cfg.get("path", f"voice/{cfg['persona']}")


def voice_enabled(cfg):
    voice_cfg = cfg.get("voice") or {}
    if not voice_cfg.get("enabled", True):
        return False
    return voice_path(cfg).exists()


def persona_dir(persona):
    return DATA_DIR / persona


def turns_path(persona):
    return persona_dir(persona) / "turns.jsonl"


def holdout_path(persona):
    return persona_dir(persona) / "holdout.jsonl"


def report_path(persona):
    return persona_dir(persona) / "ingest_report.json"


def prompt_path(persona):
    return persona_dir(persona) / "system_prompt.txt"


def style_path(persona):
    return persona_dir(persona) / "style.json"


def manifest_path(persona):
    return persona_dir(persona) / "persona.json"


def audio_dir(persona):
    return persona_dir(persona) / "audio"


def voice_id_path():
    return CONFIG_DIR / "voice_id.json"


VOICE_STORE_HINT = "config/voice_id.json"


# I read .env myself instead of pulling in python-dotenv. Keys never get
# printed and never go on the command line.
def load_env():
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # Windows caps one env var at 32767 chars. The Python side only needs
        # API keys, so anything huge is a web value that landed here by
        # accident and can be skipped.
        if key and key not in os.environ and len(value) < 30000:
            os.environ[key] = value


def require_key(env_name):
    load_env()
    value = os.environ.get(env_name, "").strip()
    if not value:
        raise SystemExit(
            f"{env_name} is not set. Add it to .env (see .env.example). "
            "Never pass the key on the command line."
        )
    return value
