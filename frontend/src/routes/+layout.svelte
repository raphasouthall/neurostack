<script lang="ts">
	import '../app.css';
	import { authStore, logout } from '$lib/stores/auth';
	import { goto } from '$app/navigation';

	let { children } = $props();

	async function handleLogout() {
		await logout();
		goto('/login');
	}
</script>

<div class="min-h-screen bg-gray-50">
	<nav class="bg-white border-b border-gray-200">
		<div class="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
			<a href="/" class="text-xl font-bold text-gray-900">NeuroStack</a>
			<div>
				{#if $authStore.user}
					<span class="text-sm text-gray-600 mr-4">{$authStore.user.email}</span>
					<button
						onclick={handleLogout}
						class="text-sm text-gray-500 hover:text-gray-700 cursor-pointer"
					>
						Sign out
					</button>
				{:else if !$authStore.loading}
					<a href="/login" class="text-sm text-indigo-600 hover:text-indigo-800">Sign in</a>
				{/if}
			</div>
		</div>
	</nav>

	<main>
		{@render children()}
	</main>
</div>
