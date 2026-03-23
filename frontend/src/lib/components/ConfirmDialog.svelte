<script lang="ts">
	let {
		open,
		title,
		body,
		confirmLabel = 'Confirm',
		confirmVariant = 'destructive',
		requireInput,
		onconfirm,
		oncancel
	}: {
		open: boolean;
		title: string;
		body: string;
		confirmLabel?: string;
		confirmVariant?: 'primary' | 'destructive';
		requireInput?: string;
		onconfirm: () => void;
		oncancel: () => void;
	} = $props();

	let inputValue = $state('');
	let dialogEl: HTMLDivElement | undefined = $state();

	const canConfirm = $derived(!requireInput || inputValue === requireInput);

	$effect(() => {
		if (open) {
			inputValue = '';
			// Focus first interactive element
			setTimeout(() => {
				const firstInput = dialogEl?.querySelector('input, button') as HTMLElement | null;
				firstInput?.focus();
			}, 0);
		}
	});

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			oncancel();
		}
	}
</script>

{#if open}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="fixed inset-0 bg-black/50 z-50 flex items-center justify-center"
		onkeydown={handleKeydown}
	>
		<div
			bind:this={dialogEl}
			class="bg-white rounded-lg shadow-xl max-w-md w-full mx-4 p-6"
			role="dialog"
			aria-modal="true"
			aria-labelledby="confirm-dialog-title"
		>
			<h2 id="confirm-dialog-title" class="text-xl font-semibold leading-tight text-gray-900">
				{title}
			</h2>
			<p class="text-sm font-normal text-gray-600 mt-2">{body}</p>

			{#if requireInput}
				<div class="mt-4">
					<label for="confirm-input" class="block text-sm font-normal text-gray-600 mb-1">
						Type <strong>{requireInput}</strong> to confirm
					</label>
					<input
						id="confirm-input"
						type="text"
						bind:value={inputValue}
						class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
					/>
				</div>
			{/if}

			<div class="mt-6 flex justify-end gap-3">
				<button
					onclick={oncancel}
					class="bg-white text-gray-700 border border-gray-300 hover:bg-gray-50 rounded-lg px-4 py-2.5 text-sm font-normal min-h-[44px] md:min-h-0 cursor-pointer"
				>
					Cancel
				</button>
				<button
					onclick={onconfirm}
					disabled={!canConfirm}
					class="rounded-lg px-4 py-2.5 text-sm font-semibold min-h-[44px] md:min-h-0 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed {confirmVariant === 'destructive' ? 'bg-red-500 text-white hover:bg-red-600' : 'bg-indigo-600 text-white hover:bg-indigo-700'}"
				>
					{confirmLabel}
				</button>
			</div>
		</div>
	</div>
{/if}
