<script lang="ts">
	import { signInWithPopup, GoogleAuthProvider, GithubAuthProvider } from 'firebase/auth';
	import { auth } from '$lib/firebase';
	import { goto } from '$app/navigation';
	import { authStore } from '$lib/stores/auth';
	import { apiFetch } from '$lib/api';

	let error = $state('');
	let loading = $state(false);

	$effect(() => {
		if (!$authStore.loading && $authStore.user) {
			goto('/dashboard');
		}
	});

	async function loginWithGoogle() {
		await loginWithProvider(new GoogleAuthProvider());
	}

	async function loginWithGitHub() {
		await loginWithProvider(new GithubAuthProvider());
	}

	async function loginWithProvider(provider: GoogleAuthProvider | GithubAuthProvider) {
		error = '';
		loading = true;
		try {
			await signInWithPopup(auth, provider);

			// Register with backend (creates user + Stripe customer on first login)
			const response = await apiFetch('/api/v1/user/register', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' }
			});

			if (!response.ok) {
				console.warn('Registration call failed:', response.status);
				// Non-fatal: user is authenticated in Firebase even if backend fails
			}

			goto('/dashboard');
		} catch (err: unknown) {
			if (err instanceof Error) {
				error = err.message;
			} else {
				error = 'An unexpected error occurred. Please try again.';
			}
		} finally {
			loading = false;
		}
	}
</script>

<div class="flex items-center justify-center min-h-[80vh]">
	<div class="w-full max-w-sm bg-white rounded-lg shadow-md p-8">
		<h1 class="text-2xl font-bold text-center text-gray-900 mb-2">NeuroStack Cloud</h1>
		<p class="text-sm text-center text-gray-500 mb-8">Sign in to manage your vault</p>

		{#if error}
			<p class="text-red-500 text-sm text-center mb-4">{error}</p>
		{/if}

		<div class="space-y-3">
			<button
				onclick={loginWithGoogle}
				disabled={loading}
				class="w-full flex items-center justify-center gap-3 px-4 py-2.5 border border-gray-300 rounded-lg bg-white text-gray-700 font-medium hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
			>
				<svg class="w-5 h-5" viewBox="0 0 24 24">
					<path
						d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"
						fill="#4285F4"
					/>
					<path
						d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
						fill="#34A853"
					/>
					<path
						d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
						fill="#FBBC05"
					/>
					<path
						d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
						fill="#EA4335"
					/>
				</svg>
				Continue with Google
			</button>

			<button
				onclick={loginWithGitHub}
				disabled={loading}
				class="w-full flex items-center justify-center gap-3 px-4 py-2.5 rounded-lg bg-gray-900 text-white font-medium hover:bg-gray-800 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
			>
				<svg class="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
					<path
						d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0 1 12 6.844a9.59 9.59 0 0 1 2.504.337c1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.02 10.02 0 0 0 22 12.017C22 6.484 17.522 2 12 2z"
					/>
				</svg>
				Continue with GitHub
			</button>
		</div>

		<p class="mt-6 text-xs text-center text-gray-400">
			By signing in, you agree to our terms of service.
		</p>
	</div>
</div>
