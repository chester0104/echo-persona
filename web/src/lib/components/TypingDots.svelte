<script lang="ts">
	let { accent = '#c084fc', name = '' }: { accent?: string; name?: string } = $props();
</script>

<div class="flex flex-col items-start gap-1.5">
	<span class="px-1 font-mono text-[10px] uppercase tracking-[0.22em]" style="color:{accent}">
		{name}
	</span>
	<div
		class="flex items-center gap-1.5 rounded-2xl rounded-bl-sm px-4 py-3"
		style="background:linear-gradient(140deg,rgba(24,16,44,.95),rgba(12,8,26,.95));border:1px solid {accent}33"
	>
		{#each [0, 1, 2] as dot (dot)}
			<span
				class="h-1.5 w-1.5 rounded-full"
				style="background:{accent};animation:pulse-glow 1.1s ease-in-out infinite {dot * 0.16}s"
			></span>
		{/each}
	</div>
</div>
