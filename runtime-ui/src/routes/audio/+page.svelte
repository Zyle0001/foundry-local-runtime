<script lang="ts">
	import { onDestroy, onMount } from 'svelte';

	const API_BASE = 'http://127.0.0.1:8000';
	const METER_POLL_MS = 2000;

	type StatusResponse = {
		features?: {
			audio_module_enabled?: boolean;
		};
	};

	type AudioDevice = {
		id: string;
		name: string;
		channels?: number | null;
		sample_rate?: number | null;
	};

	type AudioDevicesResponse = {
		backend: string;
		input_devices: AudioDevice[];
		output_devices: AudioDevice[];
		default_input_device_id?: string | null;
		default_output_device_id?: string | null;
		error?: string | null;
		error_code?: string | null;
		hint?: string | null;
	};

	type AudioNode = {
		kind: string;
		name?: string | null;
		device_id?: string | null;
		config?: Record<string, unknown>;
	};

	type AudioRouteRecord = {
		route_id: string;
		name?: string | null;
		source: AudioNode;
		processors: AudioNode[];
		sink: AudioNode;
		enabled: boolean;
	};

	type AudioStreamRecord = {
		stream_id: string;
		route_id: string;
		direction: string;
		state: string;
		last_transition_utc?: string | null;
	};

	type AudioMeter = {
		stream_id: string;
		peak: number;
		rms: number;
		clipped: boolean;
		updated_at_utc?: string | null;
	};

	type AudioStateResponse = {
		audio_enabled: boolean;
		defaults: {
			default_input_device_id?: string | null;
			default_output_device_id?: string | null;
		};
		duplex_policy: string;
		push_to_talk: boolean;
		routes: AudioRouteRecord[];
		streams: AudioStreamRecord[];
		controls: AudioControlRecord[];
		meters: AudioMeter[];
		engine_running: boolean;
	};

	type AudioControlRecord = {
		stream_id: string;
		gain_db: number;
		muted: boolean;
	};

	type StreamAction = 'start' | 'pause' | 'stop';

	class ApiRequestError extends Error {
		status: number;

		constructor(status: number, message: string) {
			super(message);
			this.status = status;
			this.name = 'ApiRequestError';
		}
	}

	let loading = true;
	let refreshing = false;
	let statusChecked = false;
	let audioEnabled = false;
	let error: string | null = null;
	let conflictDetail: string | null = null;
	let conflictHint: string | null = null;
	let info: string | null = null;

	let devices: AudioDevicesResponse | null = null;
	let audioState: AudioStateResponse | null = null;
	let meters: AudioMeter[] = [];

	let selectedInputDeviceId = '';
	let selectedOutputDeviceId = '';

	let creatingRoute = false;
	let savingDefaults = false;
	let savingPolicy = false;
	let savingPushToTalk = false;
	let deletingRouteId: string | null = null;
	let togglingAudioModule = false;

	let editingRouteId: string | null = null;

	let selectedDuplexPolicy = 'allow_overlap';
	let selectedPushToTalk = false;

	let routeName = '';
	let sourceKind = 'mic';
	let sourceName = '';
	let sourceConfigRaw = '';
	let sinkKind = 'asr';
	let sinkName = '';
	let sinkConfigRaw = '';
	let processorKind = '';
	let processorName = '';
	let processorConfigRaw = '';

	let streamActionByRoute: Record<string, StreamAction | undefined> = {};
	let savingControlByRoute: Record<string, boolean> = {};
	let controlDraftByRoute: Record<string, { gain_db: string; muted: boolean }> = {};

	let meterPollTimer: ReturnType<typeof setInterval> | null = null;

	const sourceKinds = ['mic', 'loopback', 'file_input', 'test_tone', 'tts'];
	const sinkKinds = ['asr', 'speakers', 'file', 'virtual_output'];
	const processorKinds = ['', 'asr_ingress', 'tts_egress_formatter', 'resampler', 'passthrough'];
	const duplexPolicyModes = [
		'capture_gated_by_playback',
		'playback_gated_by_capture',
		'allow_overlap',
		'barge_in_enabled'
	];

	function parseOptionalConfig(raw: string): Record<string, unknown> {
		const trimmed = raw.trim();
		if (!trimmed) return {};
		const parsed = JSON.parse(trimmed);
		if (parsed === null || Array.isArray(parsed) || typeof parsed !== 'object') {
			throw new Error('Config JSON must be an object');
		}
		return parsed as Record<string, unknown>;
	}

	function nodeFromInputs(kind: string, name: string, configRaw: string): AudioNode {
		return {
			kind,
			name: name.trim() || null,
			config: parseOptionalConfig(configRaw)
		};
	}

	function configToRaw(config?: Record<string, unknown> | null): string {
		if (!config || Object.keys(config).length === 0) return '';
		return JSON.stringify(config, null, 2);
	}

	function resetRouteBuilder(): void {
		editingRouteId = null;
		routeName = '';
		sourceKind = 'mic';
		sourceName = '';
		sourceConfigRaw = '';
		sinkKind = 'asr';
		sinkName = '';
		sinkConfigRaw = '';
		processorKind = '';
		processorName = '';
		processorConfigRaw = '';
	}

	function getErrorMessageFromResponseBody(raw: string, status: number): string {
		if (!raw) return `HTTP ${status}`;
		try {
			const parsed = JSON.parse(raw) as { detail?: unknown; message?: unknown };
			if (typeof parsed.detail === 'string') return parsed.detail;
			if (typeof parsed.message === 'string') return parsed.message;
		} catch {
			// Keep raw if not JSON.
		}
		return raw;
	}

	function clearErrors(): void {
		error = null;
		conflictDetail = null;
		conflictHint = null;
	}

	function conflictHintFromDetail(detail: string): string {
		const normalized = detail.toLowerCase();
		if (normalized.includes('audio module disabled')) {
			return 'Enable the audio module, then retry the action.';
		}
		if (normalized.includes('capture_gated_by_playback')) {
			return 'Pause playback streams or switch duplex policy to allow_overlap/barge_in_enabled.';
		}
		if (normalized.includes('playback_gated_by_capture')) {
			return 'Pause capture streams or switch duplex policy to allow_overlap.';
		}
		return 'Adjust duplex policy or stop the conflicting stream, then retry.';
	}

	function asErrorMessage(err: unknown, fallback: string): string {
		return err instanceof Error ? err.message : fallback;
	}

	function handleActionError(err: unknown, fallback: string): void {
		if (err instanceof ApiRequestError && err.status === 409) {
			error = null;
			conflictDetail = err.message;
			conflictHint = conflictHintFromDetail(err.message);
			return;
		}
		conflictDetail = null;
		conflictHint = null;
		error = asErrorMessage(err, fallback);
	}

	async function readApiError(res: Response): Promise<ApiRequestError> {
		return new ApiRequestError(
			res.status,
			getErrorMessageFromResponseBody(await res.text(), res.status)
		);
	}

	async function fetchStatus(): Promise<void> {
		const res = await fetch(`${API_BASE}/status`);
		if (!res.ok) throw new Error(`/status HTTP ${res.status}`);
		const status: StatusResponse = await res.json();
		audioEnabled = Boolean(status.features?.audio_module_enabled);
		statusChecked = true;
	}

	async function setAudioModuleEnabled(enabled: boolean): Promise<void> {
		togglingAudioModule = true;
		info = null;
		clearErrors();
		try {
			const res = await fetch(`${API_BASE}/audio/module`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ enabled })
			});
			if (!res.ok) throw await readApiError(res);
			await refreshAll(true);
			window.dispatchEvent(new CustomEvent('audio-feature-changed', { detail: { enabled } }));
			info = enabled ? 'Audio module enabled.' : 'Audio module disabled.';
		} catch (e) {
			handleActionError(e, 'Failed to update audio module state');
		} finally {
			togglingAudioModule = false;
		}
	}

	function syncDefaultSelections(): void {
		if (!audioState) return;
		const inputDefault =
			audioState.defaults.default_input_device_id ?? devices?.default_input_device_id ?? '';
		const outputDefault =
			audioState.defaults.default_output_device_id ?? devices?.default_output_device_id ?? '';
		selectedInputDeviceId = inputDefault || '';
		selectedOutputDeviceId = outputDefault || '';
	}

	function syncStateSelections(): void {
		if (!audioState) return;
		selectedDuplexPolicy = audioState.duplex_policy || 'allow_overlap';
		selectedPushToTalk = Boolean(audioState.push_to_talk);

		const nextDraft: Record<string, { gain_db: string; muted: boolean }> = {};
		for (const route of audioState.routes) {
			const control = audioState.controls.find((entry) => entry.stream_id === route.route_id);
			nextDraft[route.route_id] = {
				gain_db: String(control?.gain_db ?? 0),
				muted: Boolean(control?.muted)
			};
		}
		controlDraftByRoute = nextDraft;
	}

	async function fetchDevices(): Promise<void> {
		const res = await fetch(`${API_BASE}/audio/devices`);
		if (!res.ok) throw new Error(`/audio/devices HTTP ${res.status}`);
		devices = await res.json();
	}

	async function fetchAudioState(): Promise<void> {
		const res = await fetch(`${API_BASE}/audio/state`);
		if (!res.ok) throw new Error(`/audio/state HTTP ${res.status}`);
		audioState = await res.json();
	}

	async function fetchMeters(): Promise<void> {
		if (!audioEnabled) return;
		try {
			const res = await fetch(`${API_BASE}/audio/meters`);
			if (!res.ok) return;
			const data = await res.json();
			meters = Array.isArray(data.meters) ? data.meters : [];
		} catch {
			// Keep non-blocking for meter polling.
		}
	}

	async function refreshAll(background = false): Promise<void> {
		if (background) refreshing = true;
		try {
			await fetchStatus();
			if (audioEnabled) {
				await Promise.all([fetchDevices(), fetchAudioState()]);
				await fetchMeters();
				syncDefaultSelections();
				syncStateSelections();
			} else {
				devices = null;
				audioState = null;
				meters = [];
			}
			clearErrors();
		} catch (e) {
			conflictDetail = null;
			conflictHint = null;
			error = asErrorMessage(e, 'Unknown error');
		} finally {
			loading = false;
			refreshing = false;
		}
	}

	async function saveDefaults(): Promise<void> {
		if (!audioEnabled) return;
		savingDefaults = true;
		info = null;
		clearErrors();
		try {
			const payload = {
				default_input_device_id: selectedInputDeviceId || null,
				default_output_device_id: selectedOutputDeviceId || null
			};
			const res = await fetch(`${API_BASE}/audio/defaults`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(payload)
			});
			if (!res.ok) throw await readApiError(res);
			await Promise.all([fetchDevices(), fetchAudioState()]);
			syncDefaultSelections();
			syncStateSelections();
			info = 'Defaults updated.';
		} catch (e) {
			handleActionError(e, 'Failed to update defaults');
		} finally {
			savingDefaults = false;
		}
	}

	async function savePolicy(): Promise<void> {
		if (!audioEnabled) return;
		savingPolicy = true;
		info = null;
		clearErrors();
		try {
			const res = await fetch(`${API_BASE}/audio/policy`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ mode: selectedDuplexPolicy })
			});
			if (!res.ok) throw await readApiError(res);
			await fetchAudioState();
			syncStateSelections();
			info = `Duplex policy set to ${selectedDuplexPolicy}.`;
		} catch (e) {
			handleActionError(e, 'Failed to save duplex policy');
		} finally {
			savingPolicy = false;
		}
	}

	async function savePushToTalk(): Promise<void> {
		if (!audioEnabled) return;
		savingPushToTalk = true;
		info = null;
		clearErrors();
		try {
			const res = await fetch(`${API_BASE}/audio/controls`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ push_to_talk: selectedPushToTalk })
			});
			if (!res.ok) throw await readApiError(res);
			await fetchAudioState();
			syncStateSelections();
			info = `Push-to-talk ${selectedPushToTalk ? 'enabled' : 'disabled'}.`;
		} catch (e) {
			handleActionError(e, 'Failed to save push-to-talk');
		} finally {
			savingPushToTalk = false;
		}
	}

	async function upsertRoute(): Promise<void> {
		if (!audioEnabled) return;
		creatingRoute = true;
		info = null;
		clearErrors();
		try {
			const processors: AudioNode[] = [];
			if (processorKind) {
				processors.push(nodeFromInputs(processorKind, processorName, processorConfigRaw));
			}

			const payload: Record<string, unknown> = {
				name: routeName.trim() || null,
				source: nodeFromInputs(sourceKind, sourceName, sourceConfigRaw),
				processors,
				sink: nodeFromInputs(sinkKind, sinkName, sinkConfigRaw),
				enabled: true
			};
			if (editingRouteId) payload.route_id = editingRouteId;

			const res = await fetch(`${API_BASE}/audio/routes`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(payload)
			});
			if (!res.ok) throw await readApiError(res);

			await Promise.all([fetchAudioState(), fetchMeters()]);
			syncStateSelections();
			info = editingRouteId ? 'Route updated.' : 'Route created.';
			resetRouteBuilder();
		} catch (e) {
			handleActionError(e, 'Failed to upsert route');
		} finally {
			creatingRoute = false;
		}
	}

	async function deleteRoute(routeId: string): Promise<void> {
		deletingRouteId = routeId;
		info = null;
		clearErrors();
		try {
			const res = await fetch(`${API_BASE}/audio/routes/${routeId}`, { method: 'DELETE' });
			if (!res.ok) throw await readApiError(res);
			await Promise.all([fetchAudioState(), fetchMeters()]);
			syncStateSelections();
			if (editingRouteId === routeId) resetRouteBuilder();
			info = `Route ${routeId} deleted.`;
		} catch (e) {
			handleActionError(e, 'Failed to delete route');
		} finally {
			deletingRouteId = null;
		}
	}

	function editRoute(route: AudioRouteRecord): void {
		editingRouteId = route.route_id;
		routeName = route.name ?? '';
		sourceKind = route.source.kind;
		sourceName = route.source.name ?? '';
		sourceConfigRaw = configToRaw(route.source.config);
		sinkKind = route.sink.kind;
		sinkName = route.sink.name ?? '';
		sinkConfigRaw = configToRaw(route.sink.config);
		processorKind = route.processors[0]?.kind ?? '';
		processorName = route.processors[0]?.name ?? '';
		processorConfigRaw = configToRaw(route.processors[0]?.config);
		if (route.processors.length > 1) {
			info = 'Edit mode keeps only one optional processor in the guided form.';
		}
	}

	function streamForRoute(routeId: string): AudioStreamRecord | undefined {
		return audioState?.streams.find((stream) => stream.route_id === routeId);
	}

	function meterForRoute(routeId: string): AudioMeter | undefined {
		return meters.find((meter) => meter.stream_id === routeId);
	}

	function meterPercent(value: number | undefined): number {
		if (typeof value !== 'number' || Number.isNaN(value)) return 0;
		return Math.min(100, Math.max(0, value * 100));
	}

	function controlDraft(routeId: string): { gain_db: string; muted: boolean } {
		return controlDraftByRoute[routeId] ?? { gain_db: '0', muted: false };
	}

	function setControlGain(routeId: string, gainValue: string): void {
		const current = controlDraft(routeId);
		controlDraftByRoute = {
			...controlDraftByRoute,
			[routeId]: { ...current, gain_db: gainValue }
		};
	}

	function setControlMuted(routeId: string, mutedValue: boolean): void {
		const current = controlDraft(routeId);
		controlDraftByRoute = {
			...controlDraftByRoute,
			[routeId]: { ...current, muted: mutedValue }
		};
	}

	function streamActionInFlight(routeId: string): StreamAction | undefined {
		return streamActionByRoute[routeId];
	}

	async function setStreamState(routeId: string, action: StreamAction): Promise<void> {
		if (!audioEnabled) return;
		streamActionByRoute = { ...streamActionByRoute, [routeId]: action };
		info = null;
		clearErrors();
		try {
			const res = await fetch(`${API_BASE}/audio/streams/${routeId}/${action}`, { method: 'POST' });
			const bodyText = await res.text();
			if (!res.ok) {
				throw new ApiRequestError(res.status, getErrorMessageFromResponseBody(bodyText, res.status));
			}
			let interruptedIds: string[] = [];
			try {
				const parsed = JSON.parse(bodyText) as { interrupted_stream_ids?: unknown };
				if (Array.isArray(parsed.interrupted_stream_ids)) {
					interruptedIds = parsed.interrupted_stream_ids.filter(
						(item): item is string => typeof item === 'string'
					);
				}
			} catch {
				// Ignore parse failures on success payload.
			}
			await Promise.all([fetchAudioState(), fetchMeters()]);
			syncStateSelections();
			info =
				action === 'start' && interruptedIds.length > 0
					? `Stream started. Barge-in paused: ${interruptedIds.join(', ')}`
					: `Stream ${action} completed.`;
		} catch (e) {
			handleActionError(e, `Failed to ${action} stream`);
		} finally {
			streamActionByRoute = { ...streamActionByRoute, [routeId]: undefined };
		}
	}

	async function saveStreamControl(routeId: string): Promise<void> {
		if (!audioEnabled) return;
		savingControlByRoute = { ...savingControlByRoute, [routeId]: true };
		info = null;
		clearErrors();
		try {
			const draft = controlDraft(routeId);
			const gain = Number(draft.gain_db);
			if (!Number.isFinite(gain)) {
				throw new Error('Gain must be a valid number');
			}
			const res = await fetch(`${API_BASE}/audio/controls`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					stream_id: routeId,
					gain_db: gain,
					muted: draft.muted
				})
			});
			if (!res.ok) throw await readApiError(res);
			await fetchAudioState();
			syncStateSelections();
			info = `Controls saved for ${routeId}.`;
		} catch (e) {
			handleActionError(e, 'Failed to save stream controls');
		} finally {
			savingControlByRoute = { ...savingControlByRoute, [routeId]: false };
		}
	}

	onMount(() => {
		refreshAll();
		meterPollTimer = setInterval(() => {
			fetchMeters();
		}, METER_POLL_MS);
	});

	onDestroy(() => {
		if (meterPollTimer) clearInterval(meterPollTimer);
	});
</script>

<div class="page-title-row">
	<div>
		<h1>Audio</h1>
		<p class="page-title-muted">Device defaults and route graph control for the optional audio module.</p>
	</div>

	<div class="audio-header-actions">
		{#if audioState}
			<span class={`badge ${audioState.engine_running ? 'badge-soft' : ''}`}>
				Engine: {audioState.engine_running ? 'running' : 'idle'}
			</span>
		{/if}
		<button class="btn btn-ghost" on:click={() => refreshAll(true)} disabled={loading || refreshing}>
			{refreshing ? 'Refreshing...' : 'Refresh'}
		</button>
	</div>
</div>

{#if error}
	<div class="alert alert-error" role="status">
		<div>
			<div class="alert-title">Audio API error</div>
			<div class="alert-body">{error}</div>
		</div>
	</div>
{/if}

{#if conflictDetail}
	<div class="alert audio-alert-conflict" role="status">
		<div>
			<div class="alert-title">Conflict (409)</div>
			<div class="alert-body">{conflictDetail}</div>
			{#if conflictHint}
				<div class="alert-body audio-alert-conflict-hint">{conflictHint}</div>
			{/if}
		</div>
	</div>
{/if}

{#if info}
	<div class="alert" role="status">
		<div>
			<div class="alert-title">Update</div>
			<div class="alert-body">{info}</div>
		</div>
	</div>
{/if}

{#if loading && !statusChecked}
	<p class="page-title-muted">Loading audio dashboard...</p>
{:else if !audioEnabled}
	<section class="audio-panel">
		<h2>Audio module disabled</h2>
		<p>
			Enable it for this runtime session:
		</p>
		<div class="audio-inline-actions">
			<button class="btn btn-primary" on:click={() => setAudioModuleEnabled(true)} disabled={togglingAudioModule}>
				{togglingAudioModule ? 'Enabling...' : 'Enable audio module'}
			</button>
			<span class="page-title-muted">Env var still controls default behavior on next restart.</span>
		</div>
	</section>
{:else}
	<section class="audio-grid">
		<article class="audio-panel">
			<div class="audio-panel-head">
				<h2>Device Defaults</h2>
				<span class="badge">/audio/devices</span>
			</div>

			<div class="audio-form-grid">
				<label class="field-label">
					Input device
					<select bind:value={selectedInputDeviceId} class="field-select">
						<option value="">Use host default</option>
						{#if devices}
							{#each devices.input_devices as device}
								<option value={device.id}>{device.name}</option>
							{/each}
						{/if}
					</select>
				</label>

				<label class="field-label">
					Output device
					<select bind:value={selectedOutputDeviceId} class="field-select">
						<option value="">Use host default</option>
						{#if devices}
							{#each devices.output_devices as device}
								<option value={device.id}>{device.name}</option>
							{/each}
						{/if}
					</select>
				</label>
			</div>

			<div class="audio-inline-actions">
				<button class="btn btn-primary" on:click={saveDefaults} disabled={savingDefaults}>
					{savingDefaults ? 'Saving...' : 'Save defaults'}
				</button>
				{#if devices?.error_code === 'missing_dependency'}
					<span class="page-title-muted">
						Audio device discovery needs one package: <code>pip install sounddevice</code>, then restart backend.
					</span>
				{:else if devices?.hint}
					<span class="page-title-muted">{devices.hint}</span>
				{:else if devices?.error}
					<span class="page-title-muted">Device backend note: {devices.error}</span>
				{/if}
			</div>
		</article>

		<article class="audio-panel">
			<div class="audio-panel-head">
				<h2>{editingRouteId ? 'Edit Route' : 'Create Route'}</h2>
				<span class="badge">/audio/routes</span>
			</div>

			<div class="audio-form-grid">
				<label class="field-label">
					Route name
					<input class="field-input" bind:value={routeName} placeholder="optional" />
				</label>
				<label class="field-label">
					Source kind
					<select class="field-select" bind:value={sourceKind}>
						{#each sourceKinds as kind}
							<option value={kind}>{kind}</option>
						{/each}
					</select>
				</label>
				<label class="field-label">
					Source name
					<input class="field-input" bind:value={sourceName} placeholder="optional" />
				</label>
				<label class="field-label">
					Sink kind
					<select class="field-select" bind:value={sinkKind}>
						{#each sinkKinds as kind}
							<option value={kind}>{kind}</option>
						{/each}
					</select>
				</label>
				<label class="field-label">
					Sink name
					<input class="field-input" bind:value={sinkName} placeholder="optional" />
				</label>
				<label class="field-label">
					Processor (optional)
					<select class="field-select" bind:value={processorKind}>
						{#each processorKinds as kind}
							<option value={kind}>{kind || 'none'}</option>
						{/each}
					</select>
				</label>
				{#if processorKind}
					<label class="field-label">
						Processor name
						<input class="field-input" bind:value={processorName} placeholder="optional" />
					</label>
				{/if}
			</div>

			<details class="audio-details">
				<summary>Advanced JSON config (optional)</summary>
				<div class="audio-form-grid">
					<label class="field-label">
						Source config JSON
						<textarea
							class="field-textarea"
							bind:value={sourceConfigRaw}
							placeholder='&#123;"device_id":"default"&#125;'
						></textarea>
					</label>
					<label class="field-label">
						Sink config JSON
						<textarea
							class="field-textarea"
							bind:value={sinkConfigRaw}
							placeholder='&#123;"path":"output.wav"&#125;'
						></textarea>
					</label>
					{#if processorKind}
						<label class="field-label">
							Processor config JSON
							<textarea
								class="field-textarea"
								bind:value={processorConfigRaw}
								placeholder='&#123;"target_sample_rate":16000&#125;'
							></textarea>
						</label>
					{/if}
				</div>
			</details>

			<div class="audio-inline-actions">
				<button class="btn btn-primary" on:click={upsertRoute} disabled={creatingRoute}>
					{creatingRoute ? 'Saving...' : editingRouteId ? 'Save route' : 'Create route'}
				</button>
				{#if editingRouteId}
					<button class="btn" on:click={resetRouteBuilder}>Cancel edit</button>
				{/if}
			</div>
		</article>

		<article class="audio-panel">
			<div class="audio-panel-head">
				<h2>Session Controls</h2>
				<span class="badge">Policy &amp; PTT</span>
			</div>
			<div class="audio-form-grid">
				<label class="field-label">
					Duplex policy
					<select class="field-select" bind:value={selectedDuplexPolicy}>
						{#each duplexPolicyModes as mode}
							<option value={mode}>{mode}</option>
						{/each}
					</select>
				</label>
				<div class="field-label">
					Push-to-talk
					<label class="audio-toggle">
						<input type="checkbox" bind:checked={selectedPushToTalk} />
						<span>{selectedPushToTalk ? 'Enabled' : 'Disabled'}</span>
					</label>
				</div>
			</div>
			<div class="audio-inline-actions">
				<button class="btn" on:click={savePolicy} disabled={savingPolicy}>
					{savingPolicy ? 'Saving policy...' : 'Save policy'}
				</button>
				<button class="btn" on:click={savePushToTalk} disabled={savingPushToTalk}>
					{savingPushToTalk ? 'Saving PTT...' : 'Save push-to-talk'}
				</button>
			</div>
		</article>
	</section>

	<section class="audio-panel">
		<div class="audio-panel-head">
			<h2>Routes</h2>
			<span class="badge">{audioState?.routes.length ?? 0} total</span>
		</div>

		{#if audioState && audioState.routes.length > 0}
			<div class="audio-routes-grid">
				{#each audioState.routes as route}
					<article class="audio-route-card">
						<header class="audio-route-head">
							<div>
								<div class="audio-route-title">{route.name || route.route_id}</div>
								<div class="audio-route-id">{route.route_id}</div>
							</div>
							<div class="audio-route-badges">
								{#if streamForRoute(route.route_id)}
									<span class="badge badge-soft">
										{streamForRoute(route.route_id)?.state}
									</span>
								{/if}
								{#if meterForRoute(route.route_id)}
									<span class="badge">
										peak {meterForRoute(route.route_id)?.peak.toFixed(2)}
									</span>
								{/if}
							</div>
						</header>
						<div class="audio-route-flow">
							<span>{route.source.kind}</span>
							<span aria-hidden="true">-></span>
							{#if route.processors.length > 0}
								<span>{route.processors.map((p) => p.kind).join(', ')}</span>
								<span aria-hidden="true">-></span>
							{/if}
							<span>{route.sink.kind}</span>
						</div>

						<div class="audio-stream-controls">
							<span class="audio-section-label">Stream</span>
							<div class="audio-inline-actions">
								<button
									class="btn"
									on:click={() => setStreamState(route.route_id, 'start')}
									disabled={Boolean(streamActionInFlight(route.route_id))}
								>
									Start
								</button>
								<button
									class="btn"
									on:click={() => setStreamState(route.route_id, 'pause')}
									disabled={Boolean(streamActionInFlight(route.route_id))}
								>
									Pause
								</button>
								<button
									class="btn"
									on:click={() => setStreamState(route.route_id, 'stop')}
									disabled={Boolean(streamActionInFlight(route.route_id))}
								>
									Stop
								</button>
								{#if streamActionInFlight(route.route_id)}
									<span class="page-title-muted">working...</span>
								{/if}
							</div>
						</div>

						<div class="audio-stream-controls">
							<span class="audio-section-label">Gain / Mute</span>
							<div class="audio-control-row">
								<input
									type="number"
									step="0.5"
									class="field-input field-input-sm"
									value={controlDraft(route.route_id).gain_db}
									on:input={(event) =>
										setControlGain(route.route_id, (event.currentTarget as HTMLInputElement).value)}
								/>
								<label class="audio-toggle">
									<input
										type="checkbox"
										checked={controlDraft(route.route_id).muted}
										on:change={(event) =>
											setControlMuted(route.route_id, (event.currentTarget as HTMLInputElement).checked)}
									/>
									<span>Muted</span>
								</label>
								<button
									class="btn"
									on:click={() => saveStreamControl(route.route_id)}
									disabled={Boolean(savingControlByRoute[route.route_id])}
								>
									{savingControlByRoute[route.route_id] ? 'Saving...' : 'Save'}
								</button>
							</div>
						</div>

						<div class="audio-stream-controls">
							<span class="audio-section-label">Meters</span>
							<div class="audio-meter-grid">
								<div class="audio-meter-line">
									<span>Peak</span>
									<div class="audio-meter-track">
										<span
											class={`audio-meter-fill ${meterForRoute(route.route_id)?.clipped ? 'audio-meter-fill-clipped' : ''}`}
											style={`width: ${meterPercent(meterForRoute(route.route_id)?.peak)}%`}
										></span>
									</div>
									<span>{meterForRoute(route.route_id)?.peak?.toFixed(2) ?? '0.00'}</span>
								</div>
								<div class="audio-meter-line">
									<span>RMS</span>
									<div class="audio-meter-track">
										<span
											class="audio-meter-fill"
											style={`width: ${meterPercent(meterForRoute(route.route_id)?.rms)}%`}
										></span>
									</div>
									<span>{meterForRoute(route.route_id)?.rms?.toFixed(2) ?? '0.00'}</span>
								</div>
							</div>
						</div>
						<div class="audio-inline-actions">
							<button class="btn" on:click={() => editRoute(route)}>Edit</button>
							<button
								class="btn"
								on:click={() => deleteRoute(route.route_id)}
								disabled={deletingRouteId === route.route_id}
							>
								{deletingRouteId === route.route_id ? 'Deleting...' : 'Delete'}
							</button>
						</div>
					</article>
				{/each}
			</div>
		{:else}
			<p class="page-title-muted">No routes configured yet.</p>
		{/if}
	</section>
{/if}

<style>
	.audio-header-actions {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 0.45rem;
	}

	.audio-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: var(--space-3);
		margin-bottom: var(--space-3);
	}

	.audio-panel {
		border: 1px solid var(--border-subtle);
		border-radius: var(--radius-md);
		background: radial-gradient(circle at top left, rgba(59, 130, 246, 0.1), transparent 60%),
			var(--bg-surface);
		padding: var(--space-4);
		box-shadow: 0 10px 22px rgba(15, 23, 42, 0.6);
	}

	.audio-panel h2 {
		margin: 0;
		font-size: 1rem;
	}

	.audio-panel-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
		margin-bottom: var(--space-3);
	}

	.audio-form-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
		gap: 0.6rem;
	}

	.field-label {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		font-size: 0.74rem;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}

	.field-input,
	.field-select,
	.field-textarea {
		padding: 0.36rem 0.55rem;
		border-radius: var(--radius-sm);
		border: 1px solid var(--border-subtle);
		background: var(--bg-surface-alt);
		color: var(--text-primary);
		font-size: 0.84rem;
	}

	.field-textarea {
		min-height: 66px;
		font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Courier New', monospace;
		resize: vertical;
	}

	.field-input:focus-visible,
	.field-select:focus-visible,
	.field-textarea:focus-visible {
		outline: none;
		border-color: rgba(59, 130, 246, 0.9);
		box-shadow: 0 0 0 1px rgba(37, 99, 235, 0.9);
	}

	.audio-inline-actions {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 0.45rem;
		margin-top: 0.65rem;
	}

	.audio-alert-conflict {
		border-color: rgba(245, 158, 11, 0.75);
		background: rgba(67, 20, 7, 0.92);
		color: #fbbf24;
	}

	.audio-alert-conflict::before {
		background: rgba(245, 158, 11, 0.95);
	}

	.audio-alert-conflict-hint {
		margin-top: 0.2rem;
		color: #fde68a;
	}

	.audio-details {
		margin-top: 0.7rem;
		padding: 0.45rem 0.55rem;
		border: 1px solid rgba(148, 163, 184, 0.25);
		border-radius: 0.45rem;
		background: rgba(15, 23, 42, 0.45);
	}

	.audio-details summary {
		cursor: pointer;
		font-size: 0.82rem;
		color: var(--text-muted);
		margin-bottom: 0.5rem;
	}

	.audio-routes-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
		gap: var(--space-3);
	}

	.audio-route-card {
		border: 1px solid rgba(148, 163, 184, 0.3);
		border-radius: var(--radius-sm);
		background: rgba(2, 6, 23, 0.56);
		padding: 0.7rem;
	}

	.audio-route-head {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 0.5rem;
	}

	.audio-route-title {
		font-size: 0.9rem;
		font-weight: 600;
	}

	.audio-route-id {
		font-size: 0.75rem;
		color: var(--text-muted);
		word-break: break-all;
	}

	.audio-route-badges {
		display: flex;
		flex-wrap: wrap;
		gap: 0.35rem;
		justify-content: flex-end;
	}

	.audio-route-flow {
		margin-top: 0.6rem;
		font-size: 0.83rem;
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.33rem;
		color: var(--text-muted);
	}

	.audio-stream-controls {
		margin-top: 0.7rem;
	}

	.audio-section-label {
		display: block;
		font-size: 0.72rem;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--text-muted);
		margin-bottom: 0.25rem;
	}

	.audio-control-row {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 0.45rem;
	}

	.field-input-sm {
		max-width: 100px;
	}

	.audio-toggle {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		font-size: 0.82rem;
		color: var(--text-primary);
	}

	.audio-toggle input {
		accent-color: #38bdf8;
	}

	.audio-meter-grid {
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
	}

	.audio-meter-line {
		display: grid;
		grid-template-columns: 34px 1fr 44px;
		align-items: center;
		gap: 0.45rem;
		font-size: 0.78rem;
		color: var(--text-muted);
	}

	.audio-meter-track {
		height: 0.42rem;
		border-radius: 999px;
		overflow: hidden;
		border: 1px solid rgba(148, 163, 184, 0.35);
		background: rgba(148, 163, 184, 0.2);
	}

	.audio-meter-fill {
		display: block;
		height: 100%;
		background: linear-gradient(90deg, #22c55e, #10b981);
	}

	.audio-meter-fill-clipped {
		background: linear-gradient(90deg, #f97316, #ef4444);
	}

	@media (max-width: 860px) {
		.audio-grid {
			grid-template-columns: 1fr;
		}

		.audio-panel {
			padding: var(--space-3);
		}
	}

	@media (max-width: 620px) {
		.audio-form-grid {
			grid-template-columns: 1fr;
			gap: 0.45rem;
		}

		.audio-routes-grid {
			grid-template-columns: 1fr;
			gap: var(--space-2);
		}

		.audio-route-card {
			padding: 0.55rem;
		}

		.audio-route-head {
			flex-direction: column;
		}

		.audio-route-badges {
			justify-content: flex-start;
		}

		.field-label {
			font-size: 0.68rem;
		}

		.field-input,
		.field-select,
		.field-textarea {
			font-size: 0.8rem;
			padding: 0.3rem 0.5rem;
		}

		.audio-meter-line {
			grid-template-columns: 30px 1fr 40px;
			font-size: 0.72rem;
		}

		.field-input-sm {
			max-width: 88px;
		}
	}
</style>
