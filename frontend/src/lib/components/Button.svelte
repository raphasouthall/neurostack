<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		variant = 'primary',
		disabled = false,
		type = 'button',
		onclick,
		children
	}: {
		variant?: 'primary' | 'secondary' | 'destructive' | 'ghost';
		disabled?: boolean;
		type?: 'button' | 'submit';
		onclick?: (e: MouseEvent) => void;
		children: Snippet;
	} = $props();

	const base = 'rounded-lg text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed';

	const variants: Record<string, string> = {
		primary: 'bg-indigo-600 text-white hover:bg-indigo-700 px-4 py-2.5 font-semibold',
		secondary: 'bg-white text-gray-700 border border-gray-300 hover:bg-gray-50 px-4 py-2.5 font-normal',
		destructive: 'bg-red-500 text-white hover:bg-red-600 px-4 py-2.5 font-semibold',
		ghost: 'text-gray-500 hover:text-gray-700 font-normal'
	};
</script>

<button
	{type}
	{disabled}
	{onclick}
	class="{base} {variants[variant]} min-h-[44px] md:min-h-0 cursor-pointer"
>
	{@render children()}
</button>
