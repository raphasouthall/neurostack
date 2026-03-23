<script lang="ts">
	import { apiFetch } from '$lib/api';
	import { authStore, logout } from '$lib/stores/auth';
	import { goto } from '$app/navigation';
	import Button from '$lib/components/Button.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import { User, Download, AlertTriangle } from 'lucide-svelte';

	let userInfo = $state({
		email: '',
		display_name: '',
		provider: '',
		created_at: '',
		tier: 'free'
	});
	let loading = $state(true);
	let exporting = $state(false);
	let showDeleteDialog = $state(false);
	let deleting = $state(false);
	let deleteError = $state('');

	$effect(() => {
		if (!$authStore.loading && !$authStore.user) {
			goto('/login');
		}
	});

	$effect(() => {
		if ($authStore.user) {
			loadProfile();
		}
	});

	async function loadProfile() {
		loading = true;
		try {
			const res = await apiFetch('/api/v1/user/register', { method: 'POST' });
			if (res.ok) {
				const data = await res.json();
				userInfo = {
					email: data.email,
					display_name: data.display_name,
					provider: data.provider,
					created_at: data.created_at || '',
					tier: data.tier
				};
			}
		} catch {
			// Non-fatal: use Firebase user data as fallback
		} finally {
			loading = false;
		}
	}

	async function handleExport() {
		exporting = true;
		try {
			const res = await apiFetch('/api/v1/user/export');
			if (res.ok) {
				const blob = await res.blob();
				const url = URL.createObjectURL(blob);
				const a = document.createElement('a');
				a.href = url;
				a.download = 'neurostack-export.zip';
				document.body.appendChild(a);
				a.click();
				document.body.removeChild(a);
				URL.revokeObjectURL(url);
			}
		} catch {
			// Error handling -- could show toast
		} finally {
			exporting = false;
		}
	}

	async function handleDelete() {
		deleting = true;
		deleteError = '';
		try {
			const res = await apiFetch('/api/v1/user/account', { method: 'DELETE' });
			if (res.ok || res.status === 204) {
				await logout();
				goto('/login');
			} else {
				deleteError = 'Failed to delete account. Please try again.';
			}
		} catch {
			deleteError = 'Something went wrong. Check your connection and try again.';
		} finally {
			deleting = false;
		}
	}

	function formatDate(dateStr: string): string {
		if (!dateStr) {
			const creationTime = $authStore.user?.metadata.creationTime;
			if (creationTime) {
				return new Date(creationTime).toLocaleDateString('en-GB', {
					day: 'numeric',
					month: 'long',
					year: 'numeric'
				});
			}
			return 'Unknown';
		}
		return new Date(dateStr).toLocaleDateString('en-GB', {
			day: 'numeric',
			month: 'long',
			year: 'numeric'
		});
	}

	function providerLabel(provider: string): string {
		if (!provider) {
			const providerId = $authStore.user?.providerData[0]?.providerId;
			if (providerId === 'google.com') return 'Google';
			if (providerId === 'github.com') return 'GitHub';
			return providerId || 'Unknown';
		}
		if (provider === 'google.com' || provider.toLowerCase() === 'google') return 'Google';
		if (provider === 'github.com' || provider.toLowerCase() === 'github') return 'GitHub';
		return provider;
	}
</script>

<div class="space-y-6">
	<h1 class="text-2xl font-semibold leading-tight text-gray-900">Account</h1>

	<!-- Account Info -->
	<div class="bg-white border border-gray-200 rounded-lg p-6">
		<div class="flex items-center gap-2 mb-4">
			<User class="w-5 h-5 text-gray-400" />
			<h2 class="text-xl font-semibold leading-tight text-gray-900">Account Info</h2>
		</div>

		{#if loading}
			<div class="grid grid-cols-1 md:grid-cols-2 gap-4">
				{#each [1, 2, 3, 4] as _}
					<div class="space-y-2">
						<div class="h-3 w-16 bg-gray-200 rounded animate-pulse"></div>
						<div class="h-4 w-40 bg-gray-200 rounded animate-pulse"></div>
					</div>
				{/each}
			</div>
		{:else}
			<div class="grid grid-cols-1 md:grid-cols-2 gap-4">
				<div>
					<p class="text-xs text-gray-500">Name</p>
					<p class="text-sm text-gray-900">
						{userInfo.display_name || $authStore.user?.displayName || 'Not set'}
					</p>
				</div>
				<div>
					<p class="text-xs text-gray-500">Email</p>
					<p class="text-sm text-gray-900">
						{userInfo.email || $authStore.user?.email || 'Not set'}
					</p>
				</div>
				<div>
					<p class="text-xs text-gray-500">Auth Provider</p>
					<p class="text-sm text-gray-900">{providerLabel(userInfo.provider)}</p>
				</div>
				<div>
					<p class="text-xs text-gray-500">Member Since</p>
					<p class="text-sm text-gray-900">{formatDate(userInfo.created_at)}</p>
				</div>
			</div>
		{/if}
	</div>

	<!-- Export Data -->
	<div class="bg-white border border-gray-200 rounded-lg p-6">
		<div class="flex items-center gap-2 mb-2">
			<Download class="w-5 h-5 text-gray-400" />
			<h2 class="text-xl font-semibold leading-tight text-gray-900">Export Data</h2>
		</div>
		<p class="text-sm text-gray-500 mb-4">Download a zip archive of your vault data.</p>
		<Button variant="secondary" disabled={exporting} onclick={handleExport}>
			{#snippet children()}
				<span class="flex items-center gap-2">
					<Download class="w-4 h-4" />
					{exporting ? 'Exporting...' : 'Export Data'}
				</span>
			{/snippet}
		</Button>
	</div>

	<!-- Danger Zone -->
	<div class="border-2 border-red-200 rounded-lg p-6">
		<div class="flex items-center gap-2 mb-2">
			<AlertTriangle class="w-5 h-5 text-red-600" />
			<h2 class="text-xl font-semibold leading-tight text-red-600">Danger Zone</h2>
		</div>
		<p class="text-sm text-gray-500 mb-4">
			Download your data before deleting your account.
		</p>

		{#if deleteError}
			<p class="text-sm text-red-500 mb-4">{deleteError}</p>
		{/if}

		<Button variant="destructive" disabled={deleting} onclick={() => (showDeleteDialog = true)}>
			{#snippet children()}
				<span class="flex items-center gap-2">
					<AlertTriangle class="w-4 h-4" />
					Delete Account
				</span>
			{/snippet}
		</Button>
	</div>
</div>

<ConfirmDialog
	open={showDeleteDialog}
	title="Delete Account"
	body="This will permanently delete your account, vault data, and billing history. This action cannot be undone."
	confirmLabel="Delete Account"
	confirmVariant="destructive"
	requireInput="DELETE"
	onconfirm={handleDelete}
	oncancel={() => (showDeleteDialog = false)}
/>
