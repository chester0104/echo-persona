"""Builds the system prompt: the measured style card plus real exchanges.

Names are redacted first. Where the other person's name is a form of address
I strip it, and where it survives in the sentence I drop that exchange rather
than mangle it.
"""
import argparse
import datetime
import hashlib
import json
import pathlib
import random

from app import style
from app.redact import Redactor
from app.teach import load_facts
from ingest.personas import (
    load_persona,
    load_runtime,
    prompt_path,
    style_path,
    turns_path,
)

THEM = ">"
HER = "<"


def collect_exchanges(records, max_chars, redactor=None):
    exchanges = []
    dropped = 0
    for index, record in enumerate(records):
        turns = record["messages"]
        for i in range(len(turns) - 1):
            if turns[i]["role"] != "user" or turns[i + 1]["role"] != "assistant":
                continue
            prompt_text = turns[i]["content"]
            reply_text = turns[i + 1]["content"]
            if redactor is not None:
                prompt_text = redactor.clean(prompt_text)
                reply_text = redactor.clean(reply_text)
                if not redactor.is_clean(prompt_text) or not redactor.is_clean(reply_text):
                    dropped += 1
                    continue
            if not prompt_text.strip() or not reply_text.strip():
                continue
            if len(prompt_text) + len(reply_text) > max_chars:
                continue
            exchanges.append(
                {
                    "conversation": index,
                    "position": i,
                    "prompt": prompt_text,
                    "reply": reply_text,
                }
            )
    return exchanges, dropped


# Round-robin across conversations so the examples cover the whole history
# instead of clustering in whichever conversation was longest. Seeded so the
# prompt is byte identical between runs, which is what makes caching work.
def select(exchanges, count, seed):
    if len(exchanges) <= count:
        chosen = list(exchanges)
    else:
        by_conversation = {}
        for item in exchanges:
            by_conversation.setdefault(item["conversation"], []).append(item)
        rng = random.Random(seed)
        keys = sorted(by_conversation)
        for key in keys:
            rng.shuffle(by_conversation[key])
        chosen = []
        cursor = 0
        while len(chosen) < count:
            progressed = False
            for key in keys:
                bucket = by_conversation[key]
                if cursor < len(bucket):
                    chosen.append(bucket[cursor])
                    progressed = True
                    if len(chosen) == count:
                        break
            if not progressed:
                break
            cursor += 1
    chosen.sort(key=lambda item: (item["conversation"], item["position"]))
    return chosen


def format_exchange(item):
    lines = []
    for line in item["prompt"].split("\n"):
        lines.append(f"{THEM} {line}")
    for line in item["reply"].split("\n"):
        lines.append(f"{HER} {line}")
    return "\n".join(lines)


def _pretty_date(value):
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value).strftime("%d %B %Y")
    except (TypeError, ValueError):
        return str(value)


def build(persona_cfg, runtime_cfg, include_sensitive=True):
    persona = persona_cfg["persona"]
    name = persona_cfg.get("display_name", persona)
    pronoun = persona_cfg.get("pronoun", "they")
    possessive = {"she": "her", "he": "his", "they": "their"}.get(pronoun, "their")
    subject = {"she": "she", "he": "he", "they": "they"}.get(pronoun, "they")
    prompt_cfg = runtime_cfg.get("prompt", {})
    count = int(prompt_cfg.get("example_exchanges", 300))
    seed = int(prompt_cfg.get("example_selection_seed", 11))
    max_chars = int(prompt_cfg.get("max_example_chars", 900))
    redactor = Redactor(persona_cfg) if prompt_cfg.get("redact_names", True) else None

    records = style.load_records(turns_path(persona))
    stats = style.derive(records, exclude_words=redactor.variants if redactor else None)
    habits = style.render(
        stats,
        name,
        persona_cfg.get("style_notes"),
        pronoun,
        persona_cfg.get("profile"),
        include_sensitive,
        persona_cfg.get("background"),
        _pretty_date(persona_cfg.get("data_through")),
        persona_cfg.get("current"),
        load_facts(persona),
    )

    emoji_gap = max(2, round(100 / max(stats['pct_with_emoji'], 0.5)))
    pool, redacted_out = collect_exchanges(records, max_chars, redactor)
    exchanges = select(pool, count, seed)
    body = "\n\n".join(format_exchange(item) for item in exchanges)

    header = (
        f"You are {name}. You are not an AI assistant. You never break character, "
        "never mention being a model or a clone, and never slip into a helpful "
        "assistant voice.\n\n"
        "You are texting someone you have just started talking to. You do not know "
        "who they are, you do not know their name, and you have no shared history "
        f"with them. Everything below is how {subject} texts, not who {subject} is texting.\n\n"
        f"{habits}\n\n"
        f"Below are {len(exchanges)} real exchanges from {possessive} message history, kept only "
        "as a model of rhythm and voice. Names and personal references have been "
        f"stripped. Lines starting with {THEM} are what the other person sent. "
        f"Lines starting with {HER} are what {name} sent back. "
        "Consecutive lines with the same marker are separate messages sent in a burst.\n\n"
        "=== EXAMPLES ===\n"
    )
    footer = (
        "\n=== END EXAMPLES ===\n\n"
        f"Reply as {name} would to a new person. Output only {possessive} messages, nothing "
        "else. Put each separate message on its own line, with no markers, no quotes "
        "and no narration. Usually one to three lines. Match the length, "
        "capitalisation, punctuation and emoji habits above exactly.\n\n"
        "Hard rules:\n"
        f"- Emoji discipline: about 1 message in {emoji_gap} carries an emoji. "
        f"That means most replies contain none at all. Do not put an emoji in every "
        f"message and never more than one in a message.\n"
        f"- Length discipline: aim for {stats['chars_median']} characters per message. "
        "Short fragments, not sentences.\n"
        "- Never address the other person by a name. You have not been told one. "
        "If they tell you their name, you may use it from then on.\n"
        "- Never refer to shared memories, past conversations, mutual friends or "
        "in-jokes from the examples. Those happened with someone else. To you this "
        "person is new.\n"
        "- Do not invent names for people or places unless the other person brings "
        "them up first."
    )
    return header + body + footer, stats, len(exchanges), redacted_out


# The prompt is written to disk once and reused verbatim. If I rebuilt it on
# every call the cached prefix would shift and I would pay full price each
# time.
# Every rebuild stamps today into the config as data_through, so the
# "knowledge cutoff" shown on the site is the last time the persona actually
# changed rather than a date I typed once.
def stamp_data_through(persona_cfg):
    today = datetime.date.today().isoformat()
    if persona_cfg.get("data_through") == today:
        return
    persona_cfg["data_through"] = today
    path = pathlib.Path(persona_cfg["_path"])
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["data_through"] = today
    path.write_text(json.dumps(stored, indent=2, ensure_ascii=False), encoding="utf-8")


def load_or_build(persona_cfg, runtime_cfg, rebuild=False):
    persona = persona_cfg["persona"]
    path = prompt_path(persona)
    if path.exists() and not rebuild:
        return path.read_text(encoding="utf-8")
    stamp_data_through(persona_cfg)
    text, stats, count, redacted_out = build(persona_cfg, runtime_cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    style_path(persona).write_text(
        json.dumps(
            {"exchanges": count, "exchanges_dropped_for_names": redacted_out, **stats},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--persona")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--show-habits", action="store_true")
    args = parser.parse_args()

    persona_cfg = load_persona(args.persona)
    runtime_cfg = load_runtime()
    text = load_or_build(persona_cfg, runtime_cfg, rebuild=args.rebuild)

    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    try:
        import tiktoken

        tokens = len(tiktoken.get_encoding("o200k_base").encode(text))
    except Exception:
        tokens = None

    print(f"persona:   {persona_cfg['persona']}")
    print(f"path:      {prompt_path(persona_cfg['persona'])}")
    print(f"bytes:     {len(text.encode('utf-8'))}")
    print(f"tokens:    {tokens if tokens is not None else 'unknown (tiktoken missing)'}")
    print(f"sha256:    {digest}")
    stats_blob = json.loads(style_path(persona_cfg["persona"]).read_text(encoding="utf-8"))
    print(f"exchanges: {stats_blob['exchanges']}")
    print(f"dropped for names: {stats_blob.get('exchanges_dropped_for_names', 0)}")
    if args.show_habits:
        print()
        print(text.split("=== EXAMPLES ===")[0])


if __name__ == "__main__":
    main()


# Anything that changes with the date goes here, as a separate message after
# the cached prompt. Putting the date inside the prompt would break the cache.
def dynamic_context(persona_cfg, today=None):
    today = today or datetime.date.today()
    name = persona_cfg.get("display_name", persona_cfg["persona"])
    pronoun = persona_cfg.get("pronoun", "they")
    subject = {"she": "she", "he": "he", "they": "they"}.get(pronoun, "they")
    parts = [f"Today is {today.strftime('%A %d %B %Y')}."]

    for item in (persona_cfg.get("background") or {}).get("timeline", []):
        try:
            when = datetime.date.fromisoformat(item["date"])
        except (KeyError, ValueError):
            continue
        months = (when.year - today.year) * 12 + (when.month - today.month)
        event = item.get("event", "that milestone")
        if months > 1:
            years, rest = divmod(months, 12)
            span = f"{years} year{'s' if years != 1 else ''}" if years else ""
            if rest:
                span = f"{span} and {rest} month{'s' if rest != 1 else ''}" if span else f"{rest} months"
            parts.append(f"{name} {event} in {when.strftime('%B %Y')}, about {span} away.")
        elif months >= 0:
            parts.append(f"{name} {event} this month.")
        else:
            ago = abs(months)
            years, rest = divmod(ago, 12)
            span = f"{years} year{'s' if years != 1 else ''}" if years else f"{rest} months"
            parts.append(
                f"{name} already {event.replace('finishes', 'finished')} in "
                f"{when.strftime('%B %Y')}, {span} ago, so {subject} is out of that now."
            )

    parts.append(
        "Let that shape what is going on in your life right now. Do not announce the date."
    )
    return " ".join(parts)
