"""One command to clone a person end to end.

    python clone.py sam

It finds chat/<format>/sam and voice/sam, works out which participant is
Sam, writes the persona config, and runs every stage.
"""
import argparse
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from ingest.adapters import available, get_adapter
from ingest.personas import (
    CONFIG_DIR,
    PERSONA_DIR,
    holdout_path,
    load_persona,
    load_runtime,
    manifest_path,
    persona_dir,
    voice_enabled,
    prompt_path,
    style_path,
    turns_path,
)

CHAT_ROOT = ROOT / "chat"
VOICE_ROOT = ROOT / "voice"


# NFKC normalisation turns styled unicode like the mathematical bold letters
# Instagram uses into plain ASCII, so the folder name "sam" matches the
# stored display name without me hardcoding anything.
def slug(value):
    folded = unicodedata.normalize("NFKC", value or "").casefold()
    return re.sub(r"[^a-z0-9]+", "", folded)


def find_chat_dir(name):
    matches = []
    for fmt_dir in sorted(p for p in CHAT_ROOT.iterdir() if p.is_dir()):
        for candidate in sorted(p for p in fmt_dir.iterdir() if p.is_dir()):
            if slug(candidate.name) == slug(name):
                matches.append((fmt_dir.name, candidate))
    if not matches:
        available_dirs = [
            f"chat/{f.name}/{d.name}"
            for f in CHAT_ROOT.iterdir()
            if f.is_dir()
            for d in f.iterdir()
            if d.is_dir()
        ]
        raise SystemExit(
            f"no chat folder for {name!r}. Looked for chat/<format>/{name}.\n"
            f"found: {', '.join(available_dirs) or '(nothing)'}"
        )
    if len(matches) > 1:
        raise SystemExit(
            f"{name!r} matches several folders: "
            + ", ".join(str(p.relative_to(ROOT)) for _, p in matches)
        )
    return matches[0]


def find_voice_dir(name):
    for candidate in sorted(p for p in VOICE_ROOT.iterdir() if p.is_dir()):
        if slug(candidate.name) == slug(name):
            return candidate
    return None


# Whichever participant matches the folder name is the person being cloned.
# The most frequent remaining sender is the other party.
def detect_senders(fmt, chat_dir, name):
    adapter = get_adapter(fmt)
    counts = adapter.participants(chat_dir)
    counts = {k: v for k, v in counts.items() if k}
    if len(counts) < 2:
        raise SystemExit(
            f"expected two participants in {chat_dir}, found: {list(counts) or '(none)'}"
        )
    target = slug(name)
    hits = [n for n in counts if slug(n) == target]
    if not hits:
        hits = [n for n in counts if target and target in slug(n)]
    if not hits:
        raise SystemExit(
            f"could not tell which participant is {name!r}.\n"
            f"participants: {', '.join(repr(n) for n in counts)}\n"
            "Create the persona config by hand, or rename the chat folder to match."
        )
    if len(hits) > 1:
        raise SystemExit(f"{name!r} matches several participants: {hits}")
    clone_sender = hits[0]
    others = sorted(
        (n for n in counts if n != clone_sender), key=lambda n: counts[n], reverse=True
    )
    return clone_sender, others[0], counts


def ensure_persona(name, args):
    path = PERSONA_DIR / f"{slug(name)}.json"
    if path.exists() and not args.reconfigure:
        return json.loads(path.read_text(encoding="utf-8")), path, False

    fmt, chat_dir = find_chat_dir(name)
    clone_sender, other_sender, counts = detect_senders(fmt, chat_dir, name)
    voice_dir = find_voice_dir(name)

    cfg = {
        "persona": slug(name),
        "display_name": name,
        "pronoun": args.pronoun,
        "consent": {
            "granted": bool(args.consent),
            "granted_by": name,
            "scope": "text-style and voice cloning for personal use",
        },
        "chat": {
            "format": fmt,
            "path": str(chat_dir.relative_to(ROOT)).replace("\\", "/"),
            "clone_sender": clone_sender,
            "other_sender": other_sender,
        },
        "voice": {
            "enabled": voice_dir is not None and not args.skip_voice,
            "path": str(voice_dir.relative_to(ROOT)).replace("\\", "/")
            if voice_dir
            else f"voice/{slug(name)}",
        },
        "redact_names": [other_sender.split()[0]] if other_sender else [],
        "ingest": {"gap_hours": args.gap_hours, "holdout": 0.10, "seed": 7},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  detected participants: {', '.join(f'{k!r} ({v})' for k, v in counts.items())}")
    print(f"  cloning: {clone_sender!r}   other party: {other_sender!r}")
    print(f"  wrote {path.relative_to(ROOT)}")
    return cfg, path, True


# Each stage is its own module, so I just shell out to them in order. The voice
# clone is optional because it fails on a free ElevenLabs plan and I did not
# want that to kill the text side.
def step(label, args_list, optional=False):
    print(f"\n>> {label}")
    result = subprocess.run([sys.executable, "-m"] + args_list, cwd=ROOT)
    if result.returncode != 0:
        if optional:
            print(f"   ({label} skipped: exit {result.returncode})")
            return False
        raise SystemExit(f"{label} failed with exit code {result.returncode}")
    return True


def write_manifest(cfg, voice_ready):
    from app.elevenlabs import get_voice_id

    persona = cfg["persona"]
    stats = {}
    if style_path(persona).exists():
        stats = json.loads(style_path(persona).read_text(encoding="utf-8"))
    report = {}
    if (persona_dir(persona) / "ingest_report.json").exists():
        report = json.loads(
            (persona_dir(persona) / "ingest_report.json").read_text(encoding="utf-8")
        )
    manifest = {
        "persona": persona,
        "display_name": cfg.get("display_name", persona),
        "pronoun": cfg.get("pronoun", "they"),
        "text_ready": prompt_path(persona).exists(),
        "voice_ready": voice_ready,
        "voice_id": get_voice_id(persona),
        "paths": {
            "system_prompt": str(prompt_path(persona).relative_to(ROOT)).replace("\\", "/"),
            "turns": str(turns_path(persona).relative_to(ROOT)).replace("\\", "/"),
            "holdout": str(holdout_path(persona).relative_to(ROOT)).replace("\\", "/"),
        },
        "stats": {
            k: stats.get(k)
            for k in (
                "messages",
                "messages_per_burst",
                "chars_median",
                "pct_start_uppercase",
                "pct_with_emoji",
                "pct_question",
                "exchanges",
            )
        },
        "turns": report.get("turns_total"),
        "tokens": report.get("tokens_total"),
    }
    manifest_path(persona).parent.mkdir(parents=True, exist_ok=True)
    manifest_path(persona).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return manifest


def main():
    parser = argparse.ArgumentParser(
        description="Clone one person's texting style and voice end to end.",
        epilog="example: python clone.py sam",
    )
    parser.add_argument("name", help="folder name under chat/<format>/ and voice/")
    parser.add_argument("--pronoun", default="they", choices=["she", "he", "they"])
    parser.add_argument("--gap-hours", type=float, default=6.0)
    parser.add_argument("--skip-voice", action="store_true")
    parser.add_argument("--skip-clone", action="store_true", help="prepare audio but do not call ElevenLabs")
    parser.add_argument("--reconfigure", action="store_true")
    parser.add_argument("--format", choices=available())
    parser.add_argument(
        "--consent",
        action="store_true",
        default=True,
        help="you confirm the person consented to being cloned",
    )
    args = parser.parse_args()

    name = args.name
    persona = slug(name)
    print(f"echo-persona :: {name}  (persona id {persona!r})")

    cfg, cfg_path, created = ensure_persona(name, args)
    if not created:
        print(f"  using existing {cfg_path.relative_to(ROOT)} (--reconfigure to redetect)")

    step("parse chat", ["ingest.parse_chat", "--persona", persona])
    step("build system prompt", ["app.prompt", "--persona", persona, "--rebuild"])

    voice_ready = False
    want_voice = voice_enabled(cfg) and not args.skip_voice
    if want_voice:
        step("convert audio", ["app.convert_voice", "--persona", persona])
        step("remove background noise", ["app.denoise_voice", "--persona", persona])
        if not args.skip_clone:
            voice_ready = step(
                "clone voice", ["app.clone_voice", "--persona", persona], optional=True
            )
    else:
        print("\n>> voice skipped (no clips, or disabled)")

    manifest = write_manifest(cfg, voice_ready)
    print(f"\n{'=' * 60}")
    print(f"persona:    {manifest['display_name']}  ({persona})")
    print(f"text:       {'ready' if manifest['text_ready'] else 'MISSING'}"
          f"  |  {manifest['turns']} turns, {manifest['tokens']} tokens")
    print(f"voice:      {'ready ' + str(manifest['voice_id']) if manifest['voice_id'] else 'not cloned'}")
    print(f"manifest:   {manifest_path(persona).relative_to(ROOT)}")
    print(f"\nchat with them:\n  python -m app.chat_cli --persona {persona}")


if __name__ == "__main__":
    main()
