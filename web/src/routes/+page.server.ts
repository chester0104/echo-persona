import { publicPersonas } from '$lib/server/personas';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ platform }) => {
	return { personas: await publicPersonas(platform) };
};
