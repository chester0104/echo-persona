"""Converts whatever is in voice/<name>/ to mp3.
"""
import argparse
from pathlib import Path

from app.audio import audio_info, find_tool, format_duration, run
from ingest.personas import ROOT, load_persona, voice_enabled, voice_path

SOURCE_EXTS = (".mp4", ".m4a", ".mov", ".webm", ".mkv", ".wav", ".aac", ".mp3", ".flac", ".ogg", ".opus")


def source_files(voice_dir):
    files = []
    for path in sorted(voice_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in SOURCE_EXTS:
            if "converted" in path.parts or "clean" in path.parts:
                continue
            files.append(path)
    return files


# Mono at 44.1 kHz. ElevenLabs downmixes anyway and mono avoids any stereo
# phase weirdness ending up in the clone.
def convert(src, dest, bitrate, sample_rate, channels):
    dest.parent.mkdir(parents=True, exist_ok=True)
    args = [
        find_tool("ffmpeg"),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(src),
        "-vn",
        "-map",
        "0:a:0",
        "-ar",
        str(sample_rate),
        "-ac",
        str(channels),
        "-c:a",
        "libmp3lame",
        "-b:a",
        bitrate,
        str(dest),
    ]
    run(args)
    return dest


def main():
    parser = argparse.ArgumentParser(description="Convert raw voice clips to mp3.")
    parser.add_argument("--persona")
    parser.add_argument("--bitrate", default="192k")
    parser.add_argument("--sample-rate", type=int, default=44100)
    parser.add_argument("--channels", type=int, default=1)
    args = parser.parse_args()

    cfg = load_persona(args.persona)
    if not voice_enabled(cfg):
        raise SystemExit(f"voice is disabled for persona {cfg['persona']!r}")
    voice_dir = voice_path(cfg)
    out_dir = voice_dir / "converted"

    files = source_files(voice_dir)
    if not files:
        raise SystemExit(f"no source clips found under {voice_dir}")

    rows = []
    total = 0.0
    for src in files:
        info = audio_info(src)
        if not info["has_audio"]:
            print(f"skipped {src.name}: no audio stream")
            continue
        dest = out_dir / (src.stem + ".mp3")
        convert(src, dest, args.bitrate, args.sample_rate, args.channels)
        out_info = audio_info(dest)
        total += out_info["duration"]
        rows.append((src, info, dest, out_info))

    width = max(len(r[2].name) for r in rows)
    print(f"converted {len(rows)} file(s) -> {out_dir.relative_to(ROOT)}")
    print("")
    print(
        f"{'file'.ljust(width)}  {'duration':>8}  {'size':>9}  source"
    )
    for src, info, dest, out_info in rows:
        size = f"{out_info['size_bytes'] / 1024:.0f} KB"
        source = (
            f"{info['codec']} {info['sample_rate']} Hz "
            f"{info['channels']}ch {info['size_bytes'] / 1024:.0f} KB"
        )
        print(
            f"{dest.name.ljust(width)}  {format_duration(out_info['duration']):>8}  "
            f"{size:>9}  {source}"
        )
    print("")
    print(f"total audio: {format_duration(total)} ({total:.1f}s)")
    if total < 60:
        print("")
        print(
            "WARNING: ElevenLabs instant voice cloning wants at least about 1 minute of "
            "clean speech, and works much better with 2-3 minutes. "
            f"You have {total:.0f}s."
        )


if __name__ == "__main__":
    main()
