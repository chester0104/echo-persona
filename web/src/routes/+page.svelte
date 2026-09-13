<script lang="ts">
	// Main chat page. Built in personas come from the server, imported ones
	// live in localStorage and never touch our database.
	import { onMount, tick } from 'svelte';
	import AdminPanel from '$lib/components/AdminPanel.svelte';
	import ImportDialog from '$lib/components/ImportDialog.svelte';
	import UnlockDialog from '$lib/components/UnlockDialog.svelte';
	import MessageRow from '$lib/components/MessageRow.svelte';
	import StatBar from '$lib/components/StatBar.svelte';
	import TypingDots from '$lib/components/TypingDots.svelte';
	import { browserSpeechAvailable, cancelBrowserSpeech, speakInBrowser } from '$lib/speech';
	import type { PageData } from './$types';
	import type { PersonaPack, PersonaSummary } from '$lib/types';

	let { data }: { data: PageData } = $props();

	type Entry = { id: number; role: 'user' | 'assistant'; lines: string[] };

	const STORAGE_KEY = 'echo-persona:imported';
	const UNLOCK_KEY = 'echo-persona:unlock';

	let imported = $state<PersonaPack[]>([]);
	let activeId = $state<string>(data.personas[0]?.id ?? '');
	let entries = $state<Entry[]>([]);
	let draft = $state('');
	let busy = $state(false);
	let speaking = $state(false);
	let voiceOn = $state(true);
	let notice = $state('');
	let dialogOpen = $state(false);
	let adminOpen = $state(false);
	let unlockOpen = $state(false);
	let unlockToken = $state<string | null>(null);
	let unlockExpires = $state(0);
	let privateAvailable = $state(false);
	let scroller: HTMLDivElement | null = $state(null);
	let audio: HTMLAudioElement | null = null;
	let counter = 0;

	const roster = $derived<PersonaSummary[]>([
		...data.personas,
		...imported.map((pack) => ({
			id: pack.id,
			name: pack.name,
			tagline: pack.tagline ?? 'imported persona',
			quote: pack.quote,
			accent: pack.accent ?? '#22d3ee',
			voiceReady: Boolean(pack.voiceId),
			pronoun: (pack as { pronoun?: string }).pronoun,
			dataThrough: undefined,
			builtIn: false,
			rhythm: {
				burst: pack.rhythm?.burst ?? 0,
				medianChars: pack.rhythm?.medianChars ?? 0,
				emojiPct: pack.rhythm?.emojiPct ?? 0,
				capsPct: pack.rhythm?.capsPct ?? 0
			}
		}))
	]);

	const active = $derived(roster.find((p) => p.id === activeId) ?? roster[0]);
	const cutoff = $derived(
		active?.dataThrough
			? new Date(`${active.dataThrough}T00:00:00Z`).toLocaleDateString('en-GB', {
					day: 'numeric',
					month: 'short',
					year: 'numeric'
				})
			: ''
	);
	const activePack = $derived(imported.find((p) => p.id === activeId));

	onMount(() => {
		try {
			const stored = localStorage.getItem(STORAGE_KEY);
			if (stored) imported = JSON.parse(stored);
		} catch {
			imported = [];
		}
		if (!activeId && roster.length) activeId = roster[0].id;

		try {
			const saved = JSON.parse(localStorage.getItem(UNLOCK_KEY) ?? 'null');
			if (saved?.token && saved.expiresAt > Date.now()) {
				unlockToken = saved.token;
				unlockExpires = saved.expiresAt;
			} else {
				localStorage.removeItem(UNLOCK_KEY);
			}
		} catch {
			unlockToken = null;
		}

		fetch('/api/unlock')
			.then((r) => r.json())
			.then((d) => (privateAvailable = Boolean(d?.available)))
			.catch(() => (privateAvailable = false));
	});

	const isPrivate = $derived(Boolean(unlockToken) && unlockExpires > Date.now());

	function authHeaders(): Record<string, string> {
		const base: Record<string, string> = { 'content-type': 'application/json' };
		if (isPrivate && unlockToken) base['x-echo-unlock'] = unlockToken;
		return base;
	}

	// The unlock token goes in localStorage with its expiry so a refresh does
	// not drop you back to public mode mid conversation.
	function handleUnlock(token: string, expiresAt: number) {
		unlockToken = token;
		unlockExpires = expiresAt;
		try {
			localStorage.setItem(UNLOCK_KEY, JSON.stringify({ token, expiresAt }));
		} catch {
			notice = '';
		}
		notice = 'Private mode on. Expires in an hour.';
	}

	function relock() {
		unlockToken = null;
		unlockExpires = 0;
		try {
			localStorage.removeItem(UNLOCK_KEY);
		} catch {
			notice = '';
		}
		notice = 'Back to public mode.';
	}

	function persist() {
		try {
			localStorage.setItem(STORAGE_KEY, JSON.stringify(imported));
		} catch {
			notice = 'This browser is blocking storage, so the persona will vanish on reload.';
		}
	}

	async function scrollDown() {
		await tick();
		scroller?.scrollTo({ top: scroller.scrollHeight, behavior: 'smooth' });
	}

	function stopAudio() {
		audio?.pause();
		audio = null;
		cancelBrowserSpeech();
		speaking = false;
	}

	function switchTo(id: string) {
		if (id === activeId) return;
		stopAudio();
		activeId = id;
		entries = [];
		notice = '';
	}

	// Try the cloned voice first. If the server says fallback, or the plan has
	// lapsed, use the browser's own voice so the site never goes silent.
	async function voiceFor(text: string) {
		if (!voiceOn || !text.trim()) return;
		speaking = true;
		try {
			const response = await fetch('/api/speech', {
				method: 'POST',
				headers: authHeaders(),
				body: JSON.stringify(
					activePack ? { pack: activePack, text } : { personaId: activeId, text }
				)
			});

			const kind = response.headers.get('content-type') ?? '';
			if (response.ok && kind.includes('audio')) {
				const blob = await response.blob();
				const url = URL.createObjectURL(blob);
				audio = new Audio(url);
				await audio.play().catch(() => {});
				await new Promise<void>((resolve) => {
					if (!audio) return resolve();
					audio.onended = () => resolve();
					audio.onerror = () => resolve();
				});
				URL.revokeObjectURL(url);
			} else {
				const body = await response.json().catch(() => ({}));
				if (body?.reason) notice = `Voice: ${body.reason}. Using this browser's voice instead.`;
				if (browserSpeechAvailable()) {
					await speakInBrowser(text, { preferFemale: active?.pronoun === 'she' });
				}
			}
		} catch {
			if (browserSpeechAvailable()) await speakInBrowser(text);
		} finally {
			speaking = false;
			audio = null;
		}
	}

	// I send the last 20 turns as history. The server trims again, but there is
	// no point shipping more than it will use.
	async function send() {
		const message = draft.trim();
		if (!message || busy || !active) return;
		draft = '';
		notice = '';
		stopAudio();
		entries = [...entries, { id: counter++, role: 'user', lines: [message] }];
		busy = true;
		scrollDown();

		const history = entries
			.slice(-20)
			.map((entry) => ({ role: entry.role, content: entry.lines.join('\n') }));

		try {
			const response = await fetch('/api/chat', {
				method: 'POST',
				headers: authHeaders(),
				body: JSON.stringify({
					message,
					history: history.slice(0, -1),
					timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
					...(activePack ? { pack: activePack } : { personaId: activeId })
				})
			});
			const body = await response.json().catch(() => ({}));

			if (!response.ok) {
				notice = body?.error ?? body?.message ?? 'Something went wrong reaching the model.';
				busy = false;
				return;
			}

			const lines: string[] = body.lines?.length ? body.lines : ['...'];
			entries = [...entries, { id: counter++, role: 'assistant', lines }];
			busy = false;
			scrollDown();
			voiceFor(lines.join('\n'));
		} catch {
			notice = 'Network hiccup. Try that again.';
			busy = false;
		}
	}

	function handleImport(pack: PersonaPack) {
		imported = [...imported.filter((p) => p.id !== pack.id), pack];
		persist();
		switchTo(pack.id);
		notice = `${pack.name} loaded. Stored in this browser only.`;
	}

	function forget(id: string) {
		imported = imported.filter((p) => p.id !== id);
		persist();
		if (activeId === id) switchTo(roster[0]?.id ?? '');
	}
</script>

<svelte:head>
	<title>echo-persona // talk to a cloned voice</title>
</svelte:head>

<main class="relative mx-auto flex min-h-dvh max-w-6xl flex-col px-4 py-6 sm:px-6">
	<header class="mb-6 flex flex-wrap items-end justify-between gap-4">
		<div>
			<h1 class="neon-text flicker font-mono text-2xl font-bold tracking-[0.3em] text-neon-soft sm:text-3xl">
				ECHO<span class="text-cyan">/</span>PERSONA
			</h1>
			<p class="mt-1.5 max-w-md text-[13px] leading-relaxed text-dim">
				Cloned texting styles that reply and speak at once. Nobody's messages are stored
				here, only the statistics of how they type.
			</p>
		</div>

		<div class="flex items-center gap-2">
			<button
				class="rounded-lg border px-3 py-2 font-mono text-[11px] uppercase tracking-[0.16em] transition"
				class:border-cyan={voiceOn}
				class:text-cyan={voiceOn}
				class:border-edge={!voiceOn}
				class:text-dim={!voiceOn}
				style={voiceOn ? 'background:rgba(34,211,238,.08)' : ''}
				onclick={() => {
					voiceOn = !voiceOn;
					if (!voiceOn) stopAudio();
				}}
			>
				voice {voiceOn ? 'on' : 'off'}
			</button>
			{#if privateAvailable}
				<button
					class="rounded-lg border px-3 py-2 font-mono text-[11px] uppercase tracking-[0.16em] transition"
					class:border-neon={isPrivate}
					class:text-neon-soft={isPrivate}
					class:border-edge={!isPrivate}
					class:text-dim={!isPrivate}
					style={isPrivate ? 'background:rgba(168,85,247,.12)' : ''}
					onclick={() => (isPrivate ? relock() : (unlockOpen = true))}
					title={isPrivate ? 'private mode on, click to lock' : 'unlock private mode'}
				>
					{isPrivate ? 'private' : 'public'}
				</button>
			{/if}
			<button
				class="rounded-lg border border-neon/40 bg-neon/10 px-3 py-2 font-mono text-[11px] uppercase tracking-[0.16em] text-neon-soft transition hover:bg-neon/20"
				onclick={() => (dialogOpen = true)}>+ persona</button
			>
		</div>
	</header>

	<div class="grid flex-1 gap-4 lg:grid-cols-[260px_1fr]">
		<aside class="flex flex-col gap-2.5">
			{#each roster as person (person.id)}
				<button
					class="panel group relative overflow-hidden rounded-xl px-4 py-3 text-left transition"
					class:opacity-55={person.id !== activeId}
					style={person.id === activeId
						? `border-color:${person.accent}88; box-shadow:0 0 34px -14px ${person.accent}`
						: ''}
					onclick={() => switchTo(person.id)}
				>
					<div
						class="absolute inset-y-0 left-0 w-[3px] transition-all"
						style="background:{person.accent};opacity:{person.id === activeId ? 1 : 0.25}"
					></div>

					<div class="flex items-center justify-between gap-2">
						<span class="font-mono text-sm tracking-wide" style="color:{person.accent}"
							>{person.name}</span
						>
						<span class="flex items-center gap-1.5">
							{#if person.voiceReady}
								<span
									class="rounded px-1.5 py-0.5 font-mono text-[8px] uppercase tracking-wider"
									style="background:{person.accent}22;color:{person.accent}">voice</span
								>
							{/if}
							{#if !person.builtIn}
								<span
									class="cursor-pointer font-mono text-[10px] text-dim hover:text-rose-400"
									role="button"
									tabindex="0"
									onclick={(event) => {
										event.stopPropagation();
										forget(person.id);
									}}
									onkeydown={(event) => event.key === 'Enter' && forget(person.id)}>×</span
								>
							{/if}
						</span>
					</div>

					<p class="mt-0.5 text-[11px] leading-snug text-dim">{person.tagline}</p>

					{#if person.quote}
						<p
							class="mt-1.5 border-l-2 pl-2 text-[11px] leading-snug italic text-dim/80"
							style="border-color:{person.accent}55"
						>
							"{person.quote}"
						</p>
					{/if}

					{#if person.rhythm.medianChars}
						<div class="mt-2.5 grid grid-cols-3 gap-2">
							<StatBar
								label="burst"
								value="{person.rhythm.burst}×"
								hint="messages per reply"
								accent={person.accent}
							/>
							<StatBar
								label="len"
								value="{person.rhythm.medianChars}c"
								hint="median characters"
								accent={person.accent}
							/>
							<StatBar
								label="emoji"
								value="{person.rhythm.emojiPct}%"
								hint="messages with emoji"
								accent={person.accent}
							/>
						</div>
					{/if}
				</button>
			{/each}

			<p class="mt-1 px-1 font-mono text-[10px] leading-relaxed text-dim/70">
				These numbers are measured aggregates. No message text, transcripts or audio are served by
				this site.
			</p>
		</aside>

		<section class="panel flex min-h-[62vh] flex-col overflow-hidden rounded-2xl">
			<div class="flex items-center justify-between border-b border-edge/50 px-4 py-2.5">
				<span class="font-mono text-[11px] uppercase tracking-[0.2em] text-dim">
					<span style="color:{active?.accent}">{active?.name ?? '---'}</span>
					{#if speaking}<span class="ml-2 text-cyan">// speaking</span>{/if}
				</span>
				<button
					class="font-mono text-[10px] uppercase tracking-wider text-dim transition hover:text-neon-soft"
					onclick={() => {
						entries = [];
						stopAudio();
					}}>clear</button
				>
			</div>

			<div bind:this={scroller} class="chat-scroll flex-1 space-y-4 overflow-y-auto px-4 py-5">
				{#if entries.length === 0}
					<div class="flex h-full flex-col items-center justify-center gap-2 text-center">
						<p class="font-mono text-xs uppercase tracking-[0.24em] text-dim caret">
							say something to {active?.name ?? 'them'}
						</p>
						<p class="max-w-xs text-[12px] leading-relaxed text-dim/70">
							They do not know you. No shared history, no name. You are a stranger who just
							started a conversation.
						</p>
					</div>
				{/if}

				{#each entries as entry (entry.id)}
					<MessageRow
						role={entry.role}
						lines={entry.lines}
						name={active?.name ?? ''}
						accent={active?.accent ?? '#c084fc'}
					/>
				{/each}

				{#if busy}
					<TypingDots accent={active?.accent ?? '#c084fc'} name={active?.name ?? ''} />
				{/if}
			</div>

			{#if notice}
				<p class="border-t border-amber-500/20 bg-amber-500/5 px-4 py-2 font-mono text-[11px] text-amber-300/90">
					{notice}
				</p>
			{/if}

			<form
				class="flex items-end gap-2 border-t border-edge/50 px-3 py-3"
				onsubmit={(event) => {
					event.preventDefault();
					send();
				}}
			>
				<textarea
					bind:value={draft}
					rows="1"
					maxlength="600"
					placeholder="type something..."
					class="chat-scroll max-h-28 flex-1 resize-none rounded-xl border border-edge/70 bg-black/40 px-4 py-2.5 text-[15px] text-neon-soft/95 outline-none transition placeholder:text-dim/60 focus:border-neon/60"
					onkeydown={(event) => {
						if (event.key === 'Enter' && !event.shiftKey) {
							event.preventDefault();
							send();
						}
					}}
				></textarea>
				<button
					type="submit"
					disabled={busy || !draft.trim()}
					class="rounded-xl border border-neon/50 bg-neon/15 px-5 py-2.5 font-mono text-xs uppercase tracking-[0.18em] text-neon-soft transition hover:bg-neon/25 disabled:opacity-30"
					>send</button
				>
			</form>
		</section>
	</div>

	<footer class="mt-5 flex flex-wrap items-center justify-between gap-2 px-1">
		<p class="font-mono text-[10px] text-dim/60">
			cloned with consent · statistics only · no transcripts stored
			{#if cutoff}
				<span class="text-dim/50">· knowledge cutoff {cutoff}</span>
			{/if}
		</p>
		<button
			class="font-mono text-[10px] text-dim/60 transition hover:text-cyan"
			onclick={() => (adminOpen = true)}>rate limited demo</button
		>
	</footer>
</main>

<ImportDialog bind:open={dialogOpen} onclose={() => (dialogOpen = false)} onimport={handleImport} />
<AdminPanel bind:open={adminOpen} onclose={() => (adminOpen = false)} />
<UnlockDialog bind:open={unlockOpen} onclose={() => (unlockOpen = false)} onunlock={handleUnlock} />

<svelte:window
	onkeydown={(event) => {
		if (event.key.toLowerCase() === 'a' && event.ctrlKey && event.shiftKey) {
			event.preventDefault();
			adminOpen = true;
		}
	}}
/>
