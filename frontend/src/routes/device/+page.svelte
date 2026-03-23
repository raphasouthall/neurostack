<script lang="ts">
	import { apiFetch } from '$lib/api';
	import { authStore } from '$lib/stores/auth';
	import { goto } from '$app/navigation';
	import Button from '$lib/components/Button.svelte';
	import { CheckCircle } from 'lucide-svelte';

	let code = $state('');
	let confirming = $state(false);
	let confirmed = $state(false);
	let error = $state('');

	$effect(() => {
		if (!$authStore.loading && !$authStore.user) {
			goto('/login?redirect=/device');
		}
	});

	async function confirmDevice() {
		if (!code.trim()) return;
		confirming = true;
		error = '';
		try {
			const res = await apiFetch('/api/v1/auth/device-confirm', {
				method: 'POST',
				body: JSON.stringify({ user_code: code.toUpperCase().trim() })
			});
			if (res.ok) {
				confirmed = true;
			} else {
				error = 'Invalid or expired code. Please try again.';
			}
		} catch {
			error = 'Something went wrong. Check your connection and try again.';
		} finally {
			confirming = false;
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && code.trim() && !confirming && !confirmed) {
			confirmDevice();
		}
	}
</script>

<div class="flex items-center justify-center min-h-[60vh]">
	<div class="w-full max-w-sm bg-white rounded-lg shadow-md p-8">
		{#if confirmed}
			<div class="text-center">
				<div class="flex justify-center mb-4">
					<CheckCircle class="w-12 h-12 text-green-500" />
				</div>
				<h1 class="text-2xl font-semibold leading-tight text-gray-900 mb-2">
					Device Authorized
				</h1>
				<p class="text-sm text-gray-500">
					You can return to your terminal. The CLI will complete login automatically.
				</p>
			</div>
		{:else}
			<h1 class="text-2xl font-semibold leading-tight text-gray-900 text-center mb-2">
				Authorize Device
			</h1>
			<p class="text-sm text-gray-500 text-center mb-6">
				Enter the code shown in your terminal
			</p>

			{#if error}
				<p class="text-sm text-red-500 text-center mb-4">{error}</p>
			{/if}

			<!-- svelte-ignore a11y_no_static_element_interactions -->
			<div onkeydown={handleKeydown}>
				<input
					type="text"
					bind:value={code}
					placeholder="ABCD-EFGH"
					maxlength="9"
					class="w-full text-center uppercase tracking-widest text-2xl font-mono border border-gray-300 rounded-lg px-3 py-4 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 mb-4"
					autocomplete="off"
					spellcheck="false"
				/>
			</div>

			<Button
				variant="primary"
				disabled={confirming || !code.trim()}
				onclick={confirmDevice}
			>
				{#snippet children()}
					<span class="w-full text-center block">
						{confirming ? 'Confirming...' : 'Confirm'}
					</span>
				{/snippet}
			</Button>
		{/if}
	</div>
</div>
