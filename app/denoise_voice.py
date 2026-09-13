"""Cleans the converted audio without touching the originals.

The big wins were declipping and levelling the clips to a common loudness.
The denoiser itself did less than I expected on already clean recordings.
"""
import argparse
import json
import re
import subprocess

from app.audio import (
    audio_info,
    find_tool,
    format_duration,
    level_profile,
    measure_loudness,
    run,
)
from ingest.personas import ROOT, load_persona, load_runtime, voice_enabled, voice_path

NOISE_FLOOR_RE = re.compile(r"Noise floor dB:\s*(-?[\d.]+)")


def noise_floor(path):
    result = subprocess.run(
        [
            find_tool("ffmpeg"),
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-af",
            "astats=measure_overall=Noise_floor:measure_perchannel=none",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    match = NOISE_FLOOR_RE.search(result.stderr)
    return float(match.group(1)) if match else None


# adeclip fixes clipping first, highpass drops rumble under 70 Hz, and afftdn
# does conservative spectral denoising. I measured this on the real clips and
# pushing nr higher bought 0.2 dB while risking the breathiness the clone
# needs, so it stays at 12.
def clean_chain(cfg):
    steps = []
    if cfg.get("declip", True):
        steps.append("adeclip")
    steps.append(f"highpass=f={cfg.get('highpass_hz', 70)}")
    steps.append(
        f"afftdn=nr={cfg.get('afftdn_nr', 12)}:nf={cfg.get('afftdn_nf', -25)}:tn=1"
    )
    return steps


def loudnorm_filter(cfg, measured=None):
    base = (
        f"loudnorm=I={cfg.get('target_lufs', -16.0)}"
        f":TP={cfg.get('true_peak', -1.5)}"
        f":LRA={cfg.get('lra', 11.0)}"
    )
    if not measured:
        return base
    return (
        base
        + f":measured_I={measured['input_i']}"
        + f":measured_TP={measured['input_tp']}"
        + f":measured_LRA={measured['input_lra']}"
        + f":measured_thresh={measured['input_thresh']}"
        + f":offset={measured['target_offset']}"
        + ":linear=true:print_format=summary"
    )


# Two-pass loudnorm. The first pass measures, the second applies the measured
# values linearly, which sounds better than single-pass dynamic mode.
def measure_pass(src, cfg):
    chain = ",".join(clean_chain(cfg) + [loudnorm_filter(cfg) + ":print_format=json"])
    result = subprocess.run(
        [
            find_tool("ffmpeg"),
            "-hide_banner",
            "-nostats",
            "-i",
            str(src),
            "-af",
            chain,
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    start = result.stderr.rfind("{")
    end = result.stderr.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        data = json.loads(result.stderr[start : end + 1])
    except json.JSONDecodeError:
        return None
    if any(
        data.get(k) in (None, "-inf", "inf")
        for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
    ):
        return None
    return data


def clean_file(src, dest, cfg):
    dest.parent.mkdir(parents=True, exist_ok=True)
    measured = measure_pass(src, cfg)
    chain = ",".join(clean_chain(cfg) + [loudnorm_filter(cfg, measured)])
    run(
        [
            find_tool("ffmpeg"),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(src),
            "-af",
            chain,
            "-ar",
            str(cfg.get("sample_rate", 44100)),
            "-ac",
            str(cfg.get("channels", 1)),
            "-c:a",
            "libmp3lame",
            "-b:a",
            cfg.get("bitrate", "192k"),
            str(dest),
        ]
    )
    return dest, bool(measured)


def main():
    parser = argparse.ArgumentParser(description="Clean background noise from voice clips.")
    parser.add_argument("--persona")
    parser.add_argument("--nr", type=float)
    parser.add_argument("--target-lufs", type=float)
    args = parser.parse_args()

    persona_cfg = load_persona(args.persona)
    cfg = dict(load_runtime().get("denoise", {}))
    if args.nr is not None:
        cfg["afftdn_nr"] = args.nr
    if args.target_lufs is not None:
        cfg["target_lufs"] = args.target_lufs

    if not voice_enabled(persona_cfg):
        raise SystemExit(f"voice is disabled for persona {persona_cfg['persona']!r}")
    voice_dir = voice_path(persona_cfg)
    src_dir = voice_dir / "converted"
    out_dir = voice_dir / "clean"

    sources = sorted(src_dir.glob("*.mp3"))
    if not sources:
        raise SystemExit(
            f"no mp3 files in {src_dir}; run python -m app.convert_voice first"
        )

    print("filter chain: " + ",".join(clean_chain(cfg) + ["loudnorm(two-pass)"]))
    print("")

    rows = []
    total = 0.0
    for src in sources:
        before_loud = measure_loudness(src)
        before_prof = level_profile(src)
        dest, two_pass = clean_file(src, out_dir / src.name, cfg)
        after = audio_info(dest)
        after_loud = measure_loudness(dest)
        after_prof = level_profile(dest)
        total += after["duration"]
        rows.append(
            {
                "name": dest.name,
                "duration": after["duration"],
                "before_lufs": before_loud.get("lufs"),
                "after_lufs": after_loud.get("lufs"),
                "before_peak": before_loud.get("peak_db"),
                "after_peak": after_loud.get("peak_db"),
                "before_floor": before_prof.get("noise_p10"),
                "after_floor": after_prof.get("noise_p10"),
                "before_snr": before_prof.get("snr"),
                "after_snr": after_prof.get("snr"),
                "two_pass": two_pass,
            }
        )

    width = max(len(r["name"]) for r in rows)
    header = (
        f"{'file'.ljust(width)}  {'dur':>6}  {'LUFS in':>8}  {'LUFS out':>9}"
        f"  {'peak out':>9}  {'noise in':>9}  {'noise out':>10}  {'SNR in':>7}  {'SNR out':>8}"
    )
    print(header)
    for r in rows:
        def fmt(value, suffix=""):
            return f"{value:.1f}{suffix}" if isinstance(value, float) else "?"

        print(
            f"{r['name'].ljust(width)}  {format_duration(r['duration']):>6}  "
            f"{fmt(r['before_lufs']):>8}  {fmt(r['after_lufs']):>9}  "
            f"{fmt(r['after_peak']):>9}  "
            f"{fmt(r['before_floor']):>9}  {fmt(r['after_floor']):>10}  "
            f"{fmt(r['before_snr']):>7}  {fmt(r['after_snr']):>8}"
        )
    print("")
    print(f"{len(rows)} file(s) -> {out_dir.relative_to(ROOT)}")
    print(f"total audio: {format_duration(total)} ({total:.1f}s)")
    if not all(r["two_pass"] for r in rows):
        print("note: some files fell back to single-pass loudness normalisation")


if __name__ == "__main__":
    main()
