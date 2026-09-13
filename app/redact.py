"""Keeps the other person's name out of the prompt.

The clone is meant to talk to strangers, and it kept using the other person's
name because the examples were full of it.
"""
import re
import unicodedata

GENERIC_TOKENS = {"chen", "the", "and"}


def normalise(value):
    return unicodedata.normalize("NFKC", value or "").strip()


def name_variants(*sources):
    variants = set()
    for source in sources:
        if not source:
            continue
        if isinstance(source, (list, tuple, set)):
            for item in source:
                variants |= name_variants(item)
            continue
        text = normalise(source)
        if not text:
            continue
        variants.add(text)
        for part in re.split(r"[\s._-]+", text):
            if len(part) >= 3 and part.lower() not in GENERIC_TOKENS:
                variants.add(part)
    return {v for v in variants if len(v) >= 3}


def build_pattern(variants):
    if not variants:
        return None
    ordered = sorted(variants, key=len, reverse=True)
    joined = "|".join(re.escape(v) for v in ordered)
    return re.compile(rf"\b(?:{joined})\b", re.IGNORECASE)


# "What happened Sam" becomes "What happened". I only strip the name when
# it is a form of address at the start or end of a line, because deleting it
# from the middle of a sentence leaves a broken sentence.
def strip_vocatives(text, pattern):
    if pattern is None:
        return text
    out = []
    for line in text.split("\n"):
        previous = None
        while previous != line:
            previous = line
            line = re.sub(
                rf"\s*[,!]?\s*{pattern.pattern}\s*([?!.]*)\s*$",
                r"\1",
                line,
                flags=re.IGNORECASE,
            )
            line = re.sub(
                rf"^\s*{pattern.pattern}\s*[,!:]+\s*",
                "",
                line,
                flags=re.IGNORECASE,
            )
        out.append(line.rstrip())
    return "\n".join(out)


def contains(text, pattern):
    return bool(pattern and pattern.search(text))


class Redactor:
    def __init__(self, persona_cfg):
        chat_cfg = persona_cfg.get("chat", {})
        variants = name_variants(
            chat_cfg.get("other_sender"),
            chat_cfg.get("other_display_name"),
            persona_cfg.get("redact_names", []),
        )
        self.variants = variants
        self.pattern = build_pattern(variants)

    def clean(self, text):
        return strip_vocatives(text, self.pattern)

    def is_clean(self, text):
        return not contains(text, self.pattern)

    def describe(self):
        return ", ".join(sorted(self.variants)) or "(nothing)"
