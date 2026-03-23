<script lang="ts">
	let { status }: { status: 'queued' | 'indexing' | 'complete' | 'failed' } = $props();

	const styles: Record<string, string> = {
		queued: 'bg-gray-100 text-gray-600',
		indexing: 'bg-amber-50 text-amber-700',
		complete: 'bg-green-50 text-green-700',
		failed: 'bg-red-50 text-red-700'
	};
</script>

<span
	class="rounded-full px-2 py-0.5 text-xs font-normal {styles[status]}"
	aria-label="Status: {status}"
>
	{status}
</span>
