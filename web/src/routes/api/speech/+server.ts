// POST /api/speech. Returns mp3 bytes, or a fallback flag if voice is unavailable.
import { error, json } from '@sveltejs/kit';
import { getPersona } from '$lib/server/personas';
import { VoiceUnavailable, resolveSharedVoice, synthesise } from '$lib/server/elevenlabs';
import { checkLimits, clientKey, isAdmin } from '$lib/server/ratelimit';
import type { RequestHandler } from './$types';

const MAX_SPEECH_CHARS = 500;

export const POST: RequestHandler = async ({ request, platform, getClientAddress }) => {
	const limit = isAdmin(request)
		? ({ ok: true } as const)
		: await checkLimits(platform, clientKey(request, getClientAddress()));
	if (!limit.ok) return json({ error: limit.message, fallback: true }, { status: limit.status });

	let body: Record<string, unknown>;
	try {
		body = await request.json();
	} catch {
		throw error(400, 'expected a json body');
	}

	const text = typeof body.text === 'string' ? body.text.slice(0, MAX_SPEECH_CHARS).trim() : '';
	if (!text) throw error(400, 'text is required');

	let voiceId: string | undefined;
	if (typeof body.personaId === 'string' && body.personaId) {
		voiceId = (await getPersona(platform, body.personaId))?.voiceId;
	} else if (body.pack && typeof body.pack === 'object') {
		const pack = body.pack as Record<string, unknown>;
		const sharedVoice = typeof pack.voiceId === 'string' ? pack.voiceId : '';
		const owner = typeof pack.publicOwnerId === 'string' ? pack.publicOwnerId : '';
		if (sharedVoice && owner) {
			try {
				voiceId = await resolveSharedVoice(
					owner,
					sharedVoice,
					typeof pack.name === 'string' ? pack.name : 'persona'
				);
			} catch (cause) {
				const reason = cause instanceof VoiceUnavailable ? cause.message : 'shared voice failed';
				return json({ fallback: true, reason }, { status: 200 });
			}
		} else if (sharedVoice) {
			return json(
				{
					fallback: true,
					reason:
						'an imported voice needs the ElevenLabs public owner id as well, and the voice must be shared publicly'
				},
				{ status: 200 }
			);
		}
	}

	// No voice means the client falls back to browser speech. I return 200 with
	// a fallback flag rather than an error so the chat keeps working.
	if (!voiceId) {
		return json({ fallback: true, reason: 'no cloned voice for this persona' }, { status: 200 });
	}

	try {
		const audio = await synthesise(voiceId, text);
		return new Response(audio, {
			headers: { 'content-type': 'audio/mpeg', 'cache-control': 'private, max-age=3600' }
		});
	} catch (cause) {
		const reason = cause instanceof VoiceUnavailable ? cause.message : 'voice generation failed';
		console.error('speech failed', cause);
		return json({ fallback: true, reason }, { status: 200 });
	}
};
