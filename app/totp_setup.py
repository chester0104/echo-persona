"""Manages who can unlock private mode on the site.

Each person gets a setup key for their authenticator app.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import struct
import time
import urllib.parse

from ingest.personas import CONFIG_DIR, ROOT

GRANTS_PATH = CONFIG_DIR / "totp_grants.json"
STEP = 30
DIGITS = 6


def new_secret(length=20):
    return base64.b32encode(os.urandom(length)).decode("ascii").rstrip("=")


# Standard TOTP: HMAC-SHA1 of the 30 second counter, dynamic truncation, six
# digits. Same thing Google Authenticator computes.
def code_at(secret, counter):
    padded = secret + "=" * (-len(secret) % 8)
    key = base64.b32decode(padded, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**DIGITS).zfill(DIGITS)


def current_code(secret):
    return code_at(secret, int(time.time() // STEP))


def otpauth_uri(secret, label, issuer):
    label_q = urllib.parse.quote(f"{issuer}:{label}")
    params = urllib.parse.urlencode(
        {
            "secret": secret,
            "issuer": issuer,
            "algorithm": "SHA1",
            "digits": DIGITS,
            "period": STEP,
        }
    )
    return f"otpauth://totp/{label_q}?{params}"


def load_grants():
    if not GRANTS_PATH.exists():
        return []
    try:
        return json.loads(GRANTS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def write_env(key, value):
    targets = ((ROOT / "web" / ".env.local", True), (ROOT / "VERCEL_ENV.txt", False))
    for target, quote in targets:
        if not target.exists():
            continue
        kept = [
            line
            for line in target.read_text(encoding="utf-8").splitlines()
            if not line.startswith(key)
        ]
        kept.append(f'{key}="{value}"' if quote else f"{key}={value}")
        target.write_text("\n".join(kept) + "\n", encoding="utf-8")


# Every grant is its own secret. Revoking one person does not affect anyone
# else, and the site signs sessions with the grant secret so a revoked grant
# kills its live sessions immediately.
def save_grants(grants):
    GRANTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    GRANTS_PATH.write_text(json.dumps(grants, indent=2), encoding="utf-8")
    payload = [
        {k: v for k, v in grant.items() if k in ("id", "secret", "expires")}
        for grant in grants
    ]
    blob = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    write_env("ECHO_TOTP_GRANTS", blob)
    return blob


def describe(grant, now_ms):
    expires = grant.get("expires")
    if not expires:
        return "no expiry"
    if expires < now_ms:
        return "EXPIRED"
    return f"expires in {int((expires - now_ms) / 86400000)}d"


def main():
    parser = argparse.ArgumentParser(
        description="Manage who can unlock private mode on the site."
    )
    parser.add_argument("--issuer", default="echo-persona")
    parser.add_argument("--grant", metavar="NAME", help="create a grant for one person")
    parser.add_argument("--days", type=int, help="expire this grant after N days")
    parser.add_argument("--revoke", metavar="NAME", help="revoke a named grant")
    parser.add_argument("--list", action="store_true", help="list grants and codes")
    parser.add_argument("--code", metavar="NAME", help="show current code for one grant")
    parser.add_argument("--show", metavar="NAME", help="show the setup key to enrol a device")
    args = parser.parse_args()

    grants = load_grants()
    now_ms = time.time() * 1000

    if args.list:
        if not grants:
            print("no grants yet. Create one with:")
            print("  python -m app.totp_setup --grant friend")
            return
        print(f"  {'grant':18} {'status':16} code now")
        for grant in grants:
            status = describe(grant, now_ms)
            print(f"  {grant['id']:18} {status:16} {current_code(grant['secret'])}")
        return

    if args.show:
        match = next((g for g in grants if g["id"] == args.show), None)
        if not match:
            raise SystemExit(f"no grant named {args.show!r}. Use --list.")
        secret = match["secret"]
        print(f"setup key for {match['id']!r}")
        print("")
        print("  In Google Authenticator: + > Enter a setup key > Time based")
        print("")
        print(f"  account:   echo-persona ({match['id']})")
        print(f"  key:       {secret}")
        print(f"  uri:       {otpauth_uri(secret, match['id'], args.issuer)}")
        print("")
        print(f"  it should immediately show: {current_code(secret)}")
        print(f"  {describe(match, now_ms)}")
        print("")
        print("Treat this key like a password. Anyone holding it can unlock private mode.")
        return

    if args.code:
        match = next((g for g in grants if g["id"] == args.code), None)
        if not match:
            raise SystemExit(f"no grant named {args.code!r}. Use --list.")
        print(f"{match['id']}: {current_code(match['secret'])}  (rotates every {STEP}s)")
        return

    if args.revoke:
        kept = [g for g in grants if g["id"] != args.revoke]
        if len(kept) == len(grants):
            raise SystemExit(f"no grant named {args.revoke!r}. Use --list.")
        save_grants(kept)
        print(f"revoked {args.revoke!r}.")
        print("Their codes stop working, and any session they already held dies at once.")
        print("Copy ECHO_TOTP_GRANTS from VERCEL_ENV.txt into Vercel to apply in production.")
        return

    if args.grant:
        kept = [g for g in grants if g["id"] != args.grant]
        secret = new_secret()
        entry = {"id": args.grant, "secret": secret}
        if args.days:
            entry["expires"] = int((time.time() + args.days * 86400) * 1000)
        kept.append(entry)
        save_grants(kept)

        print(f"grant created for {args.grant!r}")
        print("")
        print("Send ONLY this person the setup key, over something private.")
        print("They add it in Google Authenticator as a time based 6 digit code.")
        print("")
        print(f"  setup key: {secret}")
        print(f"  uri:       {otpauth_uri(secret, args.grant, args.issuer)}")
        print(f"  code now:  {current_code(secret)}")
        if args.days:
            print(f"  expires:   in {args.days} days")
        print("")
        print("Then copy ECHO_TOTP_GRANTS from VERCEL_ENV.txt into Vercel and redeploy.")
        print(f"Revoke any time with: python -m app.totp_setup --revoke {args.grant}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
