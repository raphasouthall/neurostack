<script lang="ts">
	import type { Component } from 'svelte';

	let { label, value, icon }: { label: string; value: string | number; icon?: Component } = $props();
</script>

<div
	class="bg-white border border-gray-200 rounded-lg p-6"
	aria-label="{label}: {value}"
>
	<div class="flex items-center justify-between">
		<p class="text-xs font-normal leading-normal text-gray-500">{label}</p>
		{#if icon}
			<svelte:component this={icon} class="w-4 h-4 text-gray-400" />
		{/if}
	</div>
	<p class="text-2xl font-semibold leading-tight text-gray-900 mt-2">{value}</p>
</div>
