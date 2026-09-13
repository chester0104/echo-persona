"""Deploys the site to Cloudflare Workers.

    python -m app.cf_deploy                 full: KV, secrets, build, deploy
    python -m app.cf_deploy --personas      just push the personas to KV
    python -m app.cf_deploy --secrets       just push the secrets

Pushing personas does not need a redeploy. The Worker reads KV on each
request, so new facts are live within a minute of the put.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys

from ingest.personas import ROOT

WEB = ROOT / "web"
WRANGLER_CFG = WEB / "wrangler.jsonc"
DEV_VARS = WEB / ".dev.vars"
KV_FILE = WEB / ".kv" / "personas.json"
PLACEHOLDER = "REPLACE_AFTER_wrangler_kv_namespace_create"


def npx():
    found = shutil.which("npx.cmd") or shutil.which("npx")
    if not found:
        raise SystemExit("npx not found. Install Node 20+ first.")
    return found


def run(args, capture=False, stdin=None):
    result = subprocess.run(
        [npx(), "--yes", "wrangler"] + args,
        cwd=WEB,
        capture_output=capture,
        text=True,
        encoding="utf-8",
        errors="replace",
        input=stdin,
    )
    if result.returncode != 0:
        if capture:
            raise SystemExit(f"wrangler {' '.join(args)} failed:\n{result.stderr[-800:]}")
        raise SystemExit(f"wrangler {' '.join(args)} failed")
    return result


def logged_in():
    result = subprocess.run(
        [npx(), "--yes", "wrangler", "whoami"],
        cwd=WEB, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return "not authenticated" not in (result.stdout + result.stderr).lower()


def ensure_namespace():
    cfg = WRANGLER_CFG.read_text(encoding="utf-8")
    if PLACEHOLDER not in cfg:
        return
    print(">> creating the PERSONAS KV namespace")
    result = run(["kv", "namespace", "create", "PERSONAS"], capture=True)
    match = re.search(r'"?id"?\s*[:=]\s*"([0-9a-f]{32})"', result.stdout + result.stderr)
    if not match:
        raise SystemExit(f"could not find the namespace id in:\n{result.stdout[-600:]}")
    WRANGLER_CFG.write_text(cfg.replace(PLACEHOLDER, match.group(1)), encoding="utf-8")
    print(f"   namespace id {match.group(1)} written to wrangler.jsonc")


def push_personas():
    if not KV_FILE.exists():
        raise SystemExit(f"{KV_FILE} missing. Run: python -m app.env_sync")
    count = len(json.loads(KV_FILE.read_text(encoding="utf-8")))
    print(f">> pushing {count} persona(s) to KV")
    run(["kv", "key", "put", "personas", "--path", str(KV_FILE), "--binding", "PERSONAS", "--remote"])


def push_secrets():
    if not DEV_VARS.exists():
        raise SystemExit(f"{DEV_VARS} missing. Run: python -m app.env_sync")
    for line in DEV_VARS.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"')
        if not value:
            continue
        print(f">> secret {key}")
        run(["secret", "put", key.strip()], capture=True, stdin=value)


def deploy():
    print(">> building")
    result = subprocess.run([npx(), "vite", "build"], cwd=WEB)
    if result.returncode != 0:
        raise SystemExit("build failed")
    print(">> deploying")
    result = run(["deploy"], capture=True)
    urls = re.findall(r"https://[^\s]+workers\.dev", result.stdout)
    print("")
    print("deployed" + (f": {urls[-1]}" if urls else ""))


def main():
    parser = argparse.ArgumentParser(description="Deploy echo-persona to Cloudflare Workers.")
    parser.add_argument("--personas", action="store_true", help="only push personas to KV")
    parser.add_argument("--secrets", action="store_true", help="only push secrets")
    args = parser.parse_args()

    if not logged_in():
        raise SystemExit("not logged in. Run this first, in web/:\n  npx wrangler login")

    if args.personas:
        push_personas()
        return
    if args.secrets:
        push_secrets()
        return

    ensure_namespace()
    push_personas()
    push_secrets()
    deploy()


if __name__ == "__main__":
    main()
