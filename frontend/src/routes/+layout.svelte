<script lang="ts">
	import '../app.css';
	import { page } from '$app/stores';
	import { authStore, logout } from '$lib/stores/auth';
	import { goto } from '$app/navigation';
	import TierBadge from '$lib/components/TierBadge.svelte';
	import { Database, BarChart3, Search, Key, User, Menu, X } from 'lucide-svelte';

	let { children } = $props();

	// Public routes that don't require authentication
	const publicRoutes = ['/', '/login'];

	// Mobile menu state
	let menuOpen = $state(false);

	// Tier state (default free, will be fetched from /v1/usage in Plans 03+)
	let tier: 'free' | 'pro' | 'team' = $state('free');

	// Navigation items
	const navItems = [
		{ label: 'Vault', href: '/dashboard', icon: Database },
		{ label: 'Usage', href: '/dashboard/usage', icon: BarChart3 },
		{ label: 'Playground', href: '/dashboard/playground', icon: Search },
		{ label: 'Keys', href: '/dashboard/keys', icon: Key },
		{ label: 'Account', href: '/dashboard/account', icon: User }
	];

	// Active nav detection
	function isActive(href: string, pathname: string): boolean {
		if (href === '/dashboard') {
			return pathname === '/dashboard' || pathname === '/dashboard/vault';
		}
		return pathname.startsWith(href);
	}

	// Auth guard: redirect unauthenticated users away from protected routes
	$effect(() => {
		if (!$authStore.loading && !$authStore.user && !publicRoutes.includes($page.url.pathname)) {
			goto('/login');
		}
	});

	// Close mobile menu on navigation
	$effect(() => {
		$page.url.pathname;
		menuOpen = false;
	});

	async function handleLogout() {
		await logout();
		goto('/login');
	}
</script>

{#if $authStore.loading}
	<div class="flex items-center justify-center min-h-screen bg-gray-50">
		<p class="text-gray-500">Loading...</p>
	</div>
{:else}
	<div class="min-h-screen bg-gray-50">
		<nav class="bg-white border-b border-gray-200">
			<div class="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
				<!-- Logo -->
				<a href="/dashboard" class="text-xl font-bold text-gray-900">NeuroStack</a>

				<!-- Desktop nav items -->
				<div class="hidden md:flex items-center gap-1">
					{#each navItems as item}
						<a
							href={item.href}
							class="flex items-center gap-1.5 px-3 py-2 text-sm transition-colors {isActive(item.href, $page.url.pathname)
								? 'text-indigo-600 border-b-2 border-indigo-600'
								: 'text-gray-500 hover:text-gray-700'}"
						>
							<svelte:component this={item.icon} class="w-4 h-4" />
							{item.label}
						</a>
					{/each}
				</div>

				<!-- Right side: tier badge, email, sign out, hamburger -->
				<div class="flex items-center gap-3">
					{#if $authStore.user}
						<TierBadge {tier} />
						<span class="hidden md:inline text-sm text-gray-600">{$authStore.user.email}</span>
						<button
							onclick={handleLogout}
							class="hidden md:inline text-sm text-gray-500 hover:text-gray-700 font-normal cursor-pointer"
						>
							Sign out
						</button>
						<!-- Hamburger button (mobile only) -->
						<button
							onclick={() => (menuOpen = !menuOpen)}
							class="md:hidden p-2 text-gray-500 hover:text-gray-700 min-h-[44px] min-w-[44px] flex items-center justify-center cursor-pointer"
							aria-expanded={menuOpen}
							aria-controls="mobile-nav"
							aria-label="Toggle navigation menu"
						>
							{#if menuOpen}
								<X class="w-6 h-6" />
							{:else}
								<Menu class="w-6 h-6" />
							{/if}
						</button>
					{:else}
						<a href="/login" class="text-sm text-indigo-600 hover:text-indigo-800">Sign in</a>
					{/if}
				</div>
			</div>

			<!-- Mobile nav panel -->
			{#if menuOpen}
				<div id="mobile-nav" class="md:hidden border-t border-gray-200 bg-white">
					<div class="px-4 py-2 space-y-1">
						{#each navItems as item}
							<a
								href={item.href}
								class="flex items-center gap-2 px-3 py-3 text-sm rounded-lg min-h-[44px] transition-colors {isActive(item.href, $page.url.pathname)
									? 'text-indigo-600 bg-indigo-50'
									: 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'}"
							>
								<svelte:component this={item.icon} class="w-4 h-4" />
								{item.label}
							</a>
						{/each}
						<div class="border-t border-gray-100 pt-2 mt-2">
							<span class="block px-3 py-2 text-sm text-gray-600">{$authStore.user?.email}</span>
							<button
								onclick={handleLogout}
								class="w-full text-left px-3 py-3 text-sm text-gray-500 hover:text-gray-700 min-h-[44px] cursor-pointer"
							>
								Sign out
							</button>
						</div>
					</div>
				</div>
			{/if}
		</nav>

		<main class="max-w-6xl mx-auto px-4 py-8">
			{@render children()}
		</main>
	</div>
{/if}
