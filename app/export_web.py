"""Packages the personas for the website as a base64 env var.
"""
import argparse
import base64
import json

from app import style
from app.elevenlabs import get_voice_id
from app.prompt import build
from ingest.personas import (
    ROOT,
    list_personas,
    load_persona,
    load_runtime,
    style_path,
)

PALETTE = ["#c084fc", "#22d3ee", "#f472b6", "#34d399", "#fbbf24"]

# The tagline is shown publicly next to their name, so it fails the export
# if anything sensitive sneaks in.
CAPTION_BLOCKLIST = [
    "anxiet", "anxious", "depress", "medicat", "therapy", "mental health",
    "sexualit", "coming out", "gay", "queer", "lesbian", "bisexual", "trans",
    "self-esteem", "self esteem", "insecur", "suicid", "ex-", "her ex", "his ex",
    "weed", "drug", "trauma", "abuse", "diagnos",
]


def check_caption(persona, tagline):
    lowered = tagline.lower()
    hits = [w for w in CAPTION_BLOCKLIST if w in lowered]
    if hits:
        raise SystemExit(
            f"caption for {persona!r} mentions sensitive topics {hits}; "
            "captions are shown publicly on the site, rewrite it in TAGLINES"
        )
    return tagline
DEFAULT_TAGLINE = "cloned texting style"


# The site gets the style card only, never the 300 real exchanges. I measured
# it: 33% style gap versus 18.5% with examples, at 1/20th the tokens and with
# no message text on the server.
def card_for(persona_cfg, runtime_cfg, include_sensitive=True):
    full, stats, _, _ = build(persona_cfg, runtime_cfg, include_sensitive)
    head = full.split("=== EXAMPLES ===")[0]
    tail = full.split("=== END EXAMPLES ===")[1]
    head = head.replace(
        f"Below are {runtime_cfg['prompt']['example_exchanges']} real exchanges",
        "No transcript is included",
    )
    return head.rstrip() + "\n" + tail.lstrip(), stats


def build_packs(names=None, verbose=False):
    runtime_cfg = load_runtime()
    names = names or list_personas()

    packs = []
    for name in names:
        persona_cfg = load_persona(name)
        card, stats = card_for(persona_cfg, runtime_cfg, include_sensitive=False)
        card_private, _ = card_for(persona_cfg, runtime_cfg, include_sensitive=True)
        packs.append(
            {
                "id": name,
                "name": persona_cfg.get("display_name", name),
                "tagline": check_caption(name, persona_cfg.get("tagline") or DEFAULT_TAGLINE),
                "quote": check_caption(name, persona_cfg.get("quote", "")),
                "accent": persona_cfg.get("accent") or PALETTE[len(packs) % len(PALETTE)],
                "styleCard": card,
                "styleCardPrivate": card_private,
                "voiceId": get_voice_id(name) or "",
                "timeline": (persona_cfg.get("background") or {}).get("timeline", []),
                "pronoun": persona_cfg.get("pronoun", "they"),
                "dataThrough": persona_cfg.get("data_through", ""),
                "rhythm": {
                    "burst": stats["messages_per_burst"],
                    "medianChars": stats["chars_median"],
                    "emojiPct": stats["pct_with_emoji"],
                    "capsPct": stats["pct_start_uppercase"],
                },
            }
        )
        leaked = [w for w, _ in stats["distinctive_words"]]
        print(
            f"{name}: public {len(card):,} chars, private {len(card_private):,} chars, "
            f"voice {'yes' if packs[-1]['voiceId'] else 'no'}"
        )
        print(f"  vocabulary shipped: {', '.join(leaked)}")

    return packs


# The plain list, for KV on Cloudflare. No base64 needed there.
def build_pack_list(names=None):
    return build_packs(names, verbose=False)


# Base64 of the list, for the old Vercel env var path. Kept so env_sync still
# writes VERCEL_ENV.txt, but Cloudflare does not use it.
def build_packs_b64(names=None, verbose=False):
    packs = build_packs(names, verbose)
    blob = base64.b64encode(json.dumps(packs, ensure_ascii=False).encode("utf-8")).decode("ascii")
    if verbose:
        print(f"\nECHO_PERSONAS_B64 is {len(blob):,} characters")
    return blob


def main():
    parser = argparse.ArgumentParser(
        description="Export style cards for the web app. Never includes message text."
    )
    parser.add_argument("--personas", nargs="*")
    parser.add_argument("--print-only", action="store_true")
    args = parser.parse_args()

    blob = build_packs(args.personas, verbose=not args.print_only)
    if args.print_only:
        print(blob)
        return

    print("")
    print("Style cards rebuilt. Write the env files with:")
    print("  python -m app.env_sync")


if __name__ == "__main__":
    main()
