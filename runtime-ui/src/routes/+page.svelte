<script lang="ts">
	import { onDestroy, onMount } from 'svelte';

	const API_BASE = 'http://127.0.0.1:8000';
	const REFRESH_MS = 10000;

	type ModelEntry = {
		id?: string;
		loaded?: boolean;
		missing?: boolean;
	};

	type ModelsResponse = {
		models?: ModelEntry[];
	};

	type StatusResponse = {
		vendor?: string;
		vram_used_mb?: number;
		vram_total_mb?: number;
		vram_free_mb?: number;
		error?: string;
		features?: {
			audio_module_enabled?: boolean;
		};
	};

	let loading = true;
	let error: string | null = null;
	let modelStats = { total: 0, loaded: 0, missing: 0 };
	let deviceStatus: StatusResponse | null = null;
	let recentErrorCount: number | null = null;
	let audioEnabled = false;
	let lastModelActivityAt: Date | null = null;
	let previousLoadedSignature: string | null = null;
	let refreshTimer: ReturnType<typeof setInterval> | null = null;
	let audioFeatureListener: ((event: Event) => void) | null = null;

	function isNumber(value: unknown): value is number {
		return typeof value === 'number' && Number.isFinite(value);
	}

	function formatRelativeTime(value: Date): string {
		const seconds = Math.max(0, Math.floor((Date.now() - value.getTime()) / 1000));
		if (seconds < 60) return 'just now';
		const minutes = Math.floor(seconds / 60);
		if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`;
		const hours = Math.floor(minutes / 60);
		if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`;
		const days = Math.floor(hours / 24);
		return `${days} day${days === 1 ? '' : 's'} ago`;
	}

	async function fetchSnapshot(): Promise<void> {
		try {
			const [modelsRes, statusRes] = await Promise.all([
				fetch(`${API_BASE}/models`),
				fetch(`${API_BASE}/status`)
			]);

			if (!modelsRes.ok) throw new Error(`/models HTTP ${modelsRes.status}`);
			if (!statusRes.ok) throw new Error(`/status HTTP ${statusRes.status}`);

			const modelsData: ModelsResponse = await modelsRes.json();
			const statusData: StatusResponse = await statusRes.json();

			const models = Array.isArray(modelsData.models) ? modelsData.models : [];
			const loadedIds = models
				.map((m, index) => (m.loaded ? (m.id ?? `index-${index}`) : null))
				.filter((id): id is string => Boolean(id))
				.sort();
			const loadedSignature = loadedIds.join('|');
			if (previousLoadedSignature !== null && previousLoadedSignature !== loadedSignature) {
				lastModelActivityAt = new Date();
			}
			if (previousLoadedSignature === null && loadedIds.length > 0) {
				lastModelActivityAt = new Date();
			}
			previousLoadedSignature = loadedSignature;

			modelStats = {
				total: models.length,
				loaded: models.filter((m) => m.loaded).length,
				missing: models.filter((m) => m.missing).length
			};
			deviceStatus = statusData;
			audioEnabled = Boolean(statusData.features?.audio_module_enabled);

			try {
				const logsRes = await fetch(`${API_BASE}/logs?limit=250&level=ERROR`);
				if (logsRes.ok) {
					const logsData = await logsRes.json();
					recentErrorCount = Array.isArray(logsData.logs) ? logsData.logs.length : null;
				} else {
					recentErrorCount = null;
				}
			} catch {
				recentErrorCount = null;
			}

			error = null;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Unknown error';
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		fetchSnapshot();
		refreshTimer = setInterval(fetchSnapshot, REFRESH_MS);
		audioFeatureListener = (event: Event) => {
			const custom = event as CustomEvent<{ enabled?: boolean }>;
			audioEnabled = Boolean(custom.detail?.enabled);
		};
		window.addEventListener('audio-feature-changed', audioFeatureListener as EventListener);
	});

	onDestroy(() => {
		if (refreshTimer) clearInterval(refreshTimer);
		if (audioFeatureListener) {
			window.removeEventListener('audio-feature-changed', audioFeatureListener as EventListener);
		}
	});

	$: hasVram =
		isNumber(deviceStatus?.vram_used_mb) &&
		isNumber(deviceStatus?.vram_total_mb) &&
		deviceStatus.vram_total_mb > 0;
	$: vramPct = hasVram ? (deviceStatus!.vram_used_mb! / deviceStatus!.vram_total_mb!) * 100 : null;
	$: lastModelActivityHint = lastModelActivityAt
		? `Last model activity: ${formatRelativeTime(lastModelActivityAt)}`
		: 'Last model activity: not observed yet';
</script>

<section class="home-hero">
	<header class="page-title-row home-hero-header">
		<div>
			<h1>Local AI Runtime</h1>
			<p class="page-title-muted">
				Host, load, and smoke-test models on your local GPU with a compact runtime dashboard.
			</p>
		</div>
		<div class="home-hero-pill badge badge-soft" aria-hidden="true">
			Local only | GPU aware
		</div>
	</header>

	<div class="home-hero-actions">
		<a href="/models" class="btn btn-primary">Manage models</a>
		<a href="/devices" class="btn btn-ghost">Check devices</a>
		<a href="/logs" class="btn btn-ghost">Open logs</a>
		{#if audioEnabled}
			<a href="/audio" class="btn btn-ghost">Audio dashboard</a>
		{/if}
	</div>

	{#if error}
		<div class="alert alert-error" role="status">
			<div>
				<div class="alert-title">Runtime snapshot unavailable</div>
				<div class="alert-body">{error}</div>
			</div>
		</div>
	{/if}

	<section class="home-snapshot" aria-label="Runtime snapshot">
		<div class="home-snapshot-head">
			<h2 class="home-snapshot-title">Runtime Snapshot</h2>
			<span class={`badge ${error || deviceStatus?.error ? 'badge-error' : 'badge-ok'}`}>
				{error || deviceStatus?.error ? 'Degraded' : loading ? 'Loading' : 'Online'}
			</span>
		</div>
		<div class="home-activity-hint">{lastModelActivityHint}</div>

		<div class="home-snapshot-grid">
			<a class="home-stat home-stat-link" href="/models">
				<div class="home-stat-label">Models</div>
				<div class="home-stat-value">{modelStats.loaded} / {modelStats.total}</div>
				{#if modelStats.loaded === 0}
					<div class="home-stat-sub home-stat-sub-empty">
						No models loaded yet -- start by loading one below.
					</div>
				{:else}
					<div class="home-stat-sub">{modelStats.loaded} loaded | {modelStats.missing} missing</div>
				{/if}
			</a>

			<a class="home-stat home-stat-link" href="/devices">
				<div class="home-stat-label">VRAM</div>
				{#if hasVram}
					<div class="home-stat-value">
						{deviceStatus?.vram_used_mb} / {deviceStatus?.vram_total_mb} MB
					</div>
					<div class="home-stat-sub">{vramPct?.toFixed(1)}% used</div>
				{:else}
					<div class="home-stat-value">Unavailable</div>
					<div class="home-stat-sub">no metrics</div>
				{/if}
			</a>

			<a class="home-stat home-stat-link" href="/logs">
				<div class="home-stat-label">Errors</div>
				<div class="home-stat-value">{recentErrorCount === null ? '--' : recentErrorCount}</div>
				<div class="home-stat-sub">recent ERROR+ entries</div>
			</a>

			<a class="home-stat home-stat-link" href="/devices">
				<div class="home-stat-label">Adapter</div>
				<div class="home-stat-value">{deviceStatus?.vendor || 'Unknown'}</div>
				<div class="home-stat-sub">from status endpoint</div>
			</a>
		</div>
	</section>

	<div class="home-hero-grid">
		<section class="home-card">
			<header class="home-card-header">
				<h2>Models</h2>
				<span class="badge">Load &amp; variants</span>
			</header>
			<p>
				Inspect available ONNX models, switch variants, and control which ones are currently loaded into
				VRAM.
			</p>
			<a href="/models" class="home-card-link">
				<span>Go to models</span>
				<span aria-hidden="true">-></span>
			</a>
		</section>

		<section class="home-card">
			<header class="home-card-header">
				<h2>Devices</h2>
				<span class="badge">VRAM &amp; status</span>
			</header>
			<p>
				See which devices are available, how much VRAM is in use, and whether the runtime can schedule
				additional models.
			</p>
			<a href="/devices" class="home-card-link">
				<span>View devices</span>
				<span aria-hidden="true">-></span>
			</a>
		</section>

		<section class="home-card">
			<header class="home-card-header">
				<h2>Logs</h2>
				<span class="badge">Diagnostics</span>
			</header>
			<p>Inspect runtime and API logs, filter noise, and triage failures without leaving the dashboard.</p>
			<a href="/logs" class="home-card-link">
				<span>Open logs</span>
				<span aria-hidden="true">-></span>
			</a>
		</section>

		{#if audioEnabled}
			<section class="home-card">
				<header class="home-card-header">
					<h2>Audio</h2>
					<span class="badge">Routing &amp; streams</span>
				</header>
				<p>Configure device defaults, route graphs, duplex policy, and stream transport controls.</p>
				<a href="/audio" class="home-card-link">
					<span>Open audio</span>
					<span aria-hidden="true">-></span>
				</a>
			</section>
		{/if}
	</div>
</section>

<style>
	.home-hero {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}

	.home-hero-header {
		align-items: flex-start;
	}

	.home-hero-pill {
		white-space: nowrap;
	}

	.home-hero-actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}

	.home-snapshot {
		background: linear-gradient(145deg, rgba(15, 23, 42, 0.95), rgba(15, 23, 42, 0.86));
		border-radius: var(--radius-md);
		border: 1px solid var(--border-subtle);
		padding: var(--space-4);
		box-shadow: 0 10px 24px rgba(15, 23, 42, 0.55);
	}

	.home-snapshot-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
		margin-bottom: var(--space-3);
	}

	.home-snapshot-head h2 {
		margin: 0;
		font-size: 1rem;
	}

	.home-snapshot-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
		gap: var(--space-3);
	}

	.home-activity-hint {
		font-size: 0.82rem;
		color: var(--text-muted);
		margin-bottom: var(--space-3);
	}

	.home-stat {
		border: 1px solid rgba(148, 163, 184, 0.3);
		border-radius: var(--radius-sm);
		background: linear-gradient(160deg, rgba(2, 6, 23, 0.78), rgba(15, 23, 42, 0.62));
		padding: 0.75rem 0.8rem;
		display: flex;
		flex-direction: column;
		gap: 0.22rem;
		min-width: 0;
		box-shadow: inset 0 0 0 1px rgba(15, 23, 42, 0.55);
	}

	.home-stat-link {
		color: inherit;
		text-decoration: none;
		transition: border-color 120ms ease, transform 120ms ease, box-shadow 120ms ease;
	}

	.home-stat-link:hover {
		border-color: rgba(56, 189, 248, 0.55);
		transform: translateY(-1px);
		box-shadow: inset 0 0 0 1px rgba(56, 189, 248, 0.35), 0 10px 18px rgba(2, 6, 23, 0.45);
	}

	.home-stat-label {
		font-size: 0.73rem;
		text-transform: uppercase;
		letter-spacing: 0.09em;
		color: var(--text-muted);
	}

	.home-stat-value {
		font-size: 1.02rem;
		font-weight: 600;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.home-stat-sub {
		font-size: 0.77rem;
		color: var(--text-muted);
	}

	.home-stat-sub-empty {
		color: #cbd5e1;
	}

	.home-hero-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
		gap: var(--space-4);
	}

	.home-card {
		background: var(--bg-surface);
		border-radius: var(--radius-md);
		border: 1px solid var(--border-subtle);
		padding: var(--space-4);
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		box-shadow: 0 12px 30px rgba(15, 23, 42, 0.55);
	}

	.home-card-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
	}

	.home-card h2 {
		margin: 0;
		font-size: 1rem;
	}

	.home-card p {
		margin: 0;
		color: var(--text-muted);
		font-size: 0.9rem;
	}

	.home-card-link {
		margin-top: auto;
		display: inline-flex;
		align-items: center;
		gap: 0.3rem;
		font-size: 0.85rem;
		color: var(--accent);
		text-decoration: none;
	}

	.home-card-link:hover {
		color: #a5c7ff;
	}

	@media (max-width: 768px) {
		.home-hero-grid {
			grid-template-columns: minmax(0, 1fr);
		}
	}
</style>
