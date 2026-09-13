"""Speaks a reply in the cloned voice, with a cache so repeats are free.
"""
import hashlib
import re
import subprocess

from app.elevenlabs import api_key, get_voice_id, text_to_speech
from ingest.personas import audio_dir

EMOJI_RE = re.compile("[\U0001f000-\U0001faff☀-➿←-⇿⬀-⯿️]")
WHITESPACE_RE = re.compile(r"[ \t]+")


# Emoji get stripped and each line gets a full stop so the voice pauses
# between messages instead of running them together.
def speakable(text):
    lines = []
    for line in text.split("\n"):
        line = EMOJI_RE.sub("", line)
        line = WHITESPACE_RE.sub(" ", line).strip()
        if not line:
            continue
        if line[-1] not in ".!?,:;":
            line += "."
        lines.append(line)
    return " ".join(lines)


class Speaker:
    def __init__(self, persona_cfg, runtime_cfg):
        tts_cfg = runtime_cfg.get("tts", {})
        self.persona = persona_cfg["persona"]
        self.model_id = tts_cfg.get("model_id", "eleven_multilingual_v2")
        self.output_format = tts_cfg.get("output_format", "mp3_44100_128")
        self.settings = tts_cfg.get("voice_settings", {})
        self.autoplay = tts_cfg.get("autoplay", True)
        self.voice_id = get_voice_id(self.persona) or tts_cfg.get("fallback_voice_id")
        if not self.voice_id:
            raise SystemExit(
                f"no voice_id for persona {self.persona!r}; run python -m app.clone_voice"
            )
        self.key = api_key(runtime_cfg)
        self.cache_dir = audio_dir(self.persona)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.last_path = None
        self.last_cached = None

    # The hash includes the voice id and settings, not just the text. Changing
    # stability should regenerate, repeating a line should not.
    def cache_key(self, text):
        blob = "|".join(
            [
                self.voice_id,
                self.model_id,
                self.output_format,
                repr(sorted(self.settings.items())),
                text,
            ]
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]

    def synthesise(self, text):
        spoken = speakable(text)
        if not spoken:
            return None
        path = self.cache_dir / f"{self.cache_key(spoken)}.mp3"
        if path.exists():
            self.last_path, self.last_cached = path, True
            return path
        audio = text_to_speech(
            self.key,
            self.voice_id,
            spoken,
            self.model_id,
            self.output_format,
            self.settings,
        )
        path.write_bytes(audio)
        self.last_path, self.last_cached = path, False
        return path

    def play(self, path):
        from app.audio import find_tool

        subprocess.run(
            [
                find_tool("ffplay"),
                "-nodisp",
                "-autoexit",
                "-loglevel",
                "quiet",
                str(path),
            ],
            check=False,
        )

    def speak(self, text):
        path = self.synthesise(text)
        if path and self.autoplay:
            self.play(path)
        return path
