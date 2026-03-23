<script lang="ts">
	import { goto } from '$app/navigation';
	import { authStore } from '$lib/stores/auth';
	import { apiFetch } from '$lib/api';
	import StatCard from '$lib/components/StatCard.svelte';
	import ProgressBar from '$lib/components/ProgressBar.svelte';
	import JobStatusBadge from '$lib/components/JobStatusBadge.svelte';
	import DataTable from '$lib/components/DataTable.svelte';
	import { FileText, Layers, Cpu, Clock } from 'lucide-svelte';

	let stats = $state({ note_count: 0, chunk_count: 0, embedding_count: 0, last_sync: null as string | null });
	let health = $state({ embedding_coverage_pct: 0, summary_coverage_pct: 0, triple_count: 0 });
	let jobs = $state<Array<{ job_id: string; status: string; note_count: number; started: string | null; duration: number | null }>>([]);
	let loading = $state(true);
	let error = $state('');

	$effect(() => {
		if (!$authStore.loading && !$authStore.user) {
			goto('/login');
		}
	});

	$effect(() => {
		if ($authStore.user) {
			loadData();
		}
	});

	async function loadData() {
		loading = true;
		error = '';
		try {
			const [statsRes, healthRes, jobsRes] = await Promise.all([
				apiFetch('/v1/vault/stats'),
				apiFetch('/v1/vault/health'),
				apiFetch('/v1/vault/jobs?limit=10')
			]);
			if (statsRes.ok) stats = await statsRes.json();
			if (healthRes.ok) health = await healthRes.json();
			if (jobsRes.ok) jobs = await jobsRes.json();
		} catch (e) {
			error = 'Something went wrong. Check your connection and try again.';
		} finally {
			loading = false;
		}
	}

	function timeAgo(isoString: string | null): string {
		if (!isoString) return 'Never';
		const now = Date.now();
		const then = new Date(isoString).getTime();
		const seconds = Math.floor((now - then) / 1000);

		if (seconds < 60) return 'Just now';
		const minutes = Math.floor(seconds / 60);
		if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`;
		const hours = Math.floor(minutes / 60);
		if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`;
		const days = Math.floor(hours / 24);
		return `${days} day${days === 1 ? '' : 's'} ago`;
	}

	function formatDuration(seconds: number | null): string {
		if (seconds === null) return '-';
		if (seconds < 60) return `${seconds}s`;
		const m = Math.floor(seconds / 60);
		const s = seconds % 60;
		return s > 0 ? `${m}m ${s}s` : `${m}m`;
	}

	const jobColumns = [
		{ key: 'job_id', label: 'Job ID' },
		{ key: 'status', label: 'Status' },
		{ key: 'note_count', label: 'Notes' },
		{ key: 'started', label: 'Started' },
		{ key: 'duration', label: 'Duration' }
	];

	const isEmpty = $derived(!loading && stats.note_count === 0);
</script>

{#if $authStore.loading}
	<div class="flex items-center justify-center min-h-[60vh]">
		<div class="text-gray-400">Loading...</div>
	</div>
{:else if $authStore.user}
	<div class="space-y-6">
		<h1 class="text-2xl font-semibold leading-tight text-gray-900">Dashboard</h1>

		{#if error}
			<div class="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">{error}</div>
		{/if}

		{#if loading}
			<div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
				<div class="animate-pulse bg-gray-200 rounded-lg h-24"></div>
				<div class="animate-pulse bg-gray-200 rounded-lg h-24"></div>
				<div class="animate-pulse bg-gray-200 rounded-lg h-24"></div>
				<div class="animate-pulse bg-gray-200 rounded-lg h-24"></div>
			</div>
			<div class="space-y-4">
				<div class="animate-pulse bg-gray-200 rounded-lg h-8 w-48"></div>
				<div class="animate-pulse bg-gray-200 rounded-lg h-6"></div>
				<div class="animate-pulse bg-gray-200 rounded-lg h-6"></div>
			</div>
		{:else if isEmpty}
			<div class="bg-white border border-gray-200 rounded-lg p-12 text-center">
				<h2 class="text-xl font-semibold text-gray-900 mb-2">No vault indexed yet</h2>
				<p class="text-sm text-gray-500">
					Push your Markdown vault from the CLI to get started. Run <code class="bg-gray-100 px-1.5 py-0.5 rounded text-sm">neurostack cloud push</code> in your terminal.
				</p>
			</div>
		{:else}
			<!-- Stat Cards -->
			<div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
				<StatCard label="Note Count" value={stats.note_count.toLocaleString()} icon={FileText} />
				<StatCard label="Chunk Count" value={stats.chunk_count.toLocaleString()} icon={Layers} />
				<StatCard label="Embedding Count" value={stats.embedding_count.toLocaleString()} icon={Cpu} />
				<StatCard label="Last Sync" value={timeAgo(stats.last_sync)} icon={Clock} />
			</div>

			<!-- Vault Health -->
			<div class="space-y-4">
				<h2 class="text-xl font-semibold leading-tight text-gray-900">Vault Health</h2>
				<ProgressBar label="Embedding Coverage" value={health.embedding_coverage_pct} />
				<ProgressBar label="Summary Coverage" value={health.summary_coverage_pct} />
				<p class="text-sm text-gray-600">{health.triple_count.toLocaleString()} triples</p>
			</div>

			<!-- Job History -->
			<div class="space-y-4">
				<h2 class="text-xl font-semibold leading-tight text-gray-900">Job History</h2>
				{#if jobs.length === 0}
					<div class="bg-white border border-gray-200 rounded-lg p-8 text-center">
						<h3 class="text-xl font-semibold text-gray-900 mb-2">No indexing jobs yet</h3>
						<p class="text-sm text-gray-500">Jobs appear here after you push your vault. Run <code class="bg-gray-100 px-1.5 py-0.5 rounded text-sm">neurostack cloud push</code> to start your first index.</p>
					</div>
				{:else}
					{#snippet cell(row: Record<string, any>, col: { key: string; label: string })}
						{#if col.key === 'status'}
							<JobStatusBadge status={row.status} />
						{:else if col.key === 'job_id'}
							<span class="font-mono text-xs">{row.job_id.slice(0, 8)}</span>
						{:else if col.key === 'started'}
							{timeAgo(row.started)}
						{:else if col.key === 'duration'}
							{formatDuration(row.duration)}
						{:else}
							{row[col.key]}
						{/if}
					{/snippet}
					<DataTable columns={jobColumns} rows={jobs} {cell} />
				{/if}
			</div>
		{/if}
	</div>
{/if}
