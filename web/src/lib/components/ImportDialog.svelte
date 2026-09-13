<script lang="ts">
	// Lets a visitor bring their own persona pack. Nothing is trained here. They
	// take the prompt to another chatbot and paste back the JSON it produces.
	import { DERIVE_PROMPT } from '$lib/promptTemplate';
	import type { PersonaPack } from '$lib/types';

	type Props = {
		open: boolean;
		onclose: () => void;
		onimport: (pack: PersonaPack) => void;
	};

	let { open = $bindable(), onclose, onimport }: Props = $props();

	let raw = $state('');
	let problem = $state('');
	let copied = $state(false);
	let tab = $state<'how' | 'paste'>('how');

	async function copyPrompt() {
		try {
			await navigator.clipboard.writeText(DERIVE_PROMPT);
			copied = true;
			setTimeout(() => (copied = false), 2200);
		} catch {
			problem = 'Could not reach the clipboard. Select the text and copy it manually.';
		}
	}

	// I validate the shape but not the content. It is their persona and it only
	// ever lives in their browser.
	function attemptImport() {
		problem = '';
		let parsed: unknown;
		try {
			parsed = JSON.parse(raw.replace(/^```(?:json)?/i, '').replace(/```$/, '').trim());
		} catch {
			problem = 'That is not valid JSON. Paste the whole object, including the outer braces.';
			return;
		}
		const pack = parsed as Partial<PersonaPack> & { publicOwnerId?: string };
		if (!pack || typeof pack !== 'object') {
			problem = 'Expected a JSON object.';
			return;
		}
		if (!pack.styleCard || typeof pack.styleCard !== 'string' || pack.styleCard.length < 80) {
			problem = 'The pack needs a "styleCard" string describing how the person texts.';
			return;
		}
		if (pack.styleCard.length > 8000) {
			problem = 'That styleCard is too long. Keep it under 8000 characters.';
			return;
		}
		if (!pack.name || typeof pack.name !== 'string') {
			problem = 'The pack needs a "name".';
			return;
		}
		onimport({
			schema: 'echo-persona/1',
			id: (pack.id || pack.name).toString().toLowerCase().replace(/[^a-z0-9]+/g, '') || 'imported',
			name: pack.name,
			tagline: pack.tagline ?? 'imported persona',
			accent: pack.accent ?? '#22d3ee',
			styleCard: pack.styleCard,
			voiceId: pack.voiceId || undefined,
			rhythm: pack.rhythm ?? {},
			...(pack.publicOwnerId ? { publicOwnerId: pack.publicOwnerId } : {})
		} as PersonaPack);
		raw = '';
		open = false;
	}
</script>

{#if open}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm"
		role="presentation"
		onclick={(event) => event.target === event.currentTarget && onclose()}
	>
		<div class="panel relative max-h-[88vh] w-full max-w-2xl overflow-hidden rounded-2xl">
			<div class="flex items-center justify-between border-b border-edge/60 px-5 py-3.5">
				<h2 class="neon-text font-mono text-sm uppercase tracking-[0.24em] text-neon-soft">
					bring your own persona
				</h2>
				<button
					class="rounded-md px-2 py-1 font-mono text-xs text-dim transition hover:text-neon-soft"
					onclick={onclose}>[esc]</button
				>
			</div>

			<div class="flex gap-1 border-b border-edge/40 px-5 pt-3">
				{#each [['how', '1. build the pack'], ['paste', '2. paste it in']] as [key, label] (key)}
					<button
						class="rounded-t-md px-3 py-2 font-mono text-[11px] uppercase tracking-wider transition"
						class:text-neon-soft={tab === key}
						class:text-dim={tab !== key}
						style={tab === key ? 'border-bottom:2px solid #c084fc' : 'border-bottom:2px solid transparent'}
						onclick={() => (tab = key as 'how' | 'paste')}>{label}</button
					>
				{/each}
			</div>

			<div class="chat-scroll max-h-[62vh] overflow-y-auto px-5 py-4">
				{#if tab === 'how'}
					<p class="text-sm leading-relaxed text-dim">
						Nothing is trained here and your messages never touch this server. You take your own
						chat export to <span class="text-neon-soft">Claude, ChatGPT or Gemini</span>, ask it to
						measure how someone texts, and it hands back a small JSON pack of
						<span class="text-neon-soft">statistics only</span>, never message text.
					</p>

					<ol class="mt-4 space-y-2 text-sm text-dim">
						<li><span class="font-mono text-neon-soft">01</span> Copy the prompt below.</li>
						<li>
							<span class="font-mono text-neon-soft">02</span> Paste it into any chatbot, then paste your
							chat export underneath and name the person.
						</li>
						<li>
							<span class="font-mono text-neon-soft">03</span> Copy the JSON it returns and bring it back
							to tab 2.
						</li>
					</ol>

					<button
						class="mt-4 w-full rounded-lg border border-neon/40 bg-neon/10 px-4 py-2.5 font-mono text-xs uppercase tracking-[0.18em] text-neon-soft transition hover:bg-neon/20"
						onclick={copyPrompt}
					>
						{copied ? 'copied to clipboard' : 'copy the prompt'}
					</button>

					<pre
						class="chat-scroll mt-3 max-h-52 overflow-auto rounded-lg border border-edge/60 bg-black/50 p-3 font-mono text-[11px] leading-relaxed text-dim whitespace-pre-wrap">{DERIVE_PROMPT}</pre>

					<div class="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3">
						<p class="font-mono text-[10px] uppercase tracking-[0.2em] text-amber-400/90">
							about voices
						</p>
						<p class="mt-1.5 text-[13px] leading-relaxed text-dim">
							To make your persona speak, clone your voice on ElevenLabs and
							<span class="text-amber-300/90">share it to the public Voice Library</span>, then put
							its <code class="font-mono text-neon-soft">voiceId</code> and
							<code class="font-mono text-neon-soft">publicOwnerId</code> in the pack.
							<span class="text-amber-300/90"
								>Sharing makes that voice public on ElevenLabs, so anyone can find and use
								it.</span
							> Leave both blank and your persona will speak with a generic browser voice instead.
						</p>
					</div>
				{:else}
					<label
						for="pack-json"
						class="font-mono text-[10px] uppercase tracking-[0.2em] text-dim">persona pack json</label
					>
					<textarea
						id="pack-json"
						bind:value={raw}
						spellcheck="false"
						placeholder={'{\n  "schema": "echo-persona/1",\n  "name": "Sam",\n  "styleCard": "You are Sam. You are not an AI assistant..."\n}'}
						class="chat-scroll mt-2 h-56 w-full resize-none rounded-lg border border-edge/70 bg-black/50 p-3 font-mono text-[12px] leading-relaxed text-neon-soft/90 outline-none transition focus:border-neon/60"
					></textarea>

					{#if problem}
						<p class="mt-2 font-mono text-[11px] text-rose-400">{problem}</p>
					{/if}

					<p class="mt-2 text-[12px] leading-relaxed text-dim">
						Stored in this browser only. It is sent with each message so the model can answer in that
						style, and is never written to our database.
					</p>

					<button
						class="mt-3 w-full rounded-lg border border-cyan/40 bg-cyan/10 px-4 py-2.5 font-mono text-xs uppercase tracking-[0.18em] text-cyan transition hover:bg-cyan/20 disabled:opacity-40"
						disabled={!raw.trim()}
						onclick={attemptImport}>load persona</button
					>
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
