<script lang="ts">
	// Six digit code in, one hour session token out.
	type Props = {
		open: boolean;
		onclose: () => void;
		onunlock: (token: string, expiresAt: number) => void;
	};

	let { open = $bindable(), onclose, onunlock }: Props = $props();

	let code = $state('');
	let problem = $state('');
	let working = $state(false);

	async function submit() {
		const digits = code.replace(/\D/g, '');
		if (digits.length !== 6) {
			problem = 'Enter the 6 digit code from your authenticator.';
			return;
		}
		working = true;
		problem = '';
		try {
			const response = await fetch('/api/unlock', {
				method: 'POST',
				headers: { 'content-type': 'application/json' },
				body: JSON.stringify({ code: digits })
			});
			const body = await response.json().catch(() => ({}));
			if (!response.ok) {
				problem = body?.error ?? 'That did not work.';
				code = '';
				return;
			}
			onunlock(body.token, body.expiresAt);
			code = '';
			open = false;
		} catch {
			problem = 'Could not reach the server.';
		} finally {
			working = false;
		}
	}
</script>

{#if open}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm"
		role="presentation"
		onclick={(event) => event.target === event.currentTarget && onclose()}
	>
		<div class="panel w-full max-w-sm rounded-2xl">
			<div class="flex items-center justify-between border-b border-edge/60 px-5 py-3.5">
				<h2 class="font-mono text-sm uppercase tracking-[0.24em] text-neon-soft">private mode</h2>
				<button
					class="rounded-md px-2 py-1 font-mono text-xs text-dim transition hover:text-neon-soft"
					onclick={onclose}>[esc]</button
				>
			</div>

			<div class="px-5 py-4">
				<p class="text-[13px] leading-relaxed text-dim">
					In public mode these personas keep things light. Private mode lets them talk about the
					heavier stuff they actually discuss. Enter the rotating code from your authenticator app.
				</p>

				<label for="totp" class="mt-4 block font-mono text-[10px] uppercase tracking-[0.2em] text-dim"
					>6 digit code</label
				>
				<input
					id="totp"
					inputmode="numeric"
					autocomplete="one-time-code"
					maxlength="7"
					bind:value={code}
					placeholder="000000"
					class="mt-2 w-full rounded-lg border border-edge/70 bg-black/50 px-3 py-3 text-center font-mono text-2xl tracking-[0.4em] text-neon-soft outline-none transition focus:border-neon/60"
					onkeydown={(event) => event.key === 'Enter' && submit()}
				/>

				{#if problem}
					<p class="mt-2 font-mono text-[11px] text-rose-400">{problem}</p>
				{/if}

				<button
					class="mt-3 w-full rounded-lg border border-neon/40 bg-neon/10 px-4 py-2.5 font-mono text-xs uppercase tracking-[0.18em] text-neon-soft transition hover:bg-neon/20 disabled:opacity-40"
					disabled={working || code.replace(/\D/g, '').length !== 6}
					onclick={submit}>unlock for 1 hour</button
				>

				<p class="mt-3 font-mono text-[10px] leading-relaxed text-dim/70">
					The code rotates every 30 seconds. Unlocking lasts an hour in this browser, then it
					returns to public mode on its own.
				</p>
			</div>
		</div>
	</div>
{/if}

<svelte:window
	onkeydown={(event) => {
		if (event.key === 'Escape' && open) onclose();
	}}
/>
