<script lang="ts">
	import { apiFetch } from '$lib/api';
	import Button from '$lib/components/Button.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import { Key, Copy, Check } from 'lucide-svelte';

	interface ApiKey {
		key_id: string;
		name: string;
		prefix: string;
		created_at: string | null;
		last_used: string | null;
	}

	let keys = $state<ApiKey[]>([]);
	let loading = $state(true);
	let error = $state('');

	// Create flow
	let showCreateModal = $state(false);
	let newKeyName = $state('');
	let createdKey = $state<string | null>(null);
	let creating = $state(false);
	let copied = $state(false);

	// Revoke flow
	let showRevokeDialog = $state(false);
	let revokeTarget = $state<ApiKey | null>(null);
	let revoking = $state(false);

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
		if (days < 30) return `${days} day${days === 1 ? '' : 's'} ago`;
		const months = Math.floor(days / 30);
		return `${months} month${months === 1 ? '' : 's'} ago`;
	}

	$effect(() => {
		loadKeys();
	});

	async function loadKeys() {
		loading = true;
		error = '';
		try {
			const res = await apiFetch('/api/v1/user/keys');
			if (res.ok) keys = await res.json();
			else error = 'Something went wrong. Check your connection and try again.';
		} catch {
			error = 'Something went wrong. Check your connection and try again.';
		} finally {
			loading = false;
		}
	}

	function openCreateModal() {
		newKeyName = '';
		createdKey = null;
		creating = false;
		copied = false;
		showCreateModal = true;
	}

	function closeCreateModal() {
		showCreateModal = false;
		if (createdKey) {
			loadKeys();
		}
	}

	async function createKey() {
		if (!newKeyName.trim()) return;
		creating = true;
		try {
			const res = await apiFetch('/api/v1/user/keys', {
				method: 'POST',
				body: JSON.stringify({ name: newKeyName.trim() })
			});
			if (res.ok) {
				const data = await res.json();
				createdKey = data.key;
			} else {
				error = 'Failed to create API key. Please try again.';
			}
		} catch {
			error = 'Something went wrong. Check your connection and try again.';
		} finally {
			creating = false;
		}
	}

	async function copyKey() {
		if (!createdKey) return;
		await navigator.clipboard.writeText(createdKey);
		copied = true;
		setTimeout(() => {
			copied = false;
		}, 2000);
	}

	async function revokeKey() {
		if (!revokeTarget) return;
		revoking = true;
		try {
			const res = await apiFetch(`/api/v1/user/keys/${revokeTarget.key_id}`, {
				method: 'DELETE'
			});
			if (res.ok || res.status === 204) {
				keys = keys.filter((k) => k.key_id !== revokeTarget!.key_id);
				showRevokeDialog = false;
				revokeTarget = null;
			} else {
				error = 'Failed to revoke key. Please try again.';
			}
		} catch {
			error = 'Something went wrong. Check your connection and try again.';
		} finally {
			revoking = false;
		}
	}
</script>

<div class="space-y-6">
	<!-- Header -->
	<div class="flex items-center justify-between">
		<h1 class="text-2xl font-semibold leading-tight text-gray-900">API Keys</h1>
		<Button variant="primary" onclick={openCreateModal}>Create API Key</Button>
	</div>

	<!-- Error -->
	{#if error}
		<p class="text-sm text-red-600">{error}</p>
	{/if}

	<!-- Content -->
	{#if loading}
		<!-- Loading skeleton -->
		<div class="bg-white border border-gray-200 rounded-lg overflow-hidden">
			<div class="p-4 space-y-4">
				<div class="animate-pulse bg-gray-200 rounded h-6"></div>
				<div class="animate-pulse bg-gray-200 rounded h-6"></div>
				<div class="animate-pulse bg-gray-200 rounded h-6"></div>
			</div>
		</div>
	{:else if keys.length === 0}
		<!-- Empty state -->
		<div class="bg-white border border-gray-200 rounded-lg p-6">
			<div class="text-center py-12">
				<Key class="mx-auto mb-4 text-gray-300" size={48} />
				<h2 class="text-xl font-semibold text-gray-900">No API keys yet</h2>
				<p class="text-sm text-gray-500 mt-1">
					Create an API key to connect Claude Code, ChatGPT, or the CLI to your vault.
				</p>
			</div>
		</div>
	{:else}
		<!-- Keys table -->
		<div class="bg-white border border-gray-200 rounded-lg overflow-x-auto">
			<table class="w-full">
				<thead>
					<tr class="bg-gray-50 text-xs font-normal text-gray-500 uppercase tracking-wide">
						<th class="px-4 py-3 text-left">Name</th>
						<th class="px-4 py-3 text-left">Key</th>
						<th class="px-4 py-3 text-left">Created</th>
						<th class="px-4 py-3 text-left">Last Used</th>
						<th class="px-4 py-3 text-right">Actions</th>
					</tr>
				</thead>
				<tbody>
					{#each keys as key}
						<tr class="border-b border-gray-100 hover:bg-gray-50">
							<td class="px-4 py-3 text-sm text-gray-900">{key.name}</td>
							<td class="px-4 py-3 text-sm text-gray-500 font-mono">{key.prefix}...</td>
							<td class="px-4 py-3 text-sm text-gray-500">{timeAgo(key.created_at)}</td>
							<td class="px-4 py-3 text-sm text-gray-500"
								>{key.last_used ? timeAgo(key.last_used) : 'Never'}</td
							>
							<td class="px-4 py-3 text-right">
								<button
									onclick={() => {
										revokeTarget = key;
										showRevokeDialog = true;
									}}
									class="text-sm text-red-500 hover:text-red-700 cursor-pointer"
								>
									Revoke
								</button>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</div>

<!-- Create API Key Modal -->
{#if showCreateModal}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="fixed inset-0 bg-black/50 z-50 flex items-center justify-center"
		onkeydown={(e) => e.key === 'Escape' && closeCreateModal()}
	>
		<div
			class="bg-white rounded-lg shadow-xl max-w-md w-full mx-4 p-6"
			role="dialog"
			aria-modal="true"
			aria-labelledby="create-key-title"
		>
			{#if createdKey}
				<!-- Key created - show plaintext key -->
				<h2 id="create-key-title" class="text-xl font-semibold leading-tight text-gray-900">
					API Key Created
				</h2>
				<p class="text-sm text-green-600 mt-2">
					API key created. Copy it now -- you won't be able to see it again.
				</p>
				<div class="mt-4">
					<code
						class="block bg-amber-50 border border-amber-200 rounded px-3 py-2 text-sm font-mono text-gray-900 break-all select-all"
					>
						{createdKey}
					</code>
				</div>
				<p class="text-sm text-amber-600 font-semibold mt-2">
					This is the only time this key will be shown. Store it securely.
				</p>
				<div class="mt-4 flex justify-between">
					<button
						onclick={copyKey}
						class="inline-flex items-center gap-1.5 text-sm text-gray-600 hover:text-gray-800 cursor-pointer"
					>
						{#if copied}
							<Check size={16} />
							Copied!
						{:else}
							<Copy size={16} />
							Copy to clipboard
						{/if}
					</button>
					<Button variant="secondary" onclick={closeCreateModal}>Done</Button>
				</div>
			{:else}
				<!-- Key name input -->
				<h2 id="create-key-title" class="text-xl font-semibold leading-tight text-gray-900">
					Create API Key
				</h2>
				<p class="text-sm text-gray-600 mt-2">
					Give your key a name to identify where it's used.
				</p>
				<div class="mt-4">
					<label for="key-name" class="block text-sm font-normal text-gray-600 mb-1">
						Key name
					</label>
					<input
						id="key-name"
						type="text"
						bind:value={newKeyName}
						onkeydown={(e) => e.key === 'Enter' && createKey()}
						placeholder="e.g. Claude Code, ChatGPT, CLI"
						class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 min-h-[44px] md:min-h-0"
					/>
				</div>
				<div class="mt-6 flex justify-end gap-3">
					<Button variant="secondary" onclick={closeCreateModal}>Cancel</Button>
					<Button
						variant="primary"
						onclick={createKey}
						disabled={creating || !newKeyName.trim()}
					>
						{creating ? 'Creating...' : 'Create'}
					</Button>
				</div>
			{/if}
		</div>
	</div>
{/if}

<!-- Revoke Confirmation Dialog -->
<ConfirmDialog
	open={showRevokeDialog}
	title="Revoke Key"
	body="This key will stop working immediately. Any tools using this key will lose access."
	confirmLabel="Revoke"
	confirmVariant="destructive"
	onconfirm={revokeKey}
	oncancel={() => {
		showRevokeDialog = false;
		revokeTarget = null;
	}}
/>
