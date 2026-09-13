// TOTP for private mode. Works with Google Authenticator or any RFC 6238 app.
import { createHmac, randomBytes, timingSafeEqual } from 'node:crypto';
import { env } from '$env/dynamic/private';

const STEP_SECONDS = 30;
const DIGITS = 6;
const DRIFT_STEPS = 1;
const SESSION_MINUTES = 60;
const BASE32 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';

export type Grant = { id: string; secret: string; expires?: number };

let cache: Grant[] | null = null;

// Grants come from an env var as base64 JSON. One secret per person, so I
// can revoke someone without regenerating everyone else's key.
function parseGrants(): Grant[] {
	if (cache) return cache;
	const out: Grant[] = [];

	const raw = (env.ECHO_TOTP_GRANTS ?? '').trim();
	if (raw) {
		try {
			const decoded = raw.startsWith('[')
				? raw
				: Buffer.from(raw, 'base64').toString('utf-8');
			const parsed = JSON.parse(decoded);
			if (Array.isArray(parsed)) {
				for (const entry of parsed) {
					const id = String(entry?.id ?? '').trim();
					const secret = String(entry?.secret ?? '').replace(/[^A-Za-z2-7]/g, '');
					if (!id || secret.length < 16) continue;
					const expires = Number(entry?.expires);
					out.push({ id, secret, expires: Number.isFinite(expires) ? expires : undefined });
				}
			}
		} catch (error) {
			console.error('ECHO_TOTP_GRANTS could not be parsed', error);
		}
	}

	cache = out;
	return out;
}

function activeGrants(): Grant[] {
	const now = Date.now();
	return parseGrants().filter((grant) => !grant.expires || grant.expires > now);
}

function decodeBase32(input: string): Buffer {
	const clean = input.toUpperCase().replace(/[^A-Z2-7]/g, '');
	let bits = 0;
	let value = 0;
	const out: number[] = [];
	for (const char of clean) {
		const index = BASE32.indexOf(char);
		if (index === -1) continue;
		value = (value << 5) | index;
		bits += 5;
		if (bits >= 8) {
			out.push((value >>> (bits - 8)) & 0xff);
			bits -= 8;
		}
	}
	return Buffer.from(out);
}

// RFC 6238. HMAC-SHA1 over the 30 second counter, dynamic truncation, six
// digits. I wrote it with node's crypto rather than pulling in a library.
function codeFor(secret: Buffer, counter: number): string {
	const buffer = Buffer.alloc(8);
	buffer.writeUInt32BE(Math.floor(counter / 0x100000000), 0);
	buffer.writeUInt32BE(counter >>> 0, 4);
	const digest = createHmac('sha1', secret).update(buffer).digest();
	const offset = digest[digest.length - 1]! & 0x0f;
	const binary =
		((digest[offset]! & 0x7f) << 24) |
		((digest[offset + 1]! & 0xff) << 16) |
		((digest[offset + 2]! & 0xff) << 8) |
		(digest[offset + 3]! & 0xff);
	return String(binary % 10 ** DIGITS).padStart(DIGITS, '0');
}

function equal(a: string, b: string): boolean {
	const x = Buffer.from(a);
	const y = Buffer.from(b);
	return x.length === y.length && timingSafeEqual(x, y);
}

export function totpConfigured(): boolean {
	return activeGrants().length > 0;
}

export function matchGrant(supplied: string): Grant | null {
	const digits = supplied.replace(/\D/g, '');
	if (digits.length !== DIGITS) return null;
	const counter = Math.floor(Date.now() / 1000 / STEP_SECONDS);
	for (const grant of activeGrants()) {
		const secret = decodeBase32(grant.secret);
		if (!secret.length) continue;
		for (let drift = -DRIFT_STEPS; drift <= DRIFT_STEPS; drift += 1) {
			if (equal(codeFor(secret, counter + drift), digits)) return grant;
		}
	}
	return null;
}

function sessionKey(grant: Grant): Buffer {
	return createHmac('sha256', grant.secret).update('echo-persona-session-v2').digest();
}

// Sessions are signed with the grant's own secret. That way revoking the grant
// invalidates its sessions immediately instead of waiting for the hour to run
// out.
export function issueSession(grant: Grant): { token: string; expiresAt: number } {
	const cap = grant.expires ? Math.min(grant.expires, Date.now() + SESSION_MINUTES * 60_000) : Date.now() + SESSION_MINUTES * 60_000;
	const nonce = randomBytes(8).toString('hex');
	const payload = `${cap}.${encodeURIComponent(grant.id)}.${nonce}`;
	const signature = createHmac('sha256', sessionKey(grant)).update(payload).digest('hex').slice(0, 32);
	return { token: `${payload}.${signature}`, expiresAt: cap };
}

export function sessionGrant(token: string | null): Grant | null {
	if (!token) return null;
	const parts = token.split('.');
	if (parts.length !== 4) return null;
	const [expiryRaw, idRaw, nonce, signature] = parts as [string, string, string, string];
	const expiry = Number(expiryRaw);
	if (!Number.isFinite(expiry) || expiry < Date.now()) return null;
	const id = decodeURIComponent(idRaw);
	const grant = activeGrants().find((candidate) => candidate.id === id);
	if (!grant) return null;
	const expected = createHmac('sha256', sessionKey(grant))
		.update(`${expiryRaw}.${idRaw}.${nonce}`)
		.digest('hex')
		.slice(0, 32);
	return equal(expected, signature) ? grant : null;
}

export function isUnlocked(request: Request): boolean {
	return sessionGrant(request.headers.get('x-echo-unlock')) !== null;
}
