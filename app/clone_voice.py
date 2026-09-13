"""Creates the ElevenLabs instant clone and saves the voice_id.

It refuses to run twice for the same persona unless you pass --force.
"""
import argparse

from app.audio import audio_info, format_duration
from app.elevenlabs import add_voice, api_key, get_voice_id, record_voice_id, subscription
from ingest.personas import (
    ROOT,
    VOICE_STORE_HINT,
    load_persona,
    load_runtime,
    voice_enabled,
    voice_path,
)

# One minute is the floor for instant cloning. I got noticeably better results
# at three minutes, so the script warns under that.
MIN_SECONDS = 60


def main():
    parser = argparse.ArgumentParser(
        description="Create an ElevenLabs instant voice clone from cleaned audio."
    )
    parser.add_argument("--persona")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--source", choices=["clean", "converted"], default="clean")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    persona_cfg = load_persona(args.persona)
    persona = persona_cfg["persona"]
    runtime_cfg = load_runtime()

    if not voice_enabled(persona_cfg):
        raise SystemExit(f"voice is disabled for persona {persona!r}")

    existing = get_voice_id(persona)
    if existing and not args.force:
        print(f"persona {persona!r} already has voice_id {existing}")
        print(VOICE_STORE_HINT)
        print("pass --force only if you really want a second clone on the account")
        return

    src_dir = voice_path(persona_cfg) / args.source
    files = sorted(src_dir.glob("*.mp3"))
    if not files:
        raise SystemExit(
            f"no mp3 files in {src_dir}; run convert_voice and denoise_voice first"
        )

    total = 0.0
    print(f"source: {src_dir.relative_to(ROOT)}")
    for path in files:
        info = audio_info(path)
        total += info["duration"]
        print(f"  {path.name:16} {format_duration(info['duration']):>6}")
    print(f"  {'total':16} {format_duration(total):>6}")

    if total < MIN_SECONDS:
        raise SystemExit(
            f"only {total:.0f}s of audio; ElevenLabs instant cloning needs at least "
            f"{MIN_SECONDS}s and works far better with 2-3 minutes"
        )

    name = persona_cfg.get("voice", {}).get(
        "clone_name", f"echo-persona {persona_cfg.get('display_name', persona)}"
    )

    if args.dry_run:
        print(f"\ndry run: would POST {len(files)} file(s) to /v1/voices/add as {name!r}")
        return

    key = api_key(runtime_cfg)
    try:
        plan = subscription(key)
        used = plan.get("character_count")
        limit = plan.get("character_limit")
        if used is not None and limit:
            print(f"quota: {used:,} / {limit:,} characters used")
    except SystemExit as exc:
        print(f"note: could not read subscription ({exc})")

    print(f"\ncreating clone {name!r} from {len(files)} file(s)...")
    result = add_voice(
        key,
        name,
        files,
        description=(
            f"Instant voice clone of {persona_cfg.get('display_name', persona)}, "
            "created with recorded consent for personal use."
        ),
        labels={"project": "echo-persona", "persona": persona},
    )

    voice_id = result.get("voice_id")
    if not voice_id:
        raise SystemExit(f"no voice_id in response: {result}")

    entry = record_voice_id(
        persona,
        voice_id,
        name,
        [str(p.relative_to(ROOT)) for p in files],
        result.get("requires_verification"),
    )
    print(f"voice_id: {voice_id}")
    print(f"saved to: {VOICE_STORE_HINT}")
    if entry.get("requires_verification"):
        print("note: ElevenLabs flagged this voice as requiring verification")


if __name__ == "__main__":
    main()
