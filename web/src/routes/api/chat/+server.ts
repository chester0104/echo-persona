// POST /api/chat. Picks the public or private card depending on the unlock
// header, appends the date context, and calls the model.
import { error, json } from '@sveltejs/kit';
import { cardFor, dynamicContext, getPersona, safeZone } from '$lib/server/personas';
import { complete } from '$lib/server/openai';
import { checkLimits, clientKey, isAdmin } from '$lib/server/ratelimit';
import { isUnlocked } from '$lib/server/totp';
import type { ChatTurn } from '$lib/types';
import type { RequestHandler } from './$types';

// Caps so a single request cannot run up a big bill.
const MAX_MESSAGE_CHARS = 600;
const MAX_HISTORY = 20;
const MAX_CARD_CHARS = 8000;

// The client sends its own history. I trust the shape but not the size.
function sanitiseHistory(raw: unknown): ChatTurn[] {
	if (!Array.isArray(raw)) return [];
	return raw
		.filter((turn): turn is ChatTurn => {
			if (!turn || typeof turn !== 'object') return false;
			const role = (turn as ChatTurn).role;
			const content = (turn as ChatTurn).content;
			return (role === 'user' || role === 'assistant') && typeof content === 'string';
		})
		.slice(-MAX_HISTORY)
		.map((turn) => ({ role: turn.role, content: turn.content.slice(0, MAX_MESSAGE_CHARS) }));
}

export const POST: RequestHandler = async ({ request, platform, getClientAddress }) => {
	const limit = isAdmin(request)
		? ({ ok: true } as const)
		: await checkLimits(platform, clientKey(request, getClientAddress()));
	if (!limit.ok) {
		return json(
			{ error: limit.message },
			{ status: limit.status, headers: limit.retryAfter ? { 'retry-after': String(limit.retryAfter) } : {} }
		);
	}

	let body: Record<string, unknown>;
	try {
		body = await request.json();
	} catch {
		throw error(400, 'expected a json body');
	}

	const message = typeof body.message === 'string' ? body.message.trim() : '';
	if (!message) throw error(400, 'message is required');
	if (message.length > MAX_MESSAGE_CHARS) throw error(413, 'message is too long');

	const history = sanitiseHistory(body.history);

	let styleCard: string;
	let voiceId: string | undefined;
	let personaId: string;
	let context = '';

	if (typeof body.personaId === 'string' && body.personaId) {
		const persona = await getPersona(platform, body.personaId);
		if (!persona) throw error(404, 'unknown persona');
		styleCard = cardFor(persona, isUnlocked(request));
		context = dynamicContext(persona, safeZone(body.timeZone));
		voiceId = persona.voiceId;
		personaId = persona.id;
	} else if (body.pack && typeof body.pack === 'object') {
		const pack = body.pack as Record<string, unknown>;
		const card = typeof pack.styleCard === 'string' ? pack.styleCard : '';
		if (!card.trim()) throw error(400, 'imported persona has no styleCard');
		styleCard = card.slice(0, MAX_CARD_CHARS);
		voiceId = typeof pack.voiceId === 'string' ? pack.voiceId : undefined;
		personaId = typeof pack.id === 'string' ? pack.id : 'imported';
	} else {
		throw error(400, 'provide personaId or pack');
	}

	let reply: string;
	try {
		reply = await complete({
			styleCard,
			context,
			history: [...history, { role: 'user', content: message }]
		});
	} catch (cause) {
		console.error('chat failed', cause);
		throw error(502, 'the model did not respond');
	}

	const lines = reply
		.split('\n')
		.map((line) => line.trim())
		.filter(Boolean);

	return json({
		personaId,
		lines,
		voiceReady: Boolean(voiceId),
		mode: isUnlocked(request) ? 'private' : 'public'
	});
};
