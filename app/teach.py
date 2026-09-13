"""Adds facts to a persona from the command line or a plain text file.

Each persona can have a config/personas/<name>.facts.txt next to its JSON.
One fact per line, written the way you would say it. Lines starting with #
are ignored. Everything in that file goes straight into the style card.

    python -m app.teach chester "my favourite zzz character is Jane Doe"
    python -m app.teach chester --file more_facts.txt
    python -m app.teach chester --list
"""
import argparse
import subprocess
import sys

from ingest.personas import PERSONA_DIR, ROOT, list_personas


def facts_path(persona):
    return PERSONA_DIR / f"{persona}.facts.txt"


def load_facts(persona):
    path = facts_path(persona)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def save_facts(persona, facts):
    path = facts_path(persona)
    header = (
        "# One fact per line, written the way you would say it out loud.\n"
        "# Lines starting with # are ignored. Everything else goes into the persona.\n"
        "# Rebuild after editing:  python -m app.teach <name> --sync\n\n"
    )
    path.write_text(header + "\n".join(facts) + "\n", encoding="utf-8")


def sync(persona):
    for step in (["app.prompt", "--persona", persona, "--rebuild"], ["app.env_sync"]):
        result = subprocess.run([sys.executable, "-m"] + step, cwd=ROOT, capture_output=True)
        if result.returncode != 0:
            raise SystemExit(f"{step[0]} failed:\n{result.stderr.decode(errors='replace')[-600:]}")


def main():
    parser = argparse.ArgumentParser(description="Teach a persona facts about themselves.")
    parser.add_argument("persona")
    parser.add_argument("facts", nargs="*", help="facts to add, each in quotes")
    parser.add_argument("--file", help="add every non-comment line from this file")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--remove", type=int, action="append", default=[], help="remove by number")
    parser.add_argument("--sync", action="store_true", help="rebuild and refresh env without adding")
    parser.add_argument("--no-sync", action="store_true")
    args = parser.parse_args()

    if args.persona not in list_personas():
        raise SystemExit(f"no persona {args.persona!r}. Available: {list_personas()}")

    facts = load_facts(args.persona)

    if args.list:
        if not facts:
            print(f"{args.persona} has no taught facts yet. Add one with:")
            print(f'  python -m app.teach {args.persona} "my favourite colour is blue"')
            return
        print(f"{args.persona} knows {len(facts)} taught fact(s):")
        for index, fact in enumerate(facts, 1):
            print(f"  {index:3}. {fact}")
        return

    changed = False
    for number in sorted(args.remove, reverse=True):
        if 1 <= number <= len(facts):
            print(f"  removed: {facts.pop(number - 1)}")
            changed = True

    incoming = list(args.facts)
    if args.file:
        for line in open(args.file, encoding="utf-8").read().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                incoming.append(line)

    for fact in incoming:
        fact = fact.strip().rstrip(".")
        if fact and fact.lower() not in {f.lower() for f in facts}:
            facts.append(fact)
            print(f"  added: {fact}")
            changed = True

    if changed:
        save_facts(args.persona, facts)
    elif not args.sync:
        print("nothing to add. Pass facts in quotes, --file, --remove N, or --sync.")
        return

    if args.no_sync:
        return

    sync(args.persona)
    print("")
    print(f"{args.persona} now knows {len(facts)} taught fact(s). Prompt rebuilt, env refreshed.")
    print("Push it live with:")
    print("  python -m app.cf_deploy --personas")


if __name__ == "__main__":
    main()
