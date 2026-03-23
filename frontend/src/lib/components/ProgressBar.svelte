<script lang="ts">
	let { value, label, max }: { value: number; label?: string; max?: number } = $props();

	const percentage = $derived(max ? (value / max) * 100 : value);
	const clampedWidth = $derived(Math.min(percentage, 100));

	const fillColor = $derived(
		percentage > 95 ? 'bg-red-500' : percentage > 80 ? 'bg-amber-500' : 'bg-indigo-600'
	);
</script>

<div>
	{#if label}
		<p class="text-sm font-normal text-gray-600 mb-1">{label}</p>
	{/if}
	<div class="h-2 bg-gray-200 rounded-full">
		<div
			class="{fillColor} rounded-full h-full transition-all"
			style="width: {clampedWidth}%"
		></div>
	</div>
</div>
