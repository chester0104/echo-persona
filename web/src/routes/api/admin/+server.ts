// Usage stats and rate limit overrides. Needs the admin token header.
import { error, json } from '@sveltejs/kit';
import { applyOverrides, isAdmin, usage } from '$lib/server/ratelimit';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = async ({ request, platform }) => {
	// 404 rather than 401 so the endpoint does not advertise itself.
	if (!isAdmin(request)) throw error(404, 'Not found');
	return json(await usage(platform));
};

export const POST: RequestHandler = async ({ request, platform }) => {
	if (!isAdmin(request)) throw error(404, 'Not found');

	let body: Record<string, unknown>;
	try {
		body = await request.json();
	} catch {
		throw error(400, 'expected a json body');
	}

	const next: { dailyCap?: number | null; resetCounter?: boolean } = {};
	if (body.dailyCap === null || typeof body.dailyCap === 'number') {
		next.dailyCap = body.dailyCap as number | null;
	}
	if (body.resetCounter === true) next.resetCounter = true;

	return json(await applyOverrides(platform, next));
};
