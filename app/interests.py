"""Works out what a persona likes, dislikes, and talks about.

The result goes into the persona config as plain JSON so I can read it and
fix anything wrong by hand.
"""
import argparse
import json
import random
import re

from app import style
from app.client import ChatClient
from app.redact import Redactor
from ingest.personas import PERSONA_DIR, load_persona, load_runtime, turns_path

EXTRACTION_PROMPT = """You are reading real text messages sent by one person, called {name}.

Work out what {name} is actually like: what {subject} enjoys, what {subject} has opinions
about, what {subject} complains about, and how {subject} comes across.

Return ONLY valid JSON, no commentary and no code fence, in exactly this shape:

{{
  "likes": ["specific things they enjoy, named concretely"],
  "dislikes": ["specific things they complain about or find annoying"],
  "traits": ["short phrases describing how they come across to others"],
  "topics": ["subjects they bring up unprompted"]
}}

Rules:
- Be specific. "the office, especially the later seasons" beats "tv shows". "building side projects"
  beats "technology".
- Only include something if it shows up more than once, or is clearly strongly felt.
- 4 to 8 entries per list. Fewer if the evidence is thin.
- Every entry under 60 characters.

CRITICAL PRIVACY RULES. The output is published, so it must never contain:
- the name of ANY real person other than {name}, including friends, family, exes,
  classmates and usernames. Refer to them by relationship only, such as "her sister".
- schools, workplaces, employers, street names, cities, or countries they live in
- phone numbers, handles, emails, links, or ages
Names of fictional characters, bands, games, films and shows ARE allowed and wanted."""


# Health, sexuality, politics and similar get filtered out by default. The
# person can opt back in with --allow-sensitive, but I did not want it to be
# the default for something that ends up on a public site.
SENSITIVE_PATTERNS = [
    r"sexualit|coming out|closet|gay|lesbian|bisexual|queer|trans|orientation",
    r"depress|anxiet|anxious|mental health|medicat|therapy|therapist|suicid|self.harm|kms",
    r"eating disorder|body image|weight|self.esteem|self.critical|insecur",
    r"religio|church|muslim|jewish|christian|atheis|god",
    r"politic|vote|voting|republican|democrat|abortion|immigrat",
    r"race|racis|ethnic|nationality|disabilit|illness|diagnos|adhd|autis",
    r"abuse|trauma|assault|addiction|drinking|drugs|weed",
]


def is_sensitive(text):
    lowered = text.lower()
    return any(re.search(pattern, lowered) for pattern in SENSITIVE_PATTERNS)


def sample_messages(records, limit, seed):
    lines = []
    for record in records:
        for turn in record["messages"]:
            if turn["role"] != "assistant":
                continue
            for line in turn["content"].split("\n"):
                line = line.strip()
                if len(line) > 12:
                    lines.append(line)
    rng = random.Random(seed)
    rng.shuffle(lines)
    return lines[:limit]


def clean_entries(entries, redactor, limit=8, allow_sensitive=False, dropped=None):
    out = []
    for entry in entries or []:
        if not isinstance(entry, str):
            continue
        text = re.sub(r"\s+", " ", entry).strip().rstrip(".")
        if not text or len(text) > 60:
            continue
        if redactor and not redactor.is_clean(text):
            continue
        if not allow_sensitive and is_sensitive(text):
            if dropped is not None:
                dropped.append(text)
            continue
        if text.lower() in {e.lower() for e in out}:
            continue
        out.append(text)
        if len(out) >= limit:
            break
    return out


# One model call over a sample of their own messages. It is the only place in
# the pipeline where a model reads the data, and it runs once.
def extract(persona_cfg, runtime_cfg, sample_size, seed, allow_sensitive=False):
    persona = persona_cfg["persona"]
    name = persona_cfg.get("display_name", persona)
    pronoun = persona_cfg.get("pronoun", "they")
    subject = {"she": "she", "he": "he", "they": "they"}.get(pronoun, "they")

    records = style.load_records(turns_path(persona))
    lines = sample_messages(records, sample_size, seed)
    if not lines:
        raise SystemExit(f"no usable messages for {persona!r}")

    redactor = Redactor(persona_cfg)
    system = EXTRACTION_PROMPT.format(name=name, subject=subject)
    body = "\n".join(f"- {line}" for line in lines)

    client = ChatClient(runtime_cfg)
    client.max_output_tokens = 900
    client.temperature = 0.3
    raw = client.complete(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Messages sent by {name}:\n\n{body}"},
        ]
    )
    cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"model did not return valid json: {exc}\n{cleaned[:400]}")

    dropped = []
    profile = {
        key: clean_entries(
            parsed.get(key), redactor, allow_sensitive=allow_sensitive, dropped=dropped
        )
        for key in ("likes", "dislikes", "traits", "topics")
    }
    return profile, len(lines), dropped


def main():
    parser = argparse.ArgumentParser(
        description="Derive interests and personality from a persona's own messages."
    )
    parser.add_argument("--persona")
    parser.add_argument("--sample", type=int, default=500)
    parser.add_argument("--seed", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--allow-sensitive",
        action="store_true",
        help="keep health, sexuality, politics and similar topics (off by default)",
    )
    args = parser.parse_args()

    persona_cfg = load_persona(args.persona)
    runtime_cfg = load_runtime()
    profile, sampled, dropped = extract(
        persona_cfg, runtime_cfg, args.sample, args.seed, args.allow_sensitive
    )

    print(f"persona: {persona_cfg['persona']}  (from {sampled} sampled messages)")
    for key in ("likes", "dislikes", "traits", "topics"):
        print(f"\n{key}:")
        for entry in profile[key]:
            print(f"  - {entry}")

    if args.dry_run:
        print("\ndry run, nothing written")
        return

    path = PERSONA_DIR / f"{persona_cfg['persona']}.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["profile"] = profile
    path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote profile to {path.name}. Edit it by hand if anything is wrong.")


if __name__ == "__main__":
    main()
