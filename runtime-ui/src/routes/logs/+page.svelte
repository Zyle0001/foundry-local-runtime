<script lang="ts">
	import { onDestroy, onMount } from 'svelte';

	const API_BASE = 'http://127.0.0.1:8000';
	const AUTO_REFRESH_MS = 2000;

	type LogEntry = {
		timestamp: string;
		level: string;
		logger: string;
		subsystem?: string;
		message: string;
		exception?: string;
	};

	let logs: LogEntry[] = [];
	let loading = true;
	let refreshing = false;
	let error: string | null = null;
	let lastUpdated: Date | null = null;
	let refreshCountdownSec = AUTO_REFRESH_MS / 1000;
	let autoRefresh = true;
	let minLevel = '';
	let includeAccess = false;
	let search = '';
	let limit = 300;

	let refreshTimer: ReturnType<typeof setInterval> | null = null;
	let countdownTimer: ReturnType<typeof setInterval> | null = null;

	function formatTime(isoTimestamp: string): string {
		const value = new Date(isoTimestamp);
		if (Number.isNaN(value.getTime())) return isoTimestamp;
		return value.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
	}

	function formatLastUpdated(value: Date | null): string {
		if (!value) return '--';
		return value.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
	}

	function levelClass(level: string): string {
		const upper = level.toUpperCase();
		if (upper === 'ERROR' || upper === 'CRITICAL') return 'log-level-error';
		if (upper === 'WARNING') return 'log-level-warn';
		if (upper === 'DEBUG') return 'log-level-debug';
		return 'log-level-info';
	}

	function matchesSearch(entry: LogEntry, query: string): boolean {
		if (!query) return true;
		const q = query.toLowerCase();
		return (
			entry.message.toLowerCase().includes(q) ||
			entry.logger.toLowerCase().includes(q) ||
			(entry.subsystem || '').toLowerCase().includes(q) ||
			entry.level.toLowerCase().includes(q) ||
			(entry.exception || '').toLowerCase().includes(q)
		);
	}

	async function fetchLogs(background = false): Promise<void> {
		if (background) refreshing = true;

		try {
			const params = new URLSearchParams({
				limit: String(limit)
			});
			if (minLevel) params.set('level', minLevel);
			if (includeAccess) params.set('include_access', 'true');

			const res = await fetch(`${API_BASE}/logs?${params.toString()}`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);

			const data = await res.json();
			logs = Array.isArray(data.logs) ? data.logs : [];
			lastUpdated = new Date();
			refreshCountdownSec = AUTO_REFRESH_MS / 1000;
			error = null;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Unknown error';
		} finally {
			loading = false;
			refreshing = false;
		}
	}

	async function clearLogs(): Promise<void> {
		try {
			const res = await fetch(`${API_BASE}/logs/clear`, { method: 'POST' });
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			await fetchLogs();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Unknown error';
		}
	}

	function toggleAutoRefresh(): void {
		autoRefresh = !autoRefresh;
		refreshCountdownSec = AUTO_REFRESH_MS / 1000;
	}

	onMount(() => {
		fetchLogs();

		refreshTimer = setInterval(() => {
			if (autoRefresh) fetchLogs(true);
		}, AUTO_REFRESH_MS);

		countdownTimer = setInterval(() => {
			if (!autoRefresh) return;
			refreshCountdownSec = refreshCountdownSec <= 1 ? AUTO_REFRESH_MS / 1000 : refreshCountdownSec - 1;
		}, 1000);
	});

	onDestroy(() => {
		if (refreshTimer) clearInterval(refreshTimer);
		if (countdownTimer) clearInterval(countdownTimer);
	});

	$: visibleLogs = logs.filter((entry) => matchesSearch(entry, search));
</script>

<div class="page-title-row">
	<div>
		<h1>Logs</h1>
		<p class="page-title-muted">Live host/runtime logs for debugging and observability.</p>
	</div>

	<div class="logs-header-actions">
		<span class="badge badge-soft">Last update: {formatLastUpdated(lastUpdated)}</span>
		<span class="badge">{autoRefresh ? `Next poll: ${refreshCountdownSec}s` : 'Auto refresh paused'}</span>
	</div>
</div>

<section class="logs-controls">
	<div class="logs-controls-left">
		<label class="control-label">
			Level
			<select bind:value={minLevel} class="field-select" on:change={() => fetchLogs()}>
				<option value="">All</option>
				<option value="DEBUG">DEBUG+</option>
				<option value="INFO">INFO+</option>
				<option value="WARNING">WARNING+</option>
				<option value="ERROR">ERROR+</option>
			</select>
		</label>

		<label class="control-label">
			Rows
			<select bind:value={limit} class="field-select" on:change={() => fetchLogs()}>
				<option value={100}>100</option>
				<option value={300}>300</option>
				<option value={500}>500</option>
				<option value={1000}>1000</option>
			</select>
		</label>

		<label class="control-label search-label">
			Search
			<input
				type="text"
				bind:value={search}
				placeholder="message, subsystem, logger, exception..."
				class="field-input"
			/>
		</label>

		<div class="control-label control-toggle">
			<span>Access Logs</span>
			<label class="toggle">
				<input type="checkbox" bind:checked={includeAccess} on:change={() => fetchLogs()} />
				<span>{includeAccess ? 'Shown' : 'Hidden'}</span>
			</label>
		</div>
	</div>

	<div class="logs-controls-right">
		<button class="btn btn-ghost" on:click={() => fetchLogs(true)} disabled={loading || refreshing}>
			{refreshing ? 'Refreshing...' : 'Refresh now'}
		</button>
		<button class="btn" on:click={toggleAutoRefresh}>
			{autoRefresh ? 'Pause refresh' : 'Resume refresh'}
		</button>
		<button class="btn" on:click={clearLogs}>Clear</button>
	</div>
</section>

{#if error}
	<div class="alert alert-error" role="status">
		<div>
			<div class="alert-title">Unable to fetch logs</div>
			<div class="alert-body">{error}</div>
		</div>
	</div>
{/if}

<section class="logs-surface" aria-label="Runtime logs">
	{#if loading && logs.length === 0}
		<p class="page-title-muted">Loading logs...</p>
	{:else if visibleLogs.length === 0}
		<p class="page-title-muted">No logs matched the current filters.</p>
	{:else}
		<div class="logs-list">
			{#each [...visibleLogs].reverse() as entry, index (`${entry.timestamp}-${entry.logger}-${index}`)}
				<article class="log-entry">
					<div class="log-meta">
						<span class="log-time">{formatTime(entry.timestamp)}</span>
						<span class={`badge ${levelClass(entry.level)}`}>{entry.level}</span>
						<span class="badge log-subsystem">{entry.subsystem || 'unknown'}</span>
						<span class="log-logger">{entry.logger}</span>
					</div>
					<div class="log-message">{entry.message}</div>
					{#if entry.exception}
						<pre class="log-exception">{entry.exception}</pre>
					{/if}
				</article>
			{/each}
		</div>
	{/if}
</section>

<style>
	.logs-header-actions {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 0.45rem;
	}

	.logs-controls {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		gap: 0.8rem;
		margin-bottom: var(--space-3);
		padding: 0.8rem;
		border-radius: var(--radius-md);
		border: 1px solid var(--border-subtle);
		background: rgba(15, 23, 42, 0.68);
	}

	.logs-controls-left {
		display: flex;
		flex-wrap: wrap;
		gap: 0.6rem;
		align-items: flex-end;
	}

	.logs-controls-right {
		display: flex;
		flex-wrap: wrap;
		gap: 0.45rem;
		align-items: center;
	}

	.control-label {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		font-size: 0.75rem;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}

	.control-toggle {
		text-transform: none;
		letter-spacing: normal;
	}

	.toggle {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		font-size: 0.82rem;
		color: var(--text-primary);
	}

	.toggle input {
		accent-color: #38bdf8;
	}

	.search-label {
		min-width: 260px;
	}

	.field-select,
	.field-input {
		padding: 0.35rem 0.55rem;
		border-radius: var(--radius-sm);
		border: 1px solid var(--border-subtle);
		background: var(--bg-surface-alt);
		color: var(--text-primary);
		font-size: 0.84rem;
	}

	.field-input {
		min-width: 260px;
	}

	.field-select:focus-visible,
	.field-input:focus-visible {
		outline: none;
		border-color: rgba(59, 130, 246, 0.9);
		box-shadow: 0 0 0 1px rgba(37, 99, 235, 0.9);
	}

	.logs-surface {
		border: 1px solid var(--border-subtle);
		border-radius: var(--radius-md);
		background: radial-gradient(circle at top left, rgba(59, 130, 246, 0.09), transparent 65%), #0a0f1c;
		padding: 0.75rem;
	}

	.logs-list {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		max-height: 66vh;
		overflow-y: auto;
		padding-right: 0.2rem;
	}

	.log-entry {
		border: 1px solid rgba(148, 163, 184, 0.25);
		border-radius: 0.5rem;
		background: rgba(2, 6, 23, 0.72);
		padding: 0.55rem 0.65rem;
	}

	.log-meta {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.45rem;
		font-size: 0.76rem;
		color: var(--text-muted);
		margin-bottom: 0.28rem;
	}

	.log-time {
		font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New',
			monospace;
	}

	.log-logger {
		color: #93c5fd;
		font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New',
			monospace;
	}

	.log-message {
		font-size: 0.86rem;
		color: var(--text-primary);
		white-space: pre-wrap;
		word-break: break-word;
	}

	.log-exception {
		margin-top: 0.45rem;
		border: 1px solid rgba(248, 113, 113, 0.45);
		background: rgba(69, 10, 10, 0.55);
		color: #fecaca;
		font-size: 0.76rem;
	}

	.log-level-info {
		background: rgba(59, 130, 246, 0.2);
		border-color: rgba(59, 130, 246, 0.7);
		color: #bfdbfe;
	}

	.log-level-debug {
		background: rgba(148, 163, 184, 0.16);
		border-color: rgba(148, 163, 184, 0.45);
		color: #cbd5e1;
	}

	.log-level-warn {
		background: rgba(245, 158, 11, 0.2);
		border-color: rgba(245, 158, 11, 0.7);
		color: #fcd34d;
	}

	.log-level-error {
		background: rgba(248, 113, 113, 0.2);
		border-color: rgba(248, 113, 113, 0.75);
		color: #fca5a5;
	}

	.log-subsystem {
		background: rgba(16, 185, 129, 0.16);
		border-color: rgba(16, 185, 129, 0.6);
		color: #a7f3d0;
	}

	@media (max-width: 900px) {
		.logs-controls {
			flex-direction: column;
		}

		.logs-controls-right {
			width: 100%;
		}
	}

	@media (max-width: 640px) {
		.search-label,
		.field-input {
			min-width: 0;
			width: 100%;
		}

		.logs-controls-left {
			width: 100%;
		}

		.logs-controls-right {
			justify-content: flex-start;
		}
	}
</style>
