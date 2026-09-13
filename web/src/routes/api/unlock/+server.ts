// POST a six digit code, get back a one hour session token for private mode.
import { error, json } from '@sveltejs/kit';
import { checkLimits, clientKey } from '$lib/server/ratelimit';
import { issueSession, matchGrant, sessionGrant, totpConfigured } from '$lib/server/totp';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = async ({ request }) => {
	const grant = sessionGrant(request.headers.get('x-echo-unlock'));
	return json({
		available: totpConfigured(),
		unlocked: grant !== null,
		grantedTo: grant?.id ?? null
	});
};

export const POST: RequestHandler = async ({ request, platform, getClientAddress }) => {
	if (!totpConfigured()) throw error(404, 'Not found');

	const limit = await checkLimits(platform, clientKey(request, getClientAddress()), 'unlock');
	if (!limit.ok) {
		return json({ error: 'Too many attempts. Wait a minute.' }, { status: 429 });
	}

	let body: Record<string, unknown>;
	try {
		body = await request.json();
	} catch {
		throw error(400, 'expected a json body');
	}

	const code = typeof body.code === 'string' ? body.code : '';
	const grant = matchGrant(code);
	if (!grant) {
		return json({ error: 'That code is not valid.' }, { status: 401 });
	}

	const session = issueSession(grant);
	console.log(`private mode unlocked by grant "${grant.id}"`);
	return json({ token: session.token, expiresAt: session.expiresAt, grantedTo: grant.id });
};
