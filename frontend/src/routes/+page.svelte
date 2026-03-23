<script lang="ts">
	import { goto } from '$app/navigation';
	import { authStore } from '$lib/stores/auth';

	$effect(() => {
		if ($authStore.loading) return;
		if ($authStore.user) {
			goto('/dashboard');
		} else {
			goto('/login');
		}
	});
</script>

<div class="flex items-center justify-center min-h-[60vh]">
	<p class="text-gray-400">Redirecting...</p>
</div>
