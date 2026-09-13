// The one model call the site makes.
import { env } from '$env/dynamic/private';
import type { ChatTurn } from '$lib/types';

const UNSUPPORTED = ['unsupported', 'not supported', 'unrecognized', 'unknown parameter'];

export type CompleteOptions = {
	styleCard: string;
	context?: string;
	history: ChatTurn[];
	temperature?: number;
	maxTokens?: number;
};

// Endpoints disagree on whether it is max_tokens or max_completion_tokens.
// I retry once with the other name when the error tells me which it wanted.
let tokenParam = 'max_completion_tokens';
let sendTemperature = true;

export async function complete({
	styleCard,
	context,
	history,
	temperature = 0.9,
	maxTokens = 220
}: CompleteOptions): Promise<string> {
	const key = env.OPENAI_API_KEY;
	if (!key) throw new Error('OPENAI_API_KEY is not configured on the server');
	const baseUrl = (env.OPENAI_BASE_URL || 'https://api.openai.com/v1').replace(/\/$/, '');
	const model = env.OPENAI_MODEL || 'gpt-5.6-terra';

	const messages = [
		{ role: 'system', content: styleCard },
		...(context ? [{ role: 'system', content: context }] : []),
		...history
	];

	for (let attempt = 0; attempt < 4; attempt += 1) {
		const payload: Record<string, unknown> = { model, messages, [tokenParam]: maxTokens };
		if (sendTemperature) payload.temperature = temperature;

		const response = await fetch(`${baseUrl}/chat/completions`, {
			method: 'POST',
			headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' },
			body: JSON.stringify(payload)
		});

		if (response.ok) {
			const body = await response.json();
			return (body?.choices?.[0]?.message?.content ?? '').trim();
		}

		const detail = (await response.text()).slice(0, 500);
		const lowered = detail.toLowerCase();
		if (response.status === 400 && UNSUPPORTED.some((hint) => lowered.includes(hint))) {
			if (lowered.includes('max_completion_tokens') && tokenParam !== 'max_tokens') {
				tokenParam = 'max_tokens';
				continue;
			}
			if (lowered.includes('max_tokens') && tokenParam !== 'max_completion_tokens') {
				tokenParam = 'max_completion_tokens';
				continue;
			}
			if (lowered.includes('temperature') && sendTemperature) {
				sendTemperature = false;
				continue;
			}
		}
		throw new Error(`model call failed (${response.status})`);
	}
	throw new Error('model call failed after retries');
}
