<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { apiFetch } from '$lib/api';
	import Button from '$lib/components/Button.svelte';
	import { Search } from 'lucide-svelte';

	let depth = $state($page.url.searchParams.get('depth') || 'auto');
	let query = $state('');
	let results = $state<any>(null);
	let loading = $state(false);
	let error = $state('');
	let resultCount = $state(0);

	function setDepth(d: string) {
		depth = d;
		const url = new URL($page.url);
		url.searchParams.set('depth', d);
		goto(url.toString(), { replaceState: true, noScroll: true });
	}

	async function runQuery() {
		if (!query.trim()) return;
		loading = true;
		error = '';
		results = null;
		try {
			const res = await apiFetch('/v1/vault/query', {
				method: 'POST',
				body: JSON.stringify({ query: query.trim(), depth, top_k: 10, mode: 'hybrid' })
			});
			if (res.ok) {
				results = await res.json();
				resultCount =
					(results.triples?.length || 0) +
					(results.summaries?.length || 0) +
					(results.chunks?.length || 0);
			} else if (res.status === 429) {
				error =
					'Usage limit reached for this billing period. Upgrade your plan for unlimited access.';
			} else if (res.status === 404) {
				error =
					'Query failed. Your vault may still be indexing -- check job status and try again.';
			} else {
				error = 'Something went wrong. Check your connection and try again.';
			}
		} catch {
			error = 'Something went wrong. Check your connection and try again.';
		} finally {
			loading = false;
		}
	}
</script>

<div class="space-y-6">
	<h1 class="text-2xl font-semibold leading-tight text-gray-900">Query Playground</h1>

	<!-- Search input and Run button -->
	<div class="flex gap-2">
		<input
			type="text"
			bind:value={query}
			onkeydown={(e) => e.key === 'Enter' && runQuery()}
			placeholder="Search your indexed vault..."
			class="flex-1 px-4 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 bg-white min-h-[44px] md:min-h-0"
		/>
		<Button variant="primary" onclick={runQuery} disabled={loading || !query.trim()}>
			Run Query
		</Button>
	</div>

	<!-- Depth selector -->
	<div class="flex gap-1 bg-gray-100 rounded-lg p-1">
		{#each ['triples', 'summaries', 'full', 'auto'] as d}
			<button
				onclick={() => setDepth(d)}
				class="flex-1 px-3 py-1.5 rounded-md text-sm transition-colors cursor-pointer min-h-[44px] md:min-h-0
					{depth === d
					? 'bg-white text-gray-900 shadow-sm font-semibold'
					: 'text-gray-500 hover:text-gray-700 font-normal'}"
			>
				{d.charAt(0).toUpperCase() + d.slice(1)}
			</button>
		{/each}
	</div>

	<!-- Results area -->
	<div class="bg-white border border-gray-200 rounded-lg p-6">
		{#if loading}
			<!-- Loading state -->
			<div class="animate-pulse bg-gray-200 rounded h-6 mb-3"></div>
			<div class="animate-pulse bg-gray-200 rounded h-6 mb-3"></div>
			<div class="animate-pulse bg-gray-200 rounded h-6 mb-3"></div>
		{:else if error}
			<!-- Error state -->
			<p class="text-sm text-red-600">{error}</p>
		{:else if results !== null}
			{#if resultCount === 0}
				<!-- Empty results -->
				<p class="text-sm text-gray-500">
					No results found. Try a broader query or different depth.
				</p>
			{:else}
				<!-- Results -->
				<p class="text-xs text-gray-500 mb-3">
					{resultCount} result{resultCount !== 1 ? 's' : ''}
				</p>

				{#if results.triples?.length > 0}
					<div class="mb-4">
						<h3 class="text-sm font-semibold text-gray-900 mb-2">Triples</h3>
						{#each results.triples as triple}
							<code
								class="block bg-gray-50 px-3 py-2 rounded text-xs font-mono text-gray-800 mb-2"
							>
								{triple.subject} &mdash; {triple.predicate} &mdash; {triple.object}
							</code>
						{/each}
					</div>
				{/if}

				{#if results.summaries?.length > 0}
					<div class="mb-4">
						<h3 class="text-sm font-semibold text-gray-900 mb-2">Summaries</h3>
						{#each results.summaries as summary}
							<div class="mb-3">
								<h3 class="text-sm font-semibold text-gray-900">{summary.title}</h3>
								<p class="text-sm text-gray-600">{summary.summary}</p>
							</div>
						{/each}
					</div>
				{/if}

				{#if results.chunks?.length > 0}
					<div class="mb-4">
						<h3 class="text-sm font-semibold text-gray-900 mb-2">Chunks</h3>
						{#each results.chunks as chunk}
							<pre class="text-xs text-gray-700 whitespace-pre-wrap bg-gray-50 px-3 py-2 rounded mb-2">{chunk.text}</pre>
						{/each}
					</div>
				{/if}
			{/if}
		{:else}
			<!-- Initial empty state -->
			<div class="text-center py-12">
				<Search class="mx-auto mb-4 text-gray-300" size={48} />
				<h2 class="text-xl font-semibold text-gray-900">Try a query</h2>
				<p class="text-sm text-gray-500 mt-1">
					Search your indexed vault. Type a question and select a depth level.
				</p>
			</div>
		{/if}
	</div>
</div>
