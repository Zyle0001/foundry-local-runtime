# Audio Dashboard Integration Plan (Svelte)

## Summary

Add a new `/audio` dashboard page with full v1 controls (devices/defaults, route CRUD, duplex policy, stream transport, gain/mute, global push-to-talk, meters), and integrate it into navigation and Home discoverability.

Visibility is feature-gated so Audio UI is hidden when audio module is disabled.

## Current Status (as of 2026-02-21)

### Completed

- Backend:
  - `/status` now includes `features.audio_module_enabled`.
  - `/audio/state` is implemented and returns defaults/policy/routes/streams/controls/meters/engine state.
  - Runtime toggle endpoints are implemented:
    - `GET /audio/module`
    - `POST /audio/module`
  - `POST /audio/controls` supports global push-to-talk updates without requiring `stream_id`.
- Dashboard entry points:
  - Sidebar Audio nav link is feature-gated.
  - Home Audio card/action is feature-gated.
  - Small "Enable audio" launcher control exists in sidebar when audio is off.
- `/audio` page:
  - Devices/default selectors with friendly missing-dependency messaging.
  - Duplex policy selector.
  - Guided route builder with optional advanced JSON blocks.
  - Route edit/delete support (edit includes `route_id` upsert path).
  - Stream controls per route (`start/pause/stop`).
  - Per-stream gain/mute controls.
  - Global push-to-talk toggle.
  - Meter display per route with 2s polling.
  - Disabled panel includes one-click runtime enable action.
  - Dedicated 409 conflict feedback with action hints (policy gating vs module-disabled cases).
  - Mobile density tuning for route cards/forms/controls on smaller viewports.
- Validation:
  - `npm run check` currently passes.

### Remaining

- Optional expanded manual UX pass in browser for mobile density/layout edge cases.
- Deeper model-specific ASR/TTS adapters (current adapters are generic ONNX-shape heuristics).

## Manual Smoke Checklist (executed 2026-02-21)

1. Mode A startup: `ENABLE_AUDIO_MODULE=false`
- Start backend with audio module disabled.
- Confirm sidebar/home audio entry points are hidden.
- Open `/audio` directly and verify disabled panel + runtime enable button.
- Click enable button and verify:
  - audio nav/home entries appear without restart.
  - defaults/routes/policy/stream controls become available.
- Create one capture and one playback route, then exercise:
  - `start/pause/stop` transitions.
  - duplex policy conflict path (expect 409 conflict banner with hint text).
  - `barge_in_enabled` path (expect interrupted stream IDs in update banner).

2. Mode B startup: `ENABLE_AUDIO_MODULE=true`
- Start backend with audio module enabled.
- Confirm audio nav/home entries are present on first load.
- Verify defaults save + reload, route CRUD, controls save, and meter polling.
- Reproduce one 409 policy conflict and confirm conflict banner appears.
- Validate small-screen layout manually (browser mobile width) for:
  - no clipped action buttons in route cards.
  - single-column forms/cards at narrow widths.

## Execution Notes (2026-02-21)

- API smoke run completed successfully against local backend:
  - Module toggle off/on verified through `/audio/module` and `/status.features.audio_module_enabled`.
  - Route CRUD verified.
  - Stream start/pause/stop verified.
  - Duplex policy conflict path returned `409` as expected.
  - `barge_in_enabled` path returned interrupted stream IDs as expected.
  - Live meter values were non-zero during active streams (frame-driven, not static snapshots).
  - Defaults roundtrip verified.
- Repro script added: `scripts/audio_phase2_smoke.ps1`.

## Public API / Interface Changes

1. Extend `GET /status` in `onnx_host/api/status.py`:
- Add `features.audio_module_enabled: boolean`.
- Keep existing fields backward-compatible.

2. Add `GET /audio/state` in `onnx_host/api/audio.py`:
```json
{
  "audio_enabled": true,
  "defaults": {
    "default_input_device_id": "string|null",
    "default_output_device_id": "string|null"
  },
  "duplex_policy": "capture_gated_by_playback|playback_gated_by_capture|allow_overlap|barge_in_enabled",
  "push_to_talk": false,
  "routes": [],
  "streams": [],
  "controls": [],
  "adapter_diagnostics": {
    "asr": {},
    "tts": {}
  },
  "engine_running": false
}
```

3. Frontend page-local types in `runtime-ui/src/routes/audio/+page.svelte`:
- `StatusResponse` (with `features`)
- `AudioDevicesResponse`
- `AudioStateResponse`
- Request/response types for existing `/audio/*` endpoints.

## Implementation Plan

1. Backend support
- Add `/status.features.audio_module_enabled`.
- Add `GET /audio/state` from `audio_state_store.snapshot()` + `audio_engine.is_running`.

2. Dashboard entry points
- Update `runtime-ui/src/routes/+layout.svelte` to fetch `/status` and show Audio nav link only when enabled.
- Update `runtime-ui/src/routes/+page.svelte` to show Audio card/action only when enabled.

3. New page: `runtime-ui/src/routes/audio/+page.svelte`
- Devices/default selectors (`GET /audio/devices`, `POST /audio/defaults`)
- Duplex policy selector (`POST /audio/policy`)
- Guided route builder:
  - Required: source kind, sink kind
  - Optional: single processor
  - Optional advanced JSON config blocks (source/processor/sink)
- Route list with edit/delete
- Stream controls per route (`start/pause/stop`)
- Per-stream controls (`gain_db`, `muted`)
- Global push-to-talk toggle
- Meter display bound by `stream_id`

4. Refresh behavior
- Initial load: `/status`, `/audio/devices`, `/audio/state`, `/audio/meters`
- Auto-poll meters only (2s)
- After any mutation: refetch `/audio/state` + `/audio/meters`
- Manual refresh refetches devices/state/meters

5. Disabled behavior
- Hide Audio nav/Home card when feature is off.
- Direct `/audio` URL shows explicit "Audio module disabled" instructions.
- API failures show non-blocking error alerts.

## Test Cases

1. Feature gating
- `ENABLE_AUDIO_MODULE=false`: no Audio nav/card; `/audio` shows disabled panel.
- `ENABLE_AUDIO_MODULE=true`: Audio nav/card visible.

2. Devices/defaults
- Devices load correctly.
- Setting defaults persists in `/audio/state.defaults`.
- Invalid IDs show API error.

3. Routes
- Create/edit/delete route works.
- Edit mode includes `route_id` in upsert payload.

4. Policy/streams
- Policy changes reflect in state.
- Start/pause/stop updates state accurately.
- 409 policy violations surfaced clearly.
- `barge_in_enabled` interrupted streams shown in UI feedback.

5. Controls/meters
- Gain/mute persisted via `/audio/state.controls`.
- Global push-to-talk reflects shared backend state.
- Meter polling updates without full page refresh.

6. Validation gate
- Run `npm run check` in `runtime-ui`.
- Manual smoke checklist for enabled/disabled modes.

## Assumptions / Defaults

- Full v1 controls are in scope.
- Audio is discoverable via sidebar + Home card.
- Frontend keeps page-local fetch style (no shared API refactor).
- Single optional processor in guided builder.
- Advanced node config editing via optional JSON blocks.
- Push-to-talk shown as a global control.
- Minimal backend additions (`/status.features`, `GET /audio/state`) are allowed for UI correctness.
