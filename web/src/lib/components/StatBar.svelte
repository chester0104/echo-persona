<script lang="ts">
	type Props = { label: string; value: string; hint?: string; accent?: string };
	let { label, value, hint = '', accent = '#c084fc' }: Props = $props();
</script>

<div class="flex flex-col gap-0.5" title={hint}>
	<span class="font-mono text-[9px] uppercase tracking-[0.2em] text-dim">{label}</span>
	<span class="font-mono text-sm" style="color:{accent}">{value}</span>
</div>
