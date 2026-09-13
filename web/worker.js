// Wrangler entry. SvelteKit builds its own worker, but a Durable Object class
// has to be exported from the main module, so this wraps the two together.
// The adapter writes to .svelte-kit/cloudflare/_worker.js via wrangler.adapter.jsonc,
// and this file is what wrangler.jsonc actually deploys.
import kit from './.svelte-kit/cloudflare/_worker.js';
export { Limiter } from './src/limiter.ts';
export default kit;
