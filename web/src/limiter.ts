// A Durable Object that holds one counter. Cloudflare routes every request for
// a given name to the same instance, so the count is exact, which the built in
// rate limit binding is not. One object per visitor IP for bursts, one named
// "daily" for the site wide budget.
//
// This file uses only relative imports because wrangler bundles it outside of
// SvelteKit, so $lib aliases would not resolve.

type Hit = { count: number; resetAt: number };

export class Limiter {
	private state: DurableObjectState;

	constructor(state: DurableObjectState) {
		this.state = state;
	}

	async fetch(request: Request): Promise<Response> {
		const url = new URL(request.url);
		const limit = Number(url.searchParams.get('limit') ?? 0);
		const period = Number(url.searchParams.get('period') ?? 60) * 1000;
		const action = url.searchParams.get('action') ?? 'hit';

		const now = Date.now();
		let hit = (await this.state.storage.get<Hit>('hit')) ?? { count: 0, resetAt: now + period };
		if (now >= hit.resetAt) hit = { count: 0, resetAt: now + period };

		if (action === 'read') {
			return Response.json({ count: hit.count, resetAt: hit.resetAt });
		}
		if (action === 'reset') {
			await this.state.storage.delete('hit');
			return Response.json({ count: 0, resetAt: now + period });
		}

		if (limit > 0 && hit.count >= limit) {
			return Response.json(
				{ ok: false, count: hit.count, retryAfter: Math.ceil((hit.resetAt - now) / 1000) },
				{ status: 429 }
			);
		}

		hit.count += 1;
		await this.state.storage.put('hit', hit);
		return Response.json({ ok: true, count: hit.count, resetAt: hit.resetAt });
	}
}

interface DurableObjectState {
	storage: {
		get<T>(key: string): Promise<T | undefined>;
		put<T>(key: string, value: T): Promise<void>;
		delete(key: string): Promise<boolean>;
	};
}
