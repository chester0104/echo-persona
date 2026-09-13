"""ffmpeg helpers: finding the binary, probing files, measuring levels.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

# winget installs ffmpeg but the PATH shim needs a new shell, so I also look
# in the places it actually puts the binary.
SEARCH_GLOBS = [
    "{localappdata}/Microsoft/WinGet/Links/{name}.exe",
    "{localappdata}/Microsoft/WinGet/Packages/Gyan.FFmpeg*/*/bin/{name}.exe",
    "{programfiles}/ffmpeg/bin/{name}.exe",
    "C:/ffmpeg/bin/{name}.exe",
]

_CACHE = {}


def find_tool(name):
    if name in _CACHE:
        return _CACHE[name]

    override = os.environ.get(f"{name.upper()}_BINARY")
    if override and Path(override).exists():
        _CACHE[name] = override
        return override

    found = shutil.which(name)
    if found:
        _CACHE[name] = found
        return found

    fields = {
        "name": name,
        "localappdata": os.environ.get("LOCALAPPDATA", ""),
        "programfiles": os.environ.get("ProgramFiles", ""),
    }
    for pattern in SEARCH_GLOBS:
        template = pattern.format(**fields)
        base, _, tail = template.partition("*")
        if not tail:
            if Path(template).exists():
                _CACHE[name] = template
                return template
            continue
        root = Path(base).parent
        if not root.exists():
            continue
        rest = template[len(str(root)) + 1 :]
        matches = sorted(root.glob(rest))
        if matches:
            _CACHE[name] = str(matches[0])
            return str(matches[0])

    raise SystemExit(
        f"{name} not found. Install it (winget install Gyan.FFmpeg) or set "
        f"{name.upper()}_BINARY to its full path."
    )


def run(args):
    result = subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        raise SystemExit(
            f"{Path(args[0]).name} failed ({result.returncode}):\n{result.stderr[-1500:]}"
        )
    return result


def probe(path):
    result = run(
        [
            find_tool("ffprobe"),
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
    )
    return json.loads(result.stdout)


def audio_info(path):
    data = probe(path)
    stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None
    )
    fmt = data.get("format", {})
    duration = float(fmt.get("duration") or (stream or {}).get("duration") or 0.0)
    return {
        "path": Path(path),
        "duration": duration,
        "size_bytes": int(fmt.get("size") or Path(path).stat().st_size),
        "codec": (stream or {}).get("codec_name"),
        "sample_rate": int((stream or {}).get("sample_rate") or 0),
        "channels": int((stream or {}).get("channels") or 0),
        "has_audio": stream is not None,
    }


def measure_loudness(path):
    result = subprocess.run(
        [
            find_tool("ffmpeg"),
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-af",
            "ebur128=peak=true",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = {}
    for line in result.stderr.splitlines():
        stripped = line.strip()
        for key, label in (("I:", "lufs"), ("LRA:", "lra"), ("Peak:", "peak_db")):
            if stripped.startswith(key):
                token = stripped.split()
                if len(token) >= 2:
                    try:
                        out[label] = float(token[1])
                    except ValueError:
                        pass
    return out


def format_duration(seconds):
    minutes, secs = divmod(int(round(seconds)), 60)
    return f"{minutes}:{secs:02d}"


# ffmpeg's astats "noise floor" reads the silence padding and reports -100 dB
# for everything, which is useless. This decodes to PCM and takes the 10th
# percentile of windowed RMS, which is the actual noise bed between words.
def level_profile(path, window_ms=50, sample_rate=16000):
    import numpy as np

    result = subprocess.run(
        [
            find_tool("ffmpeg"),
            "-v",
            "error",
            "-i",
            str(path),
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-f",
            "s16le",
            "-",
        ],
        capture_output=True,
    )
    if result.returncode != 0 or not result.stdout:
        return {}
    samples = np.frombuffer(result.stdout, dtype="<i2").astype(np.float32) / 32768.0
    size = max(1, int(sample_rate * window_ms / 1000))
    usable = len(samples) - (len(samples) % size)
    if usable < size:
        return {}
    frames = samples[:usable].reshape(-1, size)
    rms = np.sqrt((frames ** 2).mean(axis=1))
    db = 20 * np.log10(np.maximum(rms, 1e-7))
    return {
        "noise_p10": float(np.percentile(db, 10)),
        "speech_p90": float(np.percentile(db, 90)),
        "snr": float(np.percentile(db, 90) - np.percentile(db, 10)),
    }
