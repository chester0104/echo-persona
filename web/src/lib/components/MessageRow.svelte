<script lang="ts">
	// One turn. Each line is its own bubble because that is how the persona
	// actually texts, in bursts rather than paragraphs.
	type Props = {
		role: 'user' | 'assistant';
		lines: string[];
		name: string;
		accent: string;
		speaking?: boolean;
	};

	let { role, lines, name, accent, speaking = false }: Props = $props();
	const mine = $derived(role === 'user');
</script>

<div class="flex flex-col gap-1.5 {mine ? 'items-end' : 'items-start'}">
	<span
		class="px-1 font-mono text-[10px] uppercase tracking-[0.22em] text-dim"
		style={mine ? '' : `color:${accent}`}
	>
		{mine ? 'you' : name}{#if speaking}<span class="ml-1.5 animate-pulse">speaking</span>{/if}
	</span>

	{#each lines as line, index (index)}
		<div
			class="rise max-w-[85%] rounded-2xl px-4 py-2.5 text-[15px] leading-snug break-words sm:max-w-[75%]"
			class:bg-white-5={false}
			style={mine
				? 'background:linear-gradient(140deg,rgba(168,85,247,.24),rgba(88,28,135,.35));border:1px solid rgba(196,181,253,.28);border-bottom-right-radius:.35rem'
				: `background:linear-gradient(140deg,rgba(24,16,44,.95),rgba(12,8,26,.95));border:1px solid ${accent}44;border-bottom-left-radius:.35rem;box-shadow:0 0 26px -12px ${accent}`}
			style:animation-delay="{index * 110}ms"
		>
			{line}
		</div>
	{/each}
</div>
