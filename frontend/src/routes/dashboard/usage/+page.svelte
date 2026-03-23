<script lang="ts">
	import { goto } from '$app/navigation';
	import { authStore } from '$lib/stores/auth';
	import { apiFetch } from '$lib/api';
	import TierBadge from '$lib/components/TierBadge.svelte';
	import ProgressBar from '$lib/components/ProgressBar.svelte';
	import Button from '$lib/components/Button.svelte';

	let usage = $state({
		queries: 0,
		index_jobs: 0,
		notes_indexed: 0,
		period: '',
		tier: 'free' as 'free' | 'pro' | 'team',
		limits: { queries_per_month: 500, notes_max: 200, index_jobs_per_month: 50 }
	});
	let loading = $state(true);
	let error = $state('');
	let portalLoading = $state(false);
	let upgradeLoading = $state(false);

	$effect(() => {
		if (!$authStore.loading && !$authStore.user) {
			goto('/login');
		}
	});

	$effect(() => {
		if ($authStore.user) {
			loadUsage();
		}
	});

	async function loadUsage() {
		loading = true;
		error = '';
		try {
			const res = await apiFetch('/v1/usage');
			if (res.ok) {
				usage = await res.json();
			} else {
				error = 'Something went wrong. Check your connection and try again.';
			}
		} catch {
			error = 'Something went wrong. Check your connection and try again.';
		} finally {
			loading = false;
		}
	}

	async function handleUpgrade() {
		upgradeLoading = true;
		try {
			const res = await apiFetch('/v1/billing/checkout', {
				method: 'POST',
				body: JSON.stringify({
					price_id: 'price_pro',
					success_url: window.location.origin + '/dashboard/usage',
					cancel_url: window.location.origin + '/dashboard/usage'
				})
			});
			if (res.ok) {
				const { checkout_url } = await res.json();
				window.location.href = checkout_url;
			}
		} finally {
			upgradeLoading = false;
		}
	}

	async function handlePortal() {
		portalLoading = true;
		try {
			const res = await apiFetch('/v1/billing/portal', {
				method: 'POST',
				body: JSON.stringify({
					return_url: window.location.origin + '/dashboard/usage'
				})
			});
			if (res.ok) {
				const { portal_url } = await res.json();
				window.location.href = portal_url;
			}
		} finally {
			portalLoading = false;
		}
	}

	const planNames: Record<string, string> = {
		free: 'Free Plan',
		pro: 'Pro Plan',
		team: 'Team Plan'
	};

	const queryPct = $derived(usage.limits.queries_per_month > 0 ? (usage.queries / usage.limits.queries_per_month) * 100 : 0);
	const jobPct = $derived(usage.limits.index_jobs_per_month > 0 ? (usage.index_jobs / usage.limits.index_jobs_per_month) * 100 : 0);
	const notesPct = $derived(usage.limits.notes_max > 0 ? (usage.notes_indexed / usage.limits.notes_max) * 100 : 0);
	const maxPct = $derived(Math.max(queryPct, jobPct, notesPct));
</script>

{#if $authStore.loading}
	<div class="flex items-center justify-center min-h-[60vh]">
		<div class="text-gray-400">Loading...</div>
	</div>
{:else if $authStore.user}
	<div class="space-y-6">
		<h1 class="text-2xl font-semibold leading-tight text-gray-900">Usage & Billing</h1>

		{#if error}
			<div class="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">{error}</div>
		{/if}

		{#if loading}
			<div class="space-y-4">
				<div class="animate-pulse bg-gray-200 rounded-lg h-10 w-32"></div>
				<div class="grid grid-cols-1 md:grid-cols-3 gap-4">
					<div class="animate-pulse bg-gray-200 rounded-lg h-32"></div>
					<div class="animate-pulse bg-gray-200 rounded-lg h-32"></div>
					<div class="animate-pulse bg-gray-200 rounded-lg h-32"></div>
				</div>
			</div>
		{:else}
			<!-- Tier Section -->
			<div class="flex items-center gap-3">
				<TierBadge tier={usage.tier} />
				<span class="text-sm font-normal text-gray-600">{planNames[usage.tier] || usage.tier}</span>
			</div>

			{#if usage.tier === 'free'}
				<p class="text-sm text-gray-500">You're on the Free plan. Upgrade for unlimited queries and indexing.</p>
			{/if}

			<!-- Usage Warning -->
			{#if maxPct > 80}
				<p class="text-sm text-amber-600">You've used {Math.round(maxPct)}% of your monthly quota.</p>
			{/if}

			<!-- Usage Stats Grid -->
			<div class="grid grid-cols-1 md:grid-cols-3 gap-4">
				<div class="bg-white border border-gray-200 rounded-lg p-6 space-y-3">
					<p class="text-xs font-normal leading-normal text-gray-500">Queries</p>
					<p class="text-2xl font-semibold leading-tight text-gray-900">{usage.queries} <span class="text-sm font-normal text-gray-500">of {usage.limits.queries_per_month}</span></p>
					<ProgressBar value={queryPct} />
				</div>
				<div class="bg-white border border-gray-200 rounded-lg p-6 space-y-3">
					<p class="text-xs font-normal leading-normal text-gray-500">Index Jobs</p>
					<p class="text-2xl font-semibold leading-tight text-gray-900">{usage.index_jobs} <span class="text-sm font-normal text-gray-500">of {usage.limits.index_jobs_per_month}</span></p>
					<ProgressBar value={jobPct} />
				</div>
				<div class="bg-white border border-gray-200 rounded-lg p-6 space-y-3">
					<p class="text-xs font-normal leading-normal text-gray-500">Notes Indexed</p>
					<p class="text-2xl font-semibold leading-tight text-gray-900">{usage.notes_indexed} <span class="text-sm font-normal text-gray-500">of {usage.limits.notes_max}</span></p>
					<ProgressBar value={notesPct} />
				</div>
			</div>

			<!-- Action Buttons -->
			<div class="flex flex-col sm:flex-row gap-3">
				{#if usage.tier === 'free'}
					<Button variant="primary" onclick={handleUpgrade} disabled={upgradeLoading}>
						{upgradeLoading ? 'Redirecting...' : 'Upgrade Plan'}
					</Button>
				{/if}
				<Button variant="secondary" onclick={handlePortal} disabled={portalLoading}>
					{portalLoading ? 'Opening...' : 'Manage Billing'}
				</Button>
			</div>
		{/if}
	</div>
{/if}
