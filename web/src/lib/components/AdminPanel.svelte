<script lang="ts">
	// Hidden behind the admin token. Shows usage and lets me raise the caps
	// without a redeploy when a link gets more traffic than I expected.
	type Usage = {
		date: string;
		used: number;
		dailyCap: number;
		remaining: number;
		ipBurst: number;
		overridden: { dailyCap: boolean; ipBurst: boolean };
		activeIps: number;
	};

	type Props = { open: boolean; onclose: () => void };
	let { open = $bindable(), onclose }: Props = $props();

	const TOKEN_KEY = 'echo-persona:admin';

	let token = $state('');
	let stats = $state<Usage | null>(null);
	let problem = $state('');
	let working = $state(false);
	let capInput = $state('');
	let burstInput = $state('');

	$effect(() => {
		if (!open) return;
		try {
			const saved = localStorage.getItem(TOKEN_KEY);
			if (saved && !token) token = saved;
		} catch {
			problem = '';
		}
	});

	function headers() {
		return { 'content-type': 'application/json', 'x-echo-admin': token };
	}

	async function load() {
		if (!token.trim()) return;
		working = true;
		problem = '';
		try {
			const response = await fetch('/api/admin', { headers: headers() });
			if (!response.ok) {
				problem = 'That token was not accepted.';
				stats = null;
			} else {
				stats = await response.json();
				capInput = String(stats!.dailyCap);
				burstInput = String(stats!.ipBurst);
				try {
					localStorage.setItem(TOKEN_KEY, token);
				} catch {
					problem = '';
				}
			}
		} catch {
			problem = 'Could not reach the server.';
		} finally {
			working = false;
		}
	}

	async function send(payload: Record<string, unknown>) {
		working = true;
		problem = '';
		try {
			const response = await fetch('/api/admin', {
				method: 'POST',
				headers: headers(),
				body: JSON.stringify(payload)
			});
			if (!response.ok) {
				problem = 'That change was rejected.';
			} else {
				stats = await response.json();
				capInput = String(stats!.dailyCap);
				burstInput = String(stats!.ipBurst);
			}
		} catch {
			problem = 'Could not reach the server.';
		} finally {
			working = false;
		}
	}

	function signOut() {
		try {
			localStorage.removeItem(TOKEN_KEY);
		} catch {
			problem = '';
		}
		token = '';
		stats = null;
	}
</script>

{#if open}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm"
		role="presentation"
		onclick={(event) => event.target === event.currentTarget && onclose()}
	>
		<div class="panel w-full max-w-md rounded-2xl">
			<div class="flex items-center justify-between border-b border-edge/60 px-5 py-3.5">
				<h2 class="font-mono text-sm uppercase tracking-[0.24em] text-cyan">admin</h2>
				<button
					class="rounded-md px-2 py-1 font-mono text-xs text-dim transition hover:text-cyan"
					onclick={onclose}>[esc]</button
				>
			</div>

			<div class="px-5 py-4">
				{#if !stats}
					<label for="admin-token" class="font-mono text-[10px] uppercase tracking-[0.2em] text-dim"
						>admin token</label
					>
					<input
						id="admin-token"
						type="password"
						bind:value={token}
						autocomplete="off"
						class="mt-2 w-full rounded-lg border border-edge/70 bg-black/50 px-3 py-2 font-mono text-sm text-cyan outline-none transition focus:border-cyan/60"
						onkeydown={(event) => event.key === 'Enter' && load()}
					/>
					<button
						class="mt-3 w-full rounded-lg border border-cyan/40 bg-cyan/10 px-4 py-2.5 font-mono text-xs uppercase tracking-[0.18em] text-cyan transition hover:bg-cyan/20 disabled:opacity-40"
						disabled={working || !token.trim()}
						onclick={load}>unlock</button
					>
				{:else}
					<div class="grid grid-cols-2 gap-3 font-mono text-xs">
						<div class="rounded-lg border border-edge/60 bg-black/30 p-3">
							<div class="text-[9px] uppercase tracking-[0.2em] text-dim">used today</div>
							<div class="mt-1 text-lg text-cyan">{stats.used}</div>
						</div>
						<div class="rounded-lg border border-edge/60 bg-black/30 p-3">
							<div class="text-[9px] uppercase tracking-[0.2em] text-dim">remaining</div>
							<div class="mt-1 text-lg" style="color:{stats.remaining > 0 ? '#c084fc' : '#f87171'}">
								{stats.remaining}
							</div>
						</div>
					</div>

					<p class="mt-2 font-mono text-[10px] text-dim">
						{stats.date} · {stats.activeIps} active ips
					</p>

					<div class="mt-4 space-y-3">
						<div>
							<label for="cap" class="font-mono text-[10px] uppercase tracking-[0.2em] text-dim">
								daily cap {stats.overridden.dailyCap ? '(overridden)' : ''}
							</label>
							<div class="mt-1 flex gap-2">
								<input
									id="cap"
									type="number"
									min="0"
									bind:value={capInput}
									class="w-full rounded-lg border border-edge/70 bg-black/50 px-3 py-2 font-mono text-sm text-neon-soft outline-none focus:border-neon/60"
								/>
								<button
									class="rounded-lg border border-neon/40 bg-neon/10 px-3 font-mono text-[11px] uppercase text-neon-soft transition hover:bg-neon/20"
									disabled={working}
									onclick={() => send({ dailyCap: Number(capInput) })}>set</button
								>
							</div>
						</div>

					</div>

					<div class="mt-4 flex flex-wrap gap-2">
						<button
							class="rounded-lg border border-edge/70 px-3 py-2 font-mono text-[10px] uppercase tracking-wider text-dim transition hover:text-neon-soft"
							disabled={working}
							onclick={() => send({ resetCounter: true })}>reset counter</button
						>
						<button
							class="rounded-lg border border-edge/70 px-3 py-2 font-mono text-[10px] uppercase tracking-wider text-dim transition hover:text-neon-soft"
							disabled={working}
							onclick={() => send({ dailyCap: null })}>clear override</button
						>
						<button
							class="rounded-lg border border-edge/70 px-3 py-2 font-mono text-[10px] uppercase tracking-wider text-dim transition hover:text-rose-400"
							onclick={signOut}>sign out</button
						>
					</div>

					<p class="mt-3 font-mono text-[10px] leading-relaxed text-dim/70">
						The daily cap override is stored in KV, so every edge location sees it. The per
						visitor burst of {stats.ipBurst} a minute is fixed in wrangler.jsonc.
					</p>
				{/if}

				{#if problem}
					<p class="mt-2 font-mono text-[11px] text-rose-400">{problem}</p>
				{/if}
			</div>
		</div>
	</div>
{/if}

<svelte:window
	onkeydown={(event) => {
		if (event.key === 'Escape' && open) onclose();
	}}
/>
