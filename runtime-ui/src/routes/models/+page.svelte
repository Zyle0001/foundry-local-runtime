<script lang="ts">
	import { onMount, onDestroy } from 'svelte';

	// =====================
	// Types (inventory-only)
	// =====================

	type ModelsInventory = {
		models: ModelEntry[];
	};

	type ModelEntry = {
		id: string;
		root?: string;
		path?: string | null;
		loaded?: boolean;
		missing?: boolean;
		variants?: ModelVariant[];
	};

	type ModelVariant = {
		id: string;
		artifacts: string[];
	};

	type OnnxVariant = {
		artifact_set: {
			completeness: {
				status: 'complete' | 'incomplete';
				reason?: string;
			};
		};
	};

	// =====================
	// State
	// =====================

	let inventory: ModelsInventory | null = null;
	let loading = true;
	let error: string | null = null;
	let vram: { used?: number; total?: number; free?: number; error?: string } | null = null;
	let actionError: string | null = null;
	let selectedVariant: Record<string, string> = {};
	let optionsById: Record<string, { voices: string[]; configs: string[] }> = {};
	let activeById: Record<string, { voice?: string | null; config?: string | null }> = {};
	let smokeById: Record<string, { status: 'ok' | 'error'; runtime_ms?: number; error?: string }> = {};

	// =====================
	// Lifecycle
	// =====================

	async function fetchInventory() {
		try {
			const res = await fetch('http://127.0.0.1:8000/models');
			if (!res.ok) {
				throw new Error(`HTTP ${res.status}`);
			}
			inventory = await res.json();
			console.log('Inventory:', inventory);
			if (inventory?.models) {
				await Promise.all(inventory.models.filter((m) => !m.missing).map((m) => fetchOptions(m.id)));
			}
		} catch (e) {
			error = e instanceof Error ? e.message : 'Unknown error';
		} finally {
			loading = false;
		}
	}

	onMount(fetchInventory);

	async function fetchVram() {
		try {
			const res = await fetch('http://127.0.0.1:8000/status');
			if (!res.ok) {
				throw new Error(`HTTP ${res.status}`);
			}
			const data = await res.json();
			vram = {
				used: data.vram_used_mb,
				total: data.vram_total_mb,
				free: data.vram_free_mb,
				error: data.error
			};
		} catch (e) {
			vram = { error: e instanceof Error ? e.message : 'Unknown error' };
		}
	}

	let vramInterval: ReturnType<typeof setInterval> | null = null;
	onMount(() => {
		fetchVram();
		vramInterval = setInterval(fetchVram, 3000);
	});
	onDestroy(() => {
		if (vramInterval) {
			clearInterval(vramInterval);
		}
	});

	async function loadModel(id: string) {
		actionError = null;
		const variant = selectedVariant[id];
		const res = await fetch('http://127.0.0.1:8000/models/load', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(variant ? { id, variant } : { id })
		});
		if (!res.ok) {
			const detail = await res.text();
			actionError = detail || `Load failed (HTTP ${res.status})`;
		}
		await fetchInventory();
		await fetchVram();
	}

	async function unloadModel(id: string) {
		actionError = null;
		const res = await fetch('http://127.0.0.1:8000/models/unload', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ id })
		});
		if (!res.ok) {
			const detail = await res.text();
			actionError = detail || `Unload failed (HTTP ${res.status})`;
		}
		await fetchInventory();
		await fetchVram();
	}

	async function fetchOptions(id: string) {
		const res = await fetch(`http://127.0.0.1:8000/models/${id}/options`);
		if (!res.ok) {
			return;
		}
		optionsById[id] = await res.json();
	}

	async function setActive(id: string, next: { voice?: string | null; config?: string | null }) {
		actionError = null;
		const payload: { voice?: string | null; config?: string | null } = {};
		if (next.voice !== undefined) payload.voice = next.voice;
		if (next.config !== undefined) payload.config = next.config;
		const res = await fetch(`http://127.0.0.1:8000/models/${id}/active`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(payload)
		});
		if (!res.ok) {
			const detail = await res.text();
			actionError = detail || `Update failed (HTTP ${res.status})`;
			return;
		}
		activeById[id] = { ...activeById[id], ...next };
	}

	async function smokeTest(id: string) {
		actionError = null;
		const res = await fetch(`http://127.0.0.1:8000/models/${id}/smoke`, {
			method: 'POST'
		});
		if (!res.ok) {
			const detail = await res.text();
			smokeById[id] = { status: 'error', error: detail || `Smoke failed (HTTP ${res.status})` };
			return;
		}
		const data = await res.json();
		smokeById[id] = { status: 'ok', runtime_ms: data.runtime_ms };
	}

	// =====================
	// Helpers
	// =====================

	function statusMark(variant: OnnxVariant) {
		return variant.artifact_set.completeness.status === 'complete'
			? '✓'
			: '✗';
	}
</script>

<div class="page-title-row">
	<div>
		<h1>Models</h1>
		<p class="page-title-muted">Manage local ONNX models and their runtime status.</p>
	</div>

	<div class="models-vram-card" aria-label="VRAM usage">
		<div class="models-vram-label">VRAM</div>
		{#if vram?.error}
			<div class="models-vram-error">{vram.error}</div>
		{:else if vram?.used !== undefined && vram?.total !== undefined}
			<div class="models-vram-main">
				<span class="models-vram-value">{vram.used}</span>
				<span class="models-vram-separator">/</span>
				<span class="models-vram-total">{vram.total} MB</span>
			</div>
			{#if vram?.free !== undefined}
				<div class="models-vram-sub">free: {vram.free} MB</div>
			{/if}
		{:else}
			<div class="models-vram-sub">loading VRAM…</div>
		{/if}
	</div>
</div>

{#if error || actionError}
	<div class="alert alert-error" role="status">
		<div>
			<div class="alert-title">Something went wrong</div>
			<div class="alert-body">{error || actionError}</div>
		</div>
	</div>
{/if}

{#if loading && !inventory}
	<p class="page-title-muted">Scanning models…</p>
{:else if error}
	<p class="page-title-muted">Unable to load models inventory.</p>
{:else if inventory && inventory.models && inventory.models.length > 0}
	<section aria-label="Models inventory" class="models-panel">
		<div class="models-panel-scroll">
			<div class="models-table">
				<div class="models-header">
					<div>Model</div>
					<div>Variants</div>
					<div>Status</div>
					<div>Voice / Config</div>
					<div class="models-actions-col">Actions</div>
					<div>Smoke</div>
				</div>

				{#each inventory.models as model}
					<div class="models-row">
						<div class="models-cell models-cell-main">
							<div class="models-id">{model.id}</div>
							{#if model.root || model.path}
								<div class="models-path">
									{#if model.root}
										<span>{model.root}</span>
									{/if}
									{#if model.root && model.path}
										<span> · </span>
									{/if}
									{#if model.path}
										<span>{model.path}</span>
									{/if}
								</div>
							{/if}
						</div>

						<div class="models-cell models-cell-variants">
							{#if model.variants && model.variants.length > 0}
								<div class="models-variants-summary">
									{model.variants.length} variant{model.variants.length === 1 ? '' : 's'}
								</div>
								<div class="models-variants-chips">
									{#each model.variants as variant}
										<button
											type="button"
											class={`models-variant-chip ${
												selectedVariant[model.id] === variant.id ? 'models-variant-chip-active' : ''
											}`}
											title={`${variant.artifacts.length} artifact${
												variant.artifacts.length === 1 ? '' : 's'
											}`}
											on:click={() => (selectedVariant[model.id] = variant.id)}
										>
											<span class="models-variant-name">{variant.id}</span>
										</button>
									{/each}
								</div>
							{:else}
								<span class="models-empty-cell">—</span>
							{/if}
						</div>

						<div class="models-cell">
							<span
								class={`badge ${
									model.loaded
										? 'badge-loaded'
										: model.missing
											? 'badge-missing'
											: 'badge-ok'
								}`}
							>
								{model.loaded ? 'Loaded' : model.missing ? 'Missing' : 'Ready'}
							</span>
							{#if model.missing}
								<div class="models-status-hint">Folder or ONNX files not found.</div>
							{/if}
						</div>

						<div class="models-cell models-cell-selects">
							{#if !model.missing}
								{#if optionsById[model.id]?.voices && optionsById[model.id].voices.length > 0}
									<select
										class="field-select"
										on:change={(e) =>
											setActive(model.id, {
												voice: (e.currentTarget as HTMLSelectElement).value
											})
										}
										aria-label={`Select voice for ${model.id}`}
									>
										<option value="">voice</option>
										{#each optionsById[model.id].voices as voice}
											<option value={voice}>{voice}</option>
										{/each}
									</select>
								{/if}

								{#if optionsById[model.id]?.configs && optionsById[model.id].configs.length > 0}
									<select
										class="field-select"
										on:change={(e) =>
											setActive(model.id, {
												config: (e.currentTarget as HTMLSelectElement).value
											})
										}
										aria-label={`Select config for ${model.id}`}
									>
										<option value="">config</option>
										{#each optionsById[model.id].configs as config}
											<option value={config}>{config}</option>
										{/each}
									</select>
								{/if}
							{:else}
								<span class="models-empty-cell">Unavailable</span>
							{/if}
						</div>

						<div class="models-cell models-cell-actions">
							{#if !model.missing}
								{#if model.loaded}
									<button class="btn" on:click={() => unloadModel(model.id)}>Unload</button>
									<button class="btn btn-primary" on:click={() => smokeTest(model.id)}>Smoke</button>
								{:else}
									<button class="btn btn-primary" on:click={() => loadModel(model.id)}>Load</button>
								{/if}
							{/if}
						</div>

						<div class="models-cell models-cell-smoke">
							{#if smokeById[model.id]}
								<span
									class={`badge ${
										smokeById[model.id].status === 'ok' ? 'badge-soft' : 'badge-error'
									}`}
								>
									{smokeById[model.id].status === 'ok' ? 'OK' : 'Error'}
									{#if smokeById[model.id].runtime_ms !== undefined}
										<span class="models-variant-meta">
											{smokeById[model.id].runtime_ms}ms
										</span>
									{/if}
								</span>

								{#if smokeById[model.id].status === 'error' && smokeById[model.id].error}
									<div class="models-smoke-error">
										{smokeById[model.id].error}
									</div>
								{/if}
							{:else}
								<span class="models-empty-icon" aria-hidden="true"></span>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		</div>
	</section>
{:else if inventory}
	<p class="page-title-muted">Inventory loaded but no models field found.</p>
{:else}
	<p class="page-title-muted">No models found.</p>
{/if}

<style>
	.models-panel {
		margin-top: var(--space-3);
	}

	.models-panel-scroll {
		width: 100%;
		overflow-x: auto;
	}

	.models-table {
		min-width: 720px;
		border-radius: var(--radius-md);
		border: 1px solid var(--border-subtle);
		background: radial-gradient(circle at top left, rgba(37, 99, 235, 0.08), transparent 55%),
			radial-gradient(circle at bottom right, rgba(16, 185, 129, 0.06), transparent 60%),
			var(--bg-surface);
	}

	.models-header,
	.models-row {
		display: grid;
		grid-template-columns: 2.2fr 1.6fr 1fr 2fr 1.5fr 1.4fr;
		align-items: center;
		column-gap: 0.85rem;
	}

	.models-header {
		padding: 0.5rem 0.9rem;
		font-size: 0.78rem;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--text-muted);
		border-bottom: 1px solid var(--border-subtle);
		background: radial-gradient(circle at top left, rgba(59, 130, 246, 0.22), rgba(30, 64, 175, 0.9));
		box-shadow: 0 0 0 1px rgba(15, 23, 42, 0.8), 0 10px 26px rgba(15, 23, 42, 0.9);
		position: sticky;
		top: 0;
		z-index: 1;
	}

	.models-row {
		padding: 0.55rem 0.9rem;
		font-size: 0.86rem;
		border-top: 1px solid rgba(15, 23, 42, 0.9);
	}

	.models-row:nth-child(even) {
		background: rgba(15, 23, 42, 0.6);
	}

	.models-row:nth-child(odd) {
		background: rgba(15, 23, 42, 0.4);
	}

	.models-cell {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		min-width: 0;
	}

	.models-cell-main {
		gap: 0.2rem;
	}

	.models-id {
		font-weight: 500;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.models-path {
		font-size: 0.78rem;
		color: var(--text-muted);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.models-variants-summary {
		font-size: 0.8rem;
		color: var(--text-muted);
		margin-bottom: 0.1rem;
	}

	.models-cell-variants {
		overflow: hidden;
	}

	.models-variants-chips {
		display: flex;
		flex-wrap: wrap;
		gap: 0.25rem;
		max-width: 100%;
	}

	.models-variant-chip {
		border-radius: 999px;
		border: 1px solid rgba(148, 163, 184, 0.45);
		background: rgba(15, 23, 42, 0.9);
		color: var(--text-primary);
		padding: 0.16rem 0.7rem;
		font-size: 0.78rem;
		display: inline-flex;
		align-items: center;
		max-width: 100%;
		cursor: pointer;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.models-variant-chip-active {
		border-color: rgba(59, 130, 246, 0.95);
		background: radial-gradient(circle at top left, rgba(59, 130, 246, 0.4), rgba(37, 99, 235, 0.9));
		box-shadow: 0 0 0 1px rgba(15, 23, 42, 0.9), 0 4px 10px rgba(15, 23, 42, 0.85);
	}

	.models-variant-chip:focus-visible {
		outline: 2px solid rgba(59, 130, 246, 0.95);
		outline-offset: 1px;
	}

	.models-variant-name {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.models-variant-meta {
		font-size: 0.72rem;
		color: var(--text-muted);
	}

	.models-cell-selects {
		flex-direction: row;
		flex-wrap: wrap;
		gap: 0.3rem;
	}

	.models-actions-col {
		text-align: right;
	}

	.models-cell-actions {
		flex-direction: row;
		justify-content: flex-end;
		flex-wrap: wrap;
		gap: 0.3rem;
	}

	.models-cell-smoke {
		align-items: flex-start;
	}

	.models-smoke-error {
		margin-top: 0.15rem;
		font-size: 0.78rem;
		color: var(--danger);
	}

	.models-empty-icon {
		display: inline-block;
		width: 6px;
		height: 6px;
		border-radius: 999px;
		background: rgba(148, 163, 184, 0.35);
	}

	.models-empty-cell {
		color: var(--text-muted);
		font-size: 0.8rem;
	}

	.models-status-hint {
		margin-top: 0.15rem;
		font-size: 0.78rem;
		color: var(--text-muted);
	}

	.field-select {
		min-width: 110px;
		max-width: 170px;
		padding: 0.25rem 0.55rem;
		border-radius: var(--radius-sm);
		border: 1px solid var(--border-subtle);
		background: var(--bg-surface-alt);
		color: var(--text-primary);
		font-size: 0.8rem;
		outline: none;
	}

	.field-select:focus-visible {
		border-color: rgba(59, 130, 246, 0.9);
		box-shadow: 0 0 0 1px rgba(37, 99, 235, 0.9);
	}

	.models-vram-card {
		min-width: 220px;
		padding: 0.55rem 0.85rem;
		border-radius: var(--radius-md);
		border: 1px solid var(--border-subtle);
		background: linear-gradient(145deg, rgba(15, 23, 42, 0.98), rgba(15, 23, 42, 0.9));
		box-shadow: 0 8px 18px rgba(15, 23, 42, 0.85);
		text-align: right;
	}

	.models-vram-label {
		font-size: 0.78rem;
		text-transform: uppercase;
		letter-spacing: 0.12em;
		color: var(--text-muted);
		margin-bottom: 0.2rem;
	}

	.models-vram-main {
		display: flex;
		justify-content: flex-end;
		align-items: baseline;
		gap: 0.25rem;
	}

	.models-vram-value {
		font-size: 1.1rem;
		font-weight: 600;
	}

	.models-vram-separator {
		color: var(--text-muted);
		font-size: 0.9rem;
	}

	.models-vram-total {
		font-size: 0.86rem;
		color: var(--text-muted);
	}

	.models-vram-sub {
		margin-top: 0.1rem;
		font-size: 0.78rem;
		color: var(--text-muted);
	}

	.models-vram-error {
		font-size: 0.8rem;
		color: var(--danger);
	}

	@media (max-width: 900px) {
		.models-header,
		.models-row {
			grid-template-columns: 2.2fr 1.8fr 1fr 2.1fr 1.7fr 1.5fr;
		}
	}

	@media (max-width: 640px) {
		.models-vram-card {
			min-width: 0;
			width: 100%;
		}
	}
</style>
