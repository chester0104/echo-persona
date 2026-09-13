"""Prints the schema and sender names from an export.

I run this first on anything new. Instagram stores display names as styled
unicode, so copying the exact string out of here beats typing it.
"""
import argparse
from collections import Counter
from pathlib import Path

from ingest.adapters import available, get_adapter
from ingest.personas import ROOT, load_persona


def main():
    parser = argparse.ArgumentParser(
        description="Inspect a chat export before writing a persona config."
    )
    parser.add_argument("--persona")
    parser.add_argument("--path")
    parser.add_argument("--format", choices=available())
    parser.add_argument("--samples", type=int, default=10)
    args = parser.parse_args()

    if args.path:
        root = Path(args.path)
        fmt = args.format or "instagram"
    else:
        cfg = load_persona(args.persona)
        root = ROOT / cfg["chat"]["path"]
        fmt = args.format or cfg["chat"]["format"]

    adapter = get_adapter(fmt)
    records, sources = adapter.load(root)

    kinds = Counter()
    senders = Counter()
    fields = Counter()
    usable = Counter()
    for record in records:
        kind = adapter.classify(record)
        kinds[kind] += 1
        senders[record["sender"]] += 1
        fields.update(record.get("raw_fields", []))
        if kind == "text":
            usable[record["sender"]] += 1

    rels = [str(p.relative_to(ROOT)) for p in sources]
    print("format:  " + fmt)
    print("root:    " + str(root))
    print("files:   " + ", ".join(rels))
    print("records: " + str(len(records)))
    print("")
    print("senders (all records / usable text):")
    for name, count in senders.most_common():
        print("  " + repr(name) + "   " + str(count) + " / " + str(usable[name]))
    print("")
    print("record kinds: " + str(dict(kinds)))
    print("raw fields:   " + str(dict(fields)))
    print("")
    print("sample of " + str(args.samples) + " usable messages:")
    shown = 0
    for record in records:
        if adapter.classify(record) != "text":
            continue
        print("  [" + record["sender"] + "] " + repr(record["text"]))
        shown += 1
        if shown >= args.samples:
            break
    print("")
    print("Copy the sender strings above verbatim into a persona config:")
    print("  chat.clone_sender  = the person being cloned")
    print("  chat.other_sender  = the other party")


if __name__ == "__main__":
    main()
