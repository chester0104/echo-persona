// Text to speech and shared library voices.
import { env } from '$env/dynamic/private';

const API_ROOT = 'https://api.elevenlabs.io/v1';
const EMOJI = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{2190}-\u{21FF}\u{2B00}-\u{2BFF}\uFE0F]/gu;

export class VoiceUnavailable extends Error {
	constructor(
		message: string,
		readonly permanent: boolean
	) {
		super(message);
	}
}

// Strip emoji and end each line with a full stop so the voice pauses between
// messages.
export function speakable(text: string): string {
	return text
		.split('\n')
		.map((line) => line.replace(EMOJI, '').replace(/[ \t]+/g, ' ').trim())
		.filter(Boolean)
		.map((line) => (/[.!?,:;]$/.test(line) ? line : `${line}.`))
		.join(' ');
}

export async function synthesise(voiceId: string, text: string): Promise<ArrayBuffer> {
	const key = env.ELEVENLABS_API_KEY;
	if (!key) throw new VoiceUnavailable('voice is not configured', true);
	const spoken = speakable(text);
	if (!spoken) throw new VoiceUnavailable('nothing to speak', true);

	const response = await fetch(
		`${API_ROOT}/text-to-speech/${voiceId}?output_format=mp3_44100_128`,
		{
			method: 'POST',
			headers: { 'xi-api-key': key, 'Content-Type': 'application/json' },
			body: JSON.stringify({
				text: spoken,
				model_id: 'eleven_multilingual_v2',
				voice_settings: {
					stability: 0.4,
					similarity_boost: 0.85,
					style: 0.35,
					use_speaker_boost: true
				}
			})
		}
	);

	if (response.ok) return response.arrayBuffer();

	if (response.status === 401 || response.status === 402 || response.status === 403) {
		throw new VoiceUnavailable('the voice subscription has lapsed', true);
	}
	if (response.status === 429) {
		throw new VoiceUnavailable('voice quota is exhausted right now', false);
	}
	throw new VoiceUnavailable(`voice service returned ${response.status}`, false);
}

const sharedCache = new Map<string, string>();
let sharedAddsToday = 0;
let sharedStamp = new Date().toISOString().slice(0, 10);

function sharedCap(): number {
	const raw = Number(env.ECHO_SHARED_VOICE_CAP ?? 25);
	return Number.isFinite(raw) && raw > 0 ? raw : 25;
}

// Adds a voice someone shared to the ElevenLabs library onto my account so my
// key can use it. Each add uses one of my voice slots, so there is a daily cap
// and an in memory cache to avoid adding the same one twice.
export async function resolveSharedVoice(
	publicOwnerId: string,
	voiceId: string,
	label: string
): Promise<string> {
	const cacheKey = `${publicOwnerId}:${voiceId}`;
	const cached = sharedCache.get(cacheKey);
	if (cached) return cached;

	const key = env.ELEVENLABS_API_KEY;
	if (!key) throw new VoiceUnavailable('voice is not configured', true);

	const stamp = new Date().toISOString().slice(0, 10);
	if (stamp !== sharedStamp) {
		sharedStamp = stamp;
		sharedAddsToday = 0;
	}
	if (sharedAddsToday >= sharedCap()) {
		throw new VoiceUnavailable('this demo has added its limit of shared voices today', false);
	}

	const response = await fetch(
		`${API_ROOT}/voices/add/${encodeURIComponent(publicOwnerId)}/${encodeURIComponent(voiceId)}`,
		{
			method: 'POST',
			headers: { 'xi-api-key': key, 'Content-Type': 'application/json' },
			body: JSON.stringify({ new_name: `echo-guest ${label}`.slice(0, 60) })
		}
	);

	if (!response.ok) {
		if (response.status === 401 || response.status === 403) {
			throw new VoiceUnavailable('the voice subscription has lapsed', true);
		}
		if (response.status === 400 || response.status === 404) {
			throw new VoiceUnavailable(
				'that voice is not shared publicly on ElevenLabs, so it cannot be used here',
				true
			);
		}
		throw new VoiceUnavailable(`could not add the shared voice (${response.status})`, false);
	}

	const body = await response.json();
	const resolved = String(body?.voice_id ?? '');
	if (!resolved) throw new VoiceUnavailable('ElevenLabs did not return a voice id', false);
	sharedAddsToday += 1;
	sharedCache.set(cacheKey, resolved);
	return resolved;
}
