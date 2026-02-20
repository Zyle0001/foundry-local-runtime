<script lang="ts">
	import { onDestroy, onMount } from 'svelte';

	const API_BASE = 'http://127.0.0.1:8000';
	const AUTO_REFRESH_MS = 5000;
	const HISTORY_LIMIT = 30;

	type DeviceStatus = {
		vendor?: string;
		vram_used_mb?: number;
		vram_total_mb?: number;
		vram_free_mb?: number;
		gpu_load_percent?: number;
		error?: string;
	};

	type DeviceSample = {
		timestamp: Date;
		vramPct: number | null;
		gpuLoadPct: number | null;
		vramUsedMb: number | null;
	};

	let status: DeviceStatus | null = null;
	let loading = true;
	let refreshing = false;
	let error: string | null = null;
	let lastUpdated: Date | null = null;
	let refreshCountdownSec = AUTO_REFRESH_MS / 1000;
	let samples: DeviceSample[] = [];

	let refreshTimer: ReturnType<typeof setInterval> | null = null;
	let countdownTimer: ReturnType<typeof setInterval> | null = null;

	function isNumber(value: unknown): value is number {
		return typeof value === 'number' && Number.isFinite(value);
	}

	function clampPercent(value: number): number {
		return Math.min(100, Math.max(0, value));
	}

	function formatTime(value: Date | null): string {
		if (!value) return '--';
		return value.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
	}

	function formatPercent(value: number | null): string {
		return value === null ? '--' : `${value.toFixed(1)}%`;
	}

	function formatDelta(value: number | null, suffix: string): string {
		if (value === null) return 'n/a';
		const sign = value > 0 ? '+' : '';
		return `${sign}${value.toFixed(1)}${suffix}`;
	}

	function sparklinePoints(values: number[]): string {
		if (values.length === 0) return '';
		const width = 220;
		const height = 56;
		const pad = 5;

		if (values.length === 1) {
			const y = height - pad - ((values[0] / 100) * (height - pad * 2));
			return `${width / 2},${y} ${width / 2},${y}`;
		}

		const step = (width - pad * 2) / (values.length - 1);
		return values
			.map((v, i) => {
				const x = pad + i * step;
				const y = height - pad - ((v / 100) * (height - pad * 2));
				return `${x},${y}`;
			})
			.join(' ');
	}

	function pushSample(data: DeviceStatus): void {
		const hasVramUsed = isNumber(data.vram_used_mb);
		const hasVramTotal = isNumber(data.vram_total_mb) && data.vram_total_mb > 0;
		const vramUsedMb: number | null = hasVramUsed ? Number(data.vram_used_mb) : null;
		let vramPct: number | null = null;
		if (vramUsedMb !== null && hasVramTotal) {
			const vramTotalMb = Number(data.vram_total_mb);
			vramPct = clampPercent((vramUsedMb / vramTotalMb) * 100);
		}

		const gpuLoadPct = isNumber(data.gpu_load_percent) ? clampPercent(data.gpu_load_percent) : null;

		if (vramPct === null && gpuLoadPct === null) {
			return;
		}

		samples = [
			...samples,
			{
				timestamp: new Date(),
				vramPct,
				gpuLoadPct,
				vramUsedMb
			}
		].slice(-HISTORY_LIMIT);
	}

	async function fetchStatus(background = false): Promise<void> {
		if (background) {
			refreshing = true;
		}

		try {
			const res = await fetch(`${API_BASE}/status`);
			if (!res.ok) {
				throw new Error(`HTTP ${res.status}`);
			}

			const nextStatus: DeviceStatus = await res.json();
			status = nextStatus;
			lastUpdated = new Date();
			refreshCountdownSec = AUTO_REFRESH_MS / 1000;
			error = null;
			pushSample(nextStatus);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Unknown error';
		} finally {
			loading = false;
			refreshing = false;
		}
	}

	onMount(() => {
		fetchStatus();

		refreshTimer = setInterval(() => {
			fetchStatus(true);
		}, AUTO_REFRESH_MS);

		countdownTimer = setInterval(() => {
			refreshCountdownSec = refreshCountdownSec <= 1 ? AUTO_REFRESH_MS / 1000 : refreshCountdownSec - 1;
		}, 1000);
	});

	onDestroy(() => {
		if (refreshTimer) clearInterval(refreshTimer);
		if (countdownTimer) clearInterval(countdownTimer);
	});

	$: hasVram = isNumber(status?.vram_used_mb) && isNumber(status?.vram_total_mb) && status!.vram_total_mb > 0;
	$: hasGpuLoad = isNumber(status?.gpu_load_percent);

	$: vramPct = hasVram ? clampPercent((status!.vram_used_mb! / status!.vram_total_mb!) * 100) : null;
	$: gpuLoadPct = hasGpuLoad ? clampPercent(status!.gpu_load_percent!) : null;

	$: vramSeries = samples.map((s) => s.vramPct).filter((v): v is number => v !== null);
	$: gpuSeries = samples.map((s) => s.gpuLoadPct).filter((v): v is number => v !== null);

	$: vramTrend = vramSeries.length > 1 ? vramSeries[vramSeries.length - 1] - vramSeries[vramSeries.length - 2] : null;
	$: gpuTrend = gpuSeries.length > 1 ? gpuSeries[gpuSeries.length - 1] - gpuSeries[gpuSeries.length - 2] : null;

	$: recentSamples = [...samples].slice(-6).reverse();
	$: headroomGiB = hasVram && isNumber(status?.vram_free_mb) ? (status!.vram_free_mb! / 1024) : null;
	$: oneGiBSlots = hasVram && isNumber(status?.vram_free_mb) ? Math.floor(status!.vram_free_mb! / 1024) : null;

	$: healthState =
		status?.error || error
			? 'error'
			: vramPct !== null && vramPct >= 90
				? 'warning'
				: gpuLoadPct !== null && gpuLoadPct >= 95
					? 'warning'
					: 'ok';

	$: healthLabel = healthState === 'ok' ? 'Healthy' : healthState === 'warning' ? 'High Pressure' : 'Error';

	$: vramSparkline = sparklinePoints(vramSeries);
	$: gpuSparkline = sparklinePoints(gpuSeries);
</script>

<div class="page-title-row">
	<div>
		<h1>Devices</h1>
		<p class="page-title-muted">Live runtime telemetry with short-term trend context.</p>
	</div>

	<div class="devices-header-actions">
		<span class={`badge ${healthState === 'ok' ? 'badge-ok' : healthState === 'warning' ? 'badge-soft' : 'badge-error'}`}>
			{healthLabel}
		</span>
		<span class="badge badge-soft">Last update: {formatTime(lastUpdated)}</span>
		<span class="badge">Next poll: {refreshCountdownSec}s</span>
		<button class="btn btn-ghost" on:click={() => fetchStatus(true)} disabled={loading || refreshing}>
			{refreshing ? 'Refreshing...' : 'Refresh'}
		</button>
	</div>
</div>

{#if status?.error}
	<div class="alert alert-error" role="status">
		<div>
			<div class="alert-title">Runtime reported an error</div>
			<div class="alert-body">{status.error}</div>
		</div>
	</div>
{/if}

{#if error}
	<div class="alert alert-error" role="status">
		<div>
			<div class="alert-title">Unable to reach host service</div>
			<div class="alert-body">{error}</div>
		</div>
	</div>
{/if}

{#if loading && !status}
	<section class="devices-surface">
		<p class="page-title-muted">Loading device status...</p>
	</section>
{:else if status}
	<section class="devices-grid" aria-label="Device status overview">
		<article class="device-card card-span-2">
			<div class="device-card-label">Adapter</div>
			<div class="device-card-value">{status.vendor || 'Unknown'}</div>
			<div class="device-inline-stats">
				<div>
					<span class="stat-k">Samples</span>
					<span class="stat-v">{samples.length}</span>
				</div>
				<div>
					<span class="stat-k">Headroom</span>
					<span class="stat-v">{headroomGiB === null ? '--' : `${headroomGiB.toFixed(2)} GiB`}</span>
				</div>
				<div>
					<span class="stat-k">Est. 1GiB Slots</span>
					<span class="stat-v">{oneGiBSlots === null ? '--' : oneGiBSlots}</span>
				</div>
			</div>
		</article>

		<article class="device-card">
			<div class="device-card-label">VRAM Usage</div>
			{#if hasVram}
				<div class="device-card-value">{status.vram_used_mb} / {status.vram_total_mb} MB</div>
				<div class="device-card-sub">
					Utilization: {formatPercent(vramPct)} ({formatDelta(vramTrend, '%')} last sample)
				</div>
				<div class="meter" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow={vramPct ?? 0}>
					<span
						class="meter-fill"
						class:meter-fill-warn={vramPct !== null && vramPct >= 80}
						class:meter-fill-danger={vramPct !== null && vramPct >= 92}
						style={`width: ${vramPct ?? 0}%`}
					></span>
				</div>

				<div class="sparkline-wrap" aria-hidden="true">
					<svg viewBox="0 0 220 56" class="sparkline">
						<polyline points="5,51 215,51" class="sparkline-grid" />
						<polyline points="5,28 215,28" class="sparkline-grid" />
						<polyline points="5,5 215,5" class="sparkline-grid" />
						<polyline points={vramSparkline} class="sparkline-line sparkline-line-vram" />
					</svg>
				</div>
			{:else}
				<div class="device-card-value">Unavailable</div>
				<div class="device-card-sub">Runtime did not return VRAM metrics.</div>
			{/if}
		</article>

		<article class="device-card">
			<div class="device-card-label">GPU Load</div>
			{#if hasGpuLoad}
				<div class="device-card-value">{status.gpu_load_percent}%</div>
				<div class="device-card-sub">
					Load trend: {formatDelta(gpuTrend, '%')} last sample
				</div>
				<div class="meter" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow={gpuLoadPct ?? 0}>
					<span
						class="meter-fill meter-fill-load"
						class:meter-fill-warn={gpuLoadPct !== null && gpuLoadPct >= 85}
						class:meter-fill-danger={gpuLoadPct !== null && gpuLoadPct >= 95}
						style={`width: ${gpuLoadPct ?? 0}%`}
					></span>
				</div>

				<div class="sparkline-wrap" aria-hidden="true">
					<svg viewBox="0 0 220 56" class="sparkline">
						<polyline points="5,51 215,51" class="sparkline-grid" />
						<polyline points="5,28 215,28" class="sparkline-grid" />
						<polyline points="5,5 215,5" class="sparkline-grid" />
						<polyline points={gpuSparkline} class="sparkline-line sparkline-line-load" />
					</svg>
				</div>
			{:else}
				<div class="device-card-value">Unavailable</div>
				<div class="device-card-sub">Runtime did not return utilization metrics.</div>
			{/if}
		</article>

		<article class="device-card card-span-2">
			<div class="device-card-label">Recent Samples</div>
			{#if recentSamples.length > 0}
				<div class="sample-table" role="table" aria-label="Recent telemetry samples">
					<div class="sample-row sample-head" role="row">
						<div role="columnheader">Time</div>
						<div role="columnheader">VRAM</div>
						<div role="columnheader">VRAM %</div>
						<div role="columnheader">GPU %</div>
					</div>
					{#each recentSamples as sample}
						<div class="sample-row" role="row">
							<div role="cell">{formatTime(sample.timestamp)}</div>
							<div role="cell">{sample.vramUsedMb === null ? '--' : `${sample.vramUsedMb} MB`}</div>
							<div role="cell">{formatPercent(sample.vramPct)}</div>
							<div role="cell">{formatPercent(sample.gpuLoadPct)}</div>
						</div>
					{/each}
				</div>
			{:else}
				<div class="device-card-sub">No sample history yet.</div>
			{/if}
		</article>
	</section>
{/if}

<style>
	.devices-header-actions {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 0.45rem;
	}

	.devices-surface {
		padding: 1rem;
		border-radius: var(--radius-md);
		border: 1px solid var(--border-subtle);
		background: var(--bg-surface);
	}

	.devices-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: var(--space-3);
	}

	.device-card {
		padding: 1rem;
		border-radius: var(--radius-md);
		border: 1px solid var(--border-subtle);
		background: radial-gradient(circle at top left, rgba(56, 189, 248, 0.1), transparent 55%),
			linear-gradient(165deg, rgba(15, 23, 42, 0.96), rgba(15, 23, 42, 0.84));
		box-shadow: 0 10px 22px rgba(15, 23, 42, 0.6);
		display: flex;
		flex-direction: column;
		gap: 0.45rem;
		min-height: 160px;
	}

	.card-span-2 {
		grid-column: span 2;
	}

	.device-card-label {
		font-size: 0.74rem;
		text-transform: uppercase;
		letter-spacing: 0.11em;
		color: var(--text-muted);
	}

	.device-card-value {
		font-size: 1.1rem;
		font-weight: 600;
		color: var(--text-primary);
	}

	.device-card-sub {
		font-size: 0.82rem;
		color: var(--text-muted);
	}

	.device-inline-stats {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 0.5rem;
		margin-top: 0.15rem;
	}

	.device-inline-stats > div {
		padding: 0.5rem 0.55rem;
		border: 1px solid rgba(148, 163, 184, 0.28);
		border-radius: 0.45rem;
		background: rgba(15, 23, 42, 0.52);
		display: flex;
		flex-direction: column;
		gap: 0.2rem;
	}

	.stat-k {
		font-size: 0.72rem;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.07em;
	}

	.stat-v {
		font-size: 0.93rem;
		color: var(--text-primary);
		font-weight: 600;
	}

	.meter {
		height: 0.52rem;
		border-radius: 999px;
		background: rgba(148, 163, 184, 0.2);
		overflow: hidden;
		border: 1px solid rgba(148, 163, 184, 0.35);
	}

	.meter-fill {
		display: block;
		height: 100%;
		background: linear-gradient(90deg, #34d399, #10b981);
		box-shadow: 0 0 10px rgba(16, 185, 129, 0.45);
	}

	.meter-fill-load {
		background: linear-gradient(90deg, #38bdf8, #3b82f6);
		box-shadow: 0 0 10px rgba(56, 189, 248, 0.45);
	}

	.meter-fill-warn {
		background: linear-gradient(90deg, #f59e0b, #f97316);
		box-shadow: 0 0 10px rgba(249, 115, 22, 0.45);
	}

	.meter-fill-danger {
		background: linear-gradient(90deg, #ef4444, #dc2626);
		box-shadow: 0 0 10px rgba(239, 68, 68, 0.5);
	}

	.sparkline-wrap {
		margin-top: 0.2rem;
		padding: 0.2rem 0.35rem;
		border-radius: 0.5rem;
		border: 1px solid rgba(148, 163, 184, 0.2);
		background: rgba(2, 6, 23, 0.55);
	}

	.sparkline {
		width: 100%;
		height: 58px;
		display: block;
	}

	.sparkline-grid {
		fill: none;
		stroke: rgba(148, 163, 184, 0.25);
		stroke-width: 1;
	}

	.sparkline-line {
		fill: none;
		stroke-width: 2.2;
		stroke-linecap: round;
		stroke-linejoin: round;
	}

	.sparkline-line-vram {
		stroke: #10b981;
	}

	.sparkline-line-load {
		stroke: #38bdf8;
	}

	.sample-table {
		display: flex;
		flex-direction: column;
		border: 1px solid rgba(148, 163, 184, 0.24);
		border-radius: 0.55rem;
		overflow: hidden;
		margin-top: 0.2rem;
	}

	.sample-row {
		display: grid;
		grid-template-columns: 1.1fr 1fr 0.8fr 0.8fr;
		gap: 0.45rem;
		padding: 0.42rem 0.6rem;
		font-size: 0.81rem;
		border-top: 1px solid rgba(148, 163, 184, 0.18);
	}

	.sample-row:first-child {
		border-top: none;
	}

	.sample-row:nth-child(even) {
		background: rgba(15, 23, 42, 0.5);
	}

	.sample-row:nth-child(odd) {
		background: rgba(15, 23, 42, 0.38);
	}

	.sample-head {
		font-size: 0.72rem;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--text-muted);
		background: rgba(30, 41, 59, 0.92);
	}

	@media (max-width: 900px) {
		.card-span-2 {
			grid-column: span 1;
		}

		.device-inline-stats {
			grid-template-columns: 1fr;
		}
	}

	@media (max-width: 640px) {
		.devices-grid {
			grid-template-columns: 1fr;
		}

		.sample-row {
			grid-template-columns: 1fr 1fr;
		}

		.sample-head {
			display: none;
		}
	}
</style>
