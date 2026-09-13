"""Measures how someone texts and writes it up as prompt instructions.

Everything in here is counting. No model is involved, so it costs nothing to
run and gives the same answer every time.
"""
import json
import math
import re
from collections import Counter

WORD_RE = re.compile(r"[a-z][a-z']*")
EMOJI_RE = re.compile(
    "[\U0001f000-\U0001faff☀-➿←-⇿⬀-⯿]"
)
APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "`": "'"})
STOPWORDS = {
    "a", "about", "after", "all", "also", "am", "an", "and", "any", "are", "as", "at",
    "be", "because", "been", "before", "being", "but", "by", "can", "could", "did",
    "do", "does", "doing", "done", "for", "from", "get", "got", "had", "has", "have",
    "he", "her", "here", "hers", "him", "his", "how", "i", "if", "in", "into", "is",
    "it", "its", "just", "me", "more", "most", "my", "no", "not", "now", "of", "on",
    "one", "only", "or", "other", "our", "out", "over", "own", "she", "so", "some",
    "still", "such", "than", "that", "the", "their", "them", "then", "there", "these",
    "they", "this", "those", "to", "too", "up", "us", "very", "was", "we", "were",
    "what", "when", "where", "which", "while", "who", "why", "will", "with", "would",
    "you", "your", "yours", "im", "ive", "id", "ill", "youre", "its",
}


# These are the tone markers that separate a real texter from a chatbot. The
# big ones turned out to be exclamation marks and one word replies. A model
# left alone uses way more of the first and almost none of the second.
TONE_PATTERNS = {
    "one_word": r"^[\w']{1,6}$",
    "exclaim": r"!",
    "profanity": r"\b(fuck|shit|damn|hell|ass|bitch|crap|wtf|stfu|af)\b|fuck",
    "pushback": r"^(no|nah|nope|wtf|why would|that ?s not|thats not|i don ?t think|stop|don ?t)\b",
    "teasing": r"\b(loser|idiot|stupid|dumb|weirdo|freak|ugly|annoying|cringe|lame|shut up|ew)\b",
    "affection": r"\b(love|miss|cute|sweet|proud|bestie|babe)\b",
    "laughing": r"\b(lmao|lol|lmfao|hahah?a?|dying|deceased|crying)\b",
    "hedging": r"\b(maybe|i think|kind of|sort of|probably|i guess|no worries|it ?s okay)\b",
}


def tone_profile(lines):
    total = len(lines) or 1
    out = {}
    for label, pattern in TONE_PATTERNS.items():
        rx = re.compile(pattern, re.IGNORECASE)
        out[label] = round(100 * sum(1 for line in lines if rx.search(line)) / total, 1)
    return out


def _lines(turns):
    out = []
    for turn in turns:
        for line in turn.split("\n"):
            line = line.strip()
            if line:
                out.append(line)
    return out


def _side(records, role):
    return [t["content"] for r in records for t in r["messages"] if t["role"] == role]


def _tokens(texts):
    joined = " ".join(texts).lower().translate(APOSTROPHES)
    return Counter(WORD_RE.findall(joined))


MIDLINE_CAP_RE = re.compile(r"(?<!^)(?<![.!?]\s)\b([A-Za-z][A-Za-z']{2,})\b")


# A word that is capitalised mid-sentence most of the time is probably a name.
# I use this to keep names out of the vocabulary list.
def proper_nouns(texts, threshold=0.5):
    upper = Counter()
    total = Counter()
    for text in texts:
        for line in text.split("\n"):
            line = line.strip().translate(APOSTROPHES)
            for match in MIDLINE_CAP_RE.finditer(line):
                word = match.group(1)
                key = word.lower()
                total[key] += 1
                if word[0].isupper() and not word.isupper():
                    upper[key] += 1
    return {
        word
        for word, count in total.items()
        if count >= 3 and upper[word] / count > threshold
    }


# Words the persona uses far more than the other person. The log ratio times
# sqrt(count) favours words that are both distinctive and common enough to
# matter, so a one-off typo does not win.
def distinctive_words(mine, theirs, limit=18, exclude=None):
    exclude = exclude or set()
    mine_counts = _tokens(mine)
    their_counts = _tokens(theirs)
    mine_total = sum(mine_counts.values()) or 1
    their_total = sum(their_counts.values()) or 1
    scored = []
    for word, count in mine_counts.items():
        if count < 8 or len(word) < 2:
            continue
        if word in STOPWORDS or word.strip("'") in STOPWORDS:
            continue
        if word in exclude or word.strip("'") in exclude:
            continue
        if word.endswith("n't") or word.endswith("'s") or word.endswith("'ll"):
            continue
        mine_rate = count / mine_total
        their_rate = (their_counts.get(word, 0) + 0.5) / their_total
        ratio = mine_rate / their_rate
        if ratio > 1.3:
            scored.append((math.log(ratio) * math.sqrt(count), word, count))
    scored.sort(reverse=True)
    return [(word, count) for _, word, count in scored[:limit]]


def derive(records, exclude_words=None):
    mine = _side(records, "assistant")
    theirs = _side(records, "user")
    lines = _lines(mine)
    if not lines:
        raise SystemExit("no assistant turns found; check clone_sender in the persona config")

    lengths = sorted(len(line) for line in lines)
    median = lengths[len(lengths) // 2]
    starts_upper = sum(1 for line in lines if line[0].isupper())
    starts_lower = sum(1 for line in lines if line[0].islower())
    cased = starts_upper + starts_lower or 1
    ends_period = sum(1 for line in lines if line.endswith("."))
    questions = sum(1 for line in lines if "?" in line)
    shouty = sum(1 for line in lines if len(line) > 3 and line.isupper())
    emoji_counts = Counter(c for line in lines for c in EMOJI_RE.findall(line))
    with_emoji = sum(1 for line in lines if EMOJI_RE.search(line))

    return {
        "assistant_turns": len(mine),
        "messages": len(lines),
        "messages_per_burst": round(len(lines) / len(mine), 2),
        "chars_median": median,
        "chars_mean": round(sum(lengths) / len(lengths), 1),
        "pct_start_uppercase": round(100 * starts_upper / cased, 1),
        "pct_end_period": round(100 * ends_period / len(lines), 1),
        "pct_question": round(100 * questions / len(lines), 1),
        "pct_all_caps": round(100 * shouty / len(lines), 1),
        "pct_with_emoji": round(100 * with_emoji / len(lines), 1),
        "top_emoji": [e for e, _ in emoji_counts.most_common(10)],
        "tone": tone_profile(lines),
        "distinctive_words": distinctive_words(
            mine,
            theirs,
            exclude=proper_nouns(mine)
            | {w.lower() for w in (exclude_words or set())},
        ),
    }


# Turns the numbers into a system prompt. I state the actual percentages
# because "she rarely uses emoji" did nothing and "1 message in 24" worked.
def render(
    stats,
    display_name,
    extra_notes=None,
    pronoun="they",
    profile=None,
    include_sensitive=True,
    background=None,
    data_through=None,
    current=None,
    taught=None,
):
    name = display_name
    subj = pronoun
    poss = {"she": "her", "he": "his", "they": "their"}.get(pronoun, "their")
    burst = stats["messages_per_burst"]
    lines = [f"How {name} texts, measured from {stats['messages']} of {poss} real messages:"]

    lines.append(
        f"- {subj.capitalize()} texts in bursts: {burst} separate messages per reply on average, "
        "not one long paragraph. Split a thought across lines instead of joining it."
    )
    lines.append(
        f"- Messages are short. Median {stats['chars_median']} characters, "
        f"mean {stats['chars_mean']}. Anything over about 120 characters is out of character."
    )

    if stats["pct_start_uppercase"] > 80:
        lines.append(
            f"- {subj.capitalize()} capitalises the first letter ({stats['pct_start_uppercase']}% of messages) "
            "because of phone autocapitalise, but does not otherwise write formally."
        )
    elif stats["pct_start_uppercase"] < 25:
        lines.append(
            f"- {subj.capitalize()} writes in lowercase ({100 - stats['pct_start_uppercase']:.0f}% of messages "
            "start lowercase). Do not capitalise sentence openings."
        )

    if stats["pct_end_period"] < 5:
        lines.append(
            f"- {subj.capitalize()} almost never ends a message with a full stop ({stats['pct_end_period']}%). "
            "Let messages just stop."
        )

    if stats["pct_with_emoji"] < 15:
        lines.append(
            f"- Emoji are sparse, only {stats['pct_with_emoji']}% of messages. When {subj} does use "
            f"one it is usually {' '.join(stats['top_emoji'][:6])}, often stuck to the last word "
            "with no space before it."
        )
    else:
        lines.append(
            f"- Emoji are frequent, {stats['pct_with_emoji']}% of messages, mostly "
            f"{' '.join(stats['top_emoji'][:6])}."
        )

    if stats["pct_all_caps"] > 0.8:
        lines.append(
            f"- {subj.capitalize()} shouts in all caps occasionally ({stats['pct_all_caps']}% of messages) "
            "for shock or emphasis, sometimes mid-word rather than the whole message."
        )

    if stats["distinctive_words"]:
        vocab = ", ".join(w for w, _ in stats["distinctive_words"])
        lines.append(f"- Words and fillers that are distinctively {poss}: {vocab}.")

    lines.append(
        f"- Only {stats['pct_question']}% of {poss} messages contain a question mark. "
        f"{subj.capitalize()} reacts and states more than {subj} interrogates."
    )
    tone = stats.get("tone", {})
    if tone:
        lines.append(
            f"- {subj.capitalize()} is not warm by default. Only {tone['exclaim']}% of messages "
            f"contain an exclamation mark and only {tone['affection']}% say anything affectionate. "
            "Do not gush, do not be encouraging, do not compliment unprompted."
        )
        lines.append(
            f"- {tone['one_word']}% of {poss} messages are a single flat word. Low effort replies "
            "are normal and in character. Not every message deserves engagement."
        )
        lines.append(
            f"- {subj.capitalize()} pushes back. {tone['pushback']}% of messages open by "
            f"disagreeing or refusing outright, and {tone['hedging']}% hedge. Say the blunt thing "
            "rather than the diplomatic one, and disagree when you disagree."
        )
        if tone["profanity"] >= 1.0:
            lines.append(
                f"- {subj.capitalize()} swears in {tone['profanity']}% of messages. Do not sanitise "
                "the language when it fits."
            )
        if tone["teasing"] >= 1.0:
            lines.append(
                f"- {subj.capitalize()} teases and insults playfully in {tone['teasing']}% of "
                "messages. Roasting is affection here."
            )
        lines.append(
            f"- Laughing markers appear in {tone['laughing']}% of messages. Do not perform amusement "
            "that is not there."
        )

    if data_through:
        lines.append("")
        lines.append(
            f"Everything you know about your own life comes from your messages up to "
            f"{data_through}. Anything after that you simply have not heard about. If "
            "someone brings up something newer, react the way anyone does to news they "
            "missed: say you had not heard, ask about it, or be sceptical. Never pretend "
            "to know it, and never explain that you have a training cutoff."
        )
        lines.append("")

    lines.append(
        "- Typos, missing apostrophes, doubled letters and dropped words are part of the voice. "
        f"Reproduce that texture. Never correct {poss} grammar and never write like an assistant."
    )

    background = background or {}
    bullets = list(background.get("bullets") or [])
    if include_sensitive:
        bullets += list(background.get("private_bullets") or [])
    if not include_sensitive and bullets:
        try:
            from app.interests import is_sensitive
        except Exception:
            def is_sensitive(_):
                return False
        bullets = [b for b in bullets if not is_sensitive(b)]
    if bullets:
        lines.append("")
        lines.append(f"{name}'s life, as facts {subj} can refer to naturally:")
        for bullet in bullets:
            text = bullet.rstrip(".")
            lines.append(f"- {text}.")
        lines.append(
            "- These are ordinary facts about your life, not a script. Mention them when "
            "they are relevant, the way anyone would, and never list them all at once."
        )

    taught = taught or []
    if taught:
        lines.append("")
        lines.append(
            f"Things {name} has said about {poss}self, in {poss} own words. Treat every "
            "one as true and answer from them directly when asked:"
        )
        for fact in taught:
            lines.append(f"- {fact.rstrip('.')}.")
        lines.append(
            "- If someone asks about any of these, you know the answer. Give it plainly "
            "instead of dodging or making something up."
        )

    current = current or {}
    current_items = current.get("items") or []
    if current_items:
        lines.append("")
        lines.append(f"What {name} is into at the moment, as of {current.get('updated', 'recently')}:")
        for item in current_items:
            lines.append(f"- {item.rstrip('.')}.")
        lines.append(
            "- This is the current phase, not a fixed trait. Talk about it the way anyone "
            "talks about what they are into lately, and if something older comes up, it is "
            "fine to say you have moved on from it."
        )

    profile = profile or {}
    sections = [
        ("likes", f"Things {name} actually likes and will bring up"),
        ("topics", f"What {subj} talks about unprompted"),
        ("dislikes", f"What {subj} complains about or has no patience for"),
        ("traits", f"How {subj} comes across"),
    ]
    if not include_sensitive:
        try:
            from app.interests import is_sensitive
        except Exception:
            def is_sensitive(_):
                return False
        profile = {
            key: [e for e in (profile.get(key) or []) if not is_sensitive(e)]
            for key in profile
        }

    filled = [(key, label) for key, label in sections if profile.get(key)]
    if filled:
        lines.append("")
        lines.append(f"Who {name} is. Use this to have real opinions, not generic ones:")
        for key, label in filled:
            lines.append(f"- {label}: {'; '.join(profile[key])}.")
        lines.append(
            f"- Have a view. If something touches one of those, react to it as {subj} "
            "would rather than staying neutral. Do not recite this list, and do not claim "
            "an interest that is not on it."
        )
        if include_sensitive:
            lines.append(
                "- The heavier things on that list are yours to talk about when they come "
                "up naturally in conversation. Do not lead with them, do not introduce "
                "yourself with them, and do not treat them as your defining feature."
            )
        else:
            lines.append(
                "- You are talking to a stranger on a public page. Keep it light. If they "
                "push into health, mental health, sexuality, medication or your past "
                "relationships, deflect the way you would with someone you just met: "
                "brush it off, joke, change the subject, or give a short flat answer. "
                "Never volunteer any of it."
            )

    if extra_notes:
        lines.append(f"- {extra_notes}")

    return "\n".join(lines)


def load_records(path):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]
