"""Updates what a persona is into at the moment.

I rotate games every few weeks and did not want to edit JSON by hand each time.
"""
import argparse
import datetime
import json
import subprocess
import sys

from ingest.personas import PERSONA_DIR, ROOT, list_personas


def load(persona):
    path = PERSONA_DIR / f"{persona}.json"
    if not path.exists():
        raise SystemExit(f"no persona {persona!r}. Available: {list_personas()}")
    return path, json.loads(path.read_text(encoding="utf-8"))


def save(path, cfg):
    path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def show(cfg):
    current = cfg.get("current") or {}
    items = current.get("items") or []
    if not items:
        print("  (nothing set)")
        return
    print(f"  as of {current.get('updated', 'unknown')}:")
    for index, item in enumerate(items, 1):
        print(f"    {index}. {item}")


def main():
    parser = argparse.ArgumentParser(
        description="Update what a persona is into right now. For things that change often."
    )
    parser.add_argument("persona")
    parser.add_argument("items", nargs="*", help="replace the current list with these")
    parser.add_argument("--add", action="append", default=[], help="append one item")
    parser.add_argument("--drop", type=int, action="append", default=[], help="remove by number")
    parser.add_argument("--clear", action="store_true")
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--no-sync", action="store_true", help="skip rebuild and env sync")
    args = parser.parse_args()

    path, cfg = load(args.persona)
    current = cfg.setdefault("current", {"updated": "", "items": []})
    items = list(current.get("items") or [])

    if args.show:
        print(f"{args.persona} is currently into:")
        show(cfg)
        return

    changed = False
    if args.clear:
        items = []
        changed = True
    if args.items:
        items = list(args.items)
        changed = True
    for entry in args.add:
        items.append(entry)
        changed = True
    for number in sorted(args.drop, reverse=True):
        if 1 <= number <= len(items):
            items.pop(number - 1)
            changed = True

    if not changed:
        print(f"{args.persona} is currently into:")
        show(cfg)
        print("")
        print("Set it with:")
        print(f'  python -m app.now {args.persona} "reading a lot of sci-fi lately"')
        return

    current["items"] = items
    current["updated"] = datetime.date.today().isoformat()
    save(path, cfg)

    print(f"{args.persona} updated:")
    show(cfg)

    if args.no_sync:
        return

    print("")
    for step in (
        ["app.prompt", "--persona", args.persona, "--rebuild"],
        ["app.env_sync"],
    ):
        result = subprocess.run([sys.executable, "-m"] + step, cwd=ROOT, capture_output=True)
        if result.returncode != 0:
            raise SystemExit(f"{step[0]} failed:\n{result.stderr.decode(errors='replace')[-800:]}")
    print("rebuilt the style card and refreshed the env files.")
    print("")
    print("Push it live with:")
    print("  python -m app.cf_deploy --personas")


if __name__ == "__main__":
    main()
