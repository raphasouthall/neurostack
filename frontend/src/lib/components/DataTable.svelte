<script lang="ts">
	import type { Snippet } from 'svelte';

	let { columns, rows, cell }: {
		columns: { key: string; label: string }[];
		rows: Record<string, any>[];
		cell?: Snippet<[Record<string, any>, { key: string; label: string }]>;
	} = $props();
</script>

<div class="bg-white border border-gray-200 rounded-lg overflow-x-auto">
	<table class="w-full">
		<thead>
			<tr class="bg-gray-50">
				{#each columns as col}
					<th class="text-left px-4 py-3 text-xs font-normal text-gray-500 uppercase tracking-wide">
						{col.label}
					</th>
				{/each}
			</tr>
		</thead>
		<tbody>
			{#each rows as row}
				<tr class="border-b border-gray-100 hover:bg-gray-50">
					{#each columns as col}
						<td class="px-4 py-3 text-sm font-normal text-gray-900">
							{#if cell}
								{@render cell(row, col)}
							{:else}
								{row[col.key]}
							{/if}
						</td>
					{/each}
				</tr>
			{/each}
		</tbody>
	</table>
</div>
