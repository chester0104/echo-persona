// GET the persona list for the sidebar. Names and numbers only.
import { json } from '@sveltejs/kit';
import { publicPersonas } from '$lib/server/personas';
import { budgetRemaining } from '$lib/server/ratelimit';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = async ({ platform }) => {
	return json({
		personas: await publicPersonas(platform),
		budget: await budgetRemaining(platform)
	});
};
