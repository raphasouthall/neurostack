<script lang="ts">
	let { tier }: { tier: 'free' | 'pro' | 'team' } = $props();

	const styles: Record<string, string> = {
		free: 'bg-indigo-50 text-indigo-700',
		pro: 'bg-indigo-600 text-white',
		team: 'bg-indigo-600 text-white'
	};

	const labels: Record<string, string> = {
		free: 'Free',
		pro: 'Pro',
		team: 'Team'
	};
</script>

<span class="rounded-full px-2.5 py-0.5 text-xs font-normal {styles[tier]}">
	{labels[tier]}
</span>
