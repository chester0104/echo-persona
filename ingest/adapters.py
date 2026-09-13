"""Readers for different chat export formats.

Each adapter turns one format into a flat list of {sender, ts, text} records
and knows how to spot the junk messages that format produces. The parser
never has to care where the data came from.
"""
import json
import re
from pathlib import Path

# I keep every export format in one registry so adding WhatsApp or iMessage
# later is a new class and a decorator, not a rewrite of the parser.
_REGISTRY = {}


def register(name):
    def wrap(cls):
        _REGISTRY[name] = cls
        return cls

    return wrap


def get_adapter(name):
    if name not in _REGISTRY:
        raise SystemExit(
            f"unknown chat format {name!r}; available: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[name]()


def available():
    return sorted(_REGISTRY)


class Adapter:
    name = "base"
    noise_patterns = {}

    def files(self, root):
        return sorted(Path(root).rglob("*.json"))

    def decode(self, value):
        return value

    def load(self, root):
        raise NotImplementedError

    def participants(self, root):
        raise NotImplementedError

    def classify(self, record):
        text = record.get("text")
        if text is None:
            return "media_only"
        if not text.strip():
            return "empty"
        for label, pattern in self.noise_patterns.items():
            if pattern.match(text):
                return label
        return "text"


@register("instagram")
class InstagramAdapter(Adapter):
    name = "instagram"
    noise_patterns = {
        "reaction": re.compile(r"^Reacted .{0,8} to your message\s*$", re.IGNORECASE),
        "attachment": re.compile(
            r"^(?:You|.{1,40})\s+sent an attachment\.?\s*$", re.IGNORECASE
        ),
        "call_event": re.compile(
            r"^(?:.{0,40}\s)?(?:started an audio call|started a video chat|"
            r"missed an audio call|missed a video chat|missed a call|"
            r"audio call ended|video chat ended|call ended)\.?\s*$",
            re.IGNORECASE,
        ),
        "like": re.compile(r"^Liked a message\s*$", re.IGNORECASE),
        "unsent": re.compile(
            r"^(?:You|.{1,40})\s+unsent a message\.?\s*$", re.IGNORECASE
        ),
    }

    def decode(self, value):
        if not isinstance(value, str):
            return value
        # Meta stores UTF-8 bytes as latin-1 escapes, so every apostrophe and emoji
        # comes out as garbage until I undo that. This is the single most important
        # line for keeping the style data honest.
        try:
            return value.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return value

    def _threads(self, root):
        for path in self.files(root):
            with path.open(encoding="utf-8") as handle:
                yield path, json.load(handle)

    def participants(self, root):
        names = {}
        for _, payload in self._threads(root):
            for person in payload.get("participants", []):
                name = self.decode(person.get("name", ""))
                names[name] = names.get(name, 0)
            for message in payload.get("messages", []):
                name = self.decode(message.get("sender_name", ""))
                names[name] = names.get(name, 0) + 1
        return names

    def load(self, root):
        records = []
        sources = []
        for path, payload in self._threads(root):
            sources.append(path)
            for message in payload.get("messages", []):
                content = message.get("content")
                records.append(
                    {
                        "sender": self.decode(message.get("sender_name", "")),
                        "ts": message.get("timestamp_ms", 0),
                        "text": self.decode(content) if content is not None else None,
                        "raw_fields": [k for k in message],
                    }
                )
        # The export is newest first, which is backwards for building conversations.
        records.sort(key=lambda r: r["ts"])
        return records, sources


@register("generic")
class GenericAdapter(Adapter):
    name = "generic"

    def _rows(self, root):
        for path in self.files(root):
            with path.open(encoding="utf-8") as handle:
                payload = json.load(handle)
            rows = payload if isinstance(payload, list) else payload.get("messages", [])
            yield path, rows

    def participants(self, root):
        names = {}
        for _, rows in self._rows(root):
            for row in rows:
                name = row.get("sender") or row.get("sender_name") or row.get("from", "")
                names[name] = names.get(name, 0) + 1
        return names

    def load(self, root):
        records = []
        sources = []
        for path, rows in self._rows(root):
            sources.append(path)
            for row in rows:
                text = row.get("text", row.get("content"))
                records.append(
                    {
                        "sender": row.get("sender")
                        or row.get("sender_name")
                        or row.get("from", ""),
                        "ts": row.get("ts", row.get("timestamp_ms", 0)),
                        "text": text,
                        "raw_fields": [k for k in row],
                    }
                )
        records.sort(key=lambda r: r["ts"])
        return records, sources
