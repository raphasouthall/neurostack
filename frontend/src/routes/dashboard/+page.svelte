<script lang="ts">
	import { goto } from '$app/navigation';
	import { authStore } from '$lib/stores/auth';

	$effect(() => {
		if (!$authStore.loading && !$authStore.user) {
			goto('/login');
		}
	});
</script>

{#if $authStore.loading}
	<div class="flex items-center justify-center min-h-[60vh]">
		<div class="text-gray-400">Loading...</div>
	</div>
{:else if $authStore.user}
	<div class="max-w-4xl mx-auto px-4 py-8">
		<h1 class="text-2xl font-bold text-gray-900 mb-2">
			Welcome, {$authStore.user.displayName || 'User'}
		</h1>
		<p class="text-gray-600 mb-6">{$authStore.user.email}</p>

		<div class="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
			<p class="text-gray-500">Dashboard coming in Phase 9</p>
		</div>
	</div>
{/if}
