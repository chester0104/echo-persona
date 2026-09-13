// Everything in src/lib/server is server only. SvelteKit refuses to bundle it
// into client code, which is what keeps the style cards off the browser.
import type { PersonaPack, PersonaSummary } from '$lib/types';

type TimelineItem = { event?: string; date?: string };

export type StoredPersona = PersonaPack & {
	builtIn: true;
	styleCardPrivate?: string;
	pronoun?: string;
	dataThrough?: string;
	timeline?: TimelineItem[];
};

const PALETTE = ['#c084fc', '#22d3ee', '#f472b6', '#34d399', '#fbbf24'];
const KV_KEY = 'personas';
const CACHE_MS = 60_000;

// One isolate can serve many requests, so I keep the parsed list for a
// minute. A KV read per request would be fine too, this just saves a round
// trip on busy moments.
let cache: { at: number; list: StoredPersona[] } | null = null;

function normalise(entry: Record<string, unknown>, index: number): StoredPersona | null {
	const id = String(entry.id ?? entry.persona ?? '').trim();
	const styleCard = String(entry.styleCard ?? entry.style_card ?? '').trim();
	const styleCardPrivate = String(entry.styleCardPrivate ?? '').trim();
	if (!id || !styleCard) return null;
	const rhythm = (entry.rhythm ?? {}) as Record<string, number>;
	return {
		schema: 'echo-persona/1',
		builtIn: true,
		id,
		name: String(entry.name ?? entry.display_name ?? id),
		tagline: String(entry.tagline ?? ''),
		quote: entry.quote ? String(entry.quote) : undefined,
		accent: String(entry.accent ?? PALETTE[index % PALETTE.length]),
		styleCard,
		styleCardPrivate: styleCardPrivate || undefined,
		voiceId: entry.voiceId ? String(entry.voiceId) : undefined,
		pronoun: String(entry.pronoun ?? 'they'),
		dataThrough: entry.dataThrough ? String(entry.dataThrough) : undefined,
		timeline: Array.isArray(entry.timeline) ? (entry.timeline as TimelineItem[]) : [],
		rhythm: {
			burst: Number(rhythm.burst ?? 0),
			medianChars: Number(rhythm.medianChars ?? 0),
			emojiPct: Number(rhythm.emojiPct ?? 0),
			capsPct: Number(rhythm.capsPct ?? 0)
		}
	};
}

// Reads the whole persona list from KV. The value is plain JSON, no base64,
// since KV does not have the size or character problems an env var has.
export async function loadPersonas(platform: App.Platform | undefined): Promise<StoredPersona[]> {
	if (cache && Date.now() - cache.at < CACHE_MS) return cache.list;
	const kv = platform?.env?.PERSONAS;
	if (!kv) {
		console.error('PERSONAS KV binding is missing. Check wrangler.jsonc.');
		return [];
	}
	let parsed: unknown = null;
	try {
		parsed = await kv.get(KV_KEY, 'json');
	} catch (error) {
		console.error('personas could not be read from KV', error);
		return [];
	}
	const list = Array.isArray(parsed) ? parsed : [];
	const out = list
		.map((entry, index) => normalise(entry as Record<string, unknown>, index))
		.filter((entry): entry is StoredPersona => entry !== null);
	cache = { at: Date.now(), list: out };
	return out;
}

export async function getPersona(platform: App.Platform | undefined, id: string) {
	return (await loadPersonas(platform)).find((persona) => persona.id === id);
}

// This is the only shape that ever reaches the browser. No style card, no
// vocabulary, just the name and a few aggregate numbers for the sidebar.
export function summarise(persona: StoredPersona): PersonaSummary {
	return {
		id: persona.id,
		name: persona.name,
		tagline: persona.tagline ?? '',
		quote: persona.quote,
		accent: persona.accent ?? '#a855f7',
		voiceReady: Boolean(persona.voiceId),
		builtIn: true,
		dataThrough: persona.dataThrough,
		pronoun: persona.pronoun,
		rhythm: {
			burst: persona.rhythm?.burst ?? 0,
			medianChars: persona.rhythm?.medianChars ?? 0,
			emojiPct: persona.rhythm?.emojiPct ?? 0,
			capsPct: persona.rhythm?.capsPct ?? 0
		}
	};
}

export async function publicPersonas(platform: App.Platform | undefined) {
	return (await loadPersonas(platform)).map(summarise);
}

// Public card by default. The private one only comes out with a valid TOTP
// session.
export function cardFor(persona: StoredPersona, unlocked: boolean): string {
	if (unlocked && persona.styleCardPrivate) return persona.styleCardPrivate;
	return persona.styleCard;
}

// I take the visitor's IANA zone from the browser and do all the date maths
// in that zone. Workers run in UTC, and without this the persona thought it
// was Saturday while it was still Friday evening in Boston.
function partsIn(now: Date, timeZone: string) {
	const fmt = new Intl.DateTimeFormat('en-GB', {
		timeZone,
		weekday: 'long',
		day: '2-digit',
		month: 'long',
		year: 'numeric'
	});
	const parts = Object.fromEntries(fmt.formatToParts(now).map((x) => [x.type, x.value]));
	const monthIndex = new Date(`${parts.month} 1, 2000`).getMonth();
	return {
		label: `${parts.weekday} ${parts.day} ${parts.month} ${parts.year}`,
		year: Number(parts.year),
		month: monthIndex
	};
}

export function safeZone(candidate: unknown): string {
	if (typeof candidate !== 'string' || candidate.length > 64) return 'UTC';
	try {
		new Intl.DateTimeFormat('en-GB', { timeZone: candidate });
		return candidate;
	} catch {
		return 'UTC';
	}
}

// The date and anything relative to it. Kept out of the card itself so the
// prompt cache stays stable.
export function dynamicContext(persona: StoredPersona, timeZone = 'UTC', now = new Date()): string {
	const subject = persona.pronoun === 'she' ? 'she' : persona.pronoun === 'he' ? 'he' : 'they';
	const today = partsIn(now, timeZone);
	const parts = [`Today is ${today.label}.`];

	for (const item of persona.timeline ?? []) {
		if (!item?.date) continue;
		const when = new Date(`${item.date}T00:00:00Z`);
		if (Number.isNaN(when.getTime())) continue;
		const months = (when.getUTCFullYear() - today.year) * 12 + (when.getUTCMonth() - today.month);
		const label = when.toLocaleDateString('en-GB', { month: 'long', year: 'numeric', timeZone: 'UTC' });
		const event = item.event ?? 'that milestone';
		if (months > 1) {
			const years = Math.floor(months / 12);
			const rest = months % 12;
			const span = [
				years ? `${years} year${years === 1 ? '' : 's'}` : '',
				rest ? `${rest} month${rest === 1 ? '' : 's'}` : ''
			]
				.filter(Boolean)
				.join(' and ');
			parts.push(`${persona.name} ${event} in ${label}, about ${span} away.`);
		} else if (months >= 0) {
			parts.push(`${persona.name} ${event} this month.`);
		} else {
			const ago = Math.abs(months);
			const years = Math.floor(ago / 12);
			const span = years ? `${years} year${years === 1 ? '' : 's'}` : `${ago} months`;
			parts.push(
				`${persona.name} already finished that in ${label}, ${span} ago, so ${subject} is out of it now.`
			);
		}
	}

	parts.push('Let that shape what is going on in your life right now. Do not announce the date.');
	return parts.join(' ');
}
