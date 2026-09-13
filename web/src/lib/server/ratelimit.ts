// Per visitor bursts and a daily cap, plus admin overrides.
//
// Counting happens inside a Durable Object, one per visitor IP and one named
// "daily" for the whole site. Cloudflare sends every request for a name to the
// same object, so the counts are exact. On Vercel this was in memory per
// instance, and Cloudflare's own rate limit binding turned out to be
// approximate, so this is the third attempt and the first correct one.
import { env } from '$env/dynamic/private';

const OVERRIDES_KEY = 'overrides';

type Overrides = { dailyCap?: number | null };
type LimiterReply = { ok?: boolean; count: number; retryAfter?: number; resetAt?: number };

function today(): string {
	return new Date().toISOString().slice(0, 10);
}

function setting(name: string, fallback: number): number {
	const raw = Number((env as Record<string, string | undefined>)[name] ?? fallback);
	return Number.isFinite(raw) && raw > 0 ? raw : fallback;
}

async function readOverrides(kv: KVNamespace | undefined): Promise<Overrides> {
	if (!kv) return {};
	try {
		return (await kv.get<Overrides>(OVERRIDES_KEY, 'json')) ?? {};
	} catch {
		return {};
	}
}

async function dailyCap(kv: KVNamespace | undefined): Promise<number> {
	const overrides = await readOverrides(kv);
	if (typeof overrides.dailyCap === 'number') return overrides.dailyCap;
	return setting('ECHO_DAILY_MESSAGE_CAP', 80);
}

// Talks to one named object. "hit" increments and refuses past the limit,
// "read" just reports, "reset" clears.
async function counter(
	platform: App.Platform | undefined,
	name: string,
	action: 'hit' | 'read' | 'reset',
	limit = 0,
	periodSeconds = 60
): Promise<LimiterReply | null> {
	const ns = platform?.env?.LIMITER;
	if (!ns) return null;
	try {
		const stub = ns.get(ns.idFromName(name));
		const url = `https://limiter/?action=${action}&limit=${limit}&period=${periodSeconds}`;
		const response = await stub.fetch(url);
		return (await response.json()) as LimiterReply;
	} catch (error) {
		console.error('limiter unavailable', error);
		return null;
	}
}

// The daily object resets itself every 24 hours from its first hit. I also
// key it by date so a stale object from yesterday can never carry over.
function dailyName(): string {
	return `daily:${today()}`;
}

export function clientKey(request: Request, address: string | null): string {
	const cf = request.headers.get('cf-connecting-ip');
	if (cf) return cf;
	const forwarded = request.headers.get('x-forwarded-for');
	if (forwarded) return forwarded.split(',')[0]!.trim();
	return address ?? 'unknown';
}

export type LimitResult =
	| { ok: true }
	| { ok: false; status: number; message: string; retryAfter?: number };

export async function checkLimits(
	platform: App.Platform | undefined,
	key: string,
	kind: 'chat' | 'unlock' = 'chat'
): Promise<LimitResult> {
	const kv = platform?.env?.PERSONAS;
	const burstLimit = kind === 'unlock' ? setting('ECHO_UNLOCK_BURST', 5) : setting('ECHO_IP_BURST', 6);

	const burst = await counter(platform, `ip:${kind}:${key}`, 'hit', burstLimit, 60);
	if (burst && burst.ok === false) {
		return {
			ok: false,
			status: 429,
			message: 'Slow down a second, you are sending messages very fast.',
			retryAfter: burst.retryAfter ?? 60
		};
	}

	if (kind === 'chat') {
		const daily = await counter(platform, dailyName(), 'hit', await dailyCap(kv), 60 * 60 * 24);
		if (daily && daily.ok === false) {
			return {
				ok: false,
				status: 429,
				message: 'This demo has hit its daily message budget. Try again tomorrow.'
			};
		}
	}

	return { ok: true };
}

async function usedToday(platform: App.Platform | undefined): Promise<number> {
	const reply = await counter(platform, dailyName(), 'read');
	return reply?.count ?? 0;
}

export async function budgetRemaining(platform: App.Platform | undefined): Promise<number> {
	const kv = platform?.env?.PERSONAS;
	return Math.max(0, (await dailyCap(kv)) - (await usedToday(platform)));
}

function timingSafeEqual(a: string, b: string): boolean {
	if (a.length !== b.length) return false;
	let diff = 0;
	for (let i = 0; i < a.length; i += 1) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
	return diff === 0;
}

// Constant time compare so the token cannot be guessed a byte at a time.
export function isAdmin(request: Request): boolean {
	const expected = env.ECHO_ADMIN_TOKEN ?? '';
	if (expected.length < 16) return false;
	const supplied = request.headers.get('x-echo-admin') ?? '';
	if (!supplied) return false;
	return timingSafeEqual(supplied, expected);
}

export type Usage = {
	date: string;
	used: number;
	dailyCap: number;
	remaining: number;
	ipBurst: number;
	overridden: { dailyCap: boolean; ipBurst: boolean };
	activeIps: number;
};

export async function usage(platform: App.Platform | undefined): Promise<Usage> {
	const kv = platform?.env?.PERSONAS;
	const used = await usedToday(platform);
	const cap = await dailyCap(kv);
	const overrides = await readOverrides(kv);
	return {
		date: today(),
		used,
		dailyCap: cap,
		remaining: Math.max(0, cap - used),
		ipBurst: setting('ECHO_IP_BURST', 6),
		overridden: { dailyCap: typeof overrides.dailyCap === 'number', ipBurst: false },
		activeIps: 0
	};
}

export async function applyOverrides(
	platform: App.Platform | undefined,
	next: { dailyCap?: number | null; resetCounter?: boolean }
): Promise<Usage> {
	const kv = platform?.env?.PERSONAS;
	if (kv) {
		const overrides = await readOverrides(kv);
		if (next.dailyCap === null) delete overrides.dailyCap;
		else if (typeof next.dailyCap === 'number' && Number.isFinite(next.dailyCap)) {
			overrides.dailyCap = Math.max(0, Math.min(1_000_000, Math.floor(next.dailyCap)));
		}
		await kv.put(OVERRIDES_KEY, JSON.stringify(overrides));
	}
	if (next.resetCounter) await counter(platform, dailyName(), 'reset');
	return usage(platform);
}
