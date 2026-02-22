# Audio Path Module Plan (Optional)

## Goal

Add a separate **optional audio-path module** that sits between ASR/TTS models and physical/virtual audio devices. The module should provide direct controls for capture, playback, routing, and monitoring, without forcing audio logic into the core model runtime.

This module is about transport/control of audio streams. ASR and TTS remain model concerns.

## Current status (as of 2026-02-21)

### Completed so far

- Added `onnx_host/audio/` scaffolding:
  - `devices.py` (best-effort device enumeration)
  - `graph.py` (route validation + route materialization)
  - `engine.py` (minimal Phase 2 runtime scaffolding)
  - `state.py` (audio module state store separate from model state)
  - `schemas.py` (audio request/response and node/route models)
- Added `onnx_host/api/audio.py` and mounted it behind `ENABLE_AUDIO_MODULE`.
- Added `ENABLE_AUDIO_MODULE` config switch (default `false`).
- Implemented Phase 1 control-plane endpoints:
  - `GET /audio/devices`
  - `POST /audio/defaults`
  - `GET /audio/routes`
  - `POST /audio/routes`
  - `POST /audio/policy`
  - `DELETE /audio/routes/{route_id}`
- Started Phase 2 stream-plane API surface:
  - `POST /audio/streams/{stream_id}/start`
  - `POST /audio/streams/{stream_id}/stop`
  - `POST /audio/streams/{stream_id}/pause`
  - `POST /audio/controls`
  - `GET /audio/meters`
- Added initial in-memory duplex gating enforcement on stream start:
  - `allow_overlap`
  - `capture_gated_by_playback`
  - `playback_gated_by_capture`
  - `barge_in_enabled` (capture can pause active playback streams)
- Added ASR boundary conversion utility scaffold (to 16 kHz mono at ingress boundary).
- Preserved fault isolation: when disabled, existing model endpoints run unchanged.

### Still left

- Model-specific ASR/TTS adapters are still lightweight/generic (shape-driven ONNX fallback behavior).
- Route/default persistence file (`audio_defaults.json`) and template management.
- Device hot-swap handling, advanced telemetry/diagnostics, and ops hardening.

## Confirmed decisions

The following decisions are locked for implementation:

- Full-duplex is policy-driven (not binary) with explicit gating modes:
  - `capture_gated_by_playback`
  - `playback_gated_by_capture`
  - `allow_overlap`
  - `barge_in_enabled`
- TTS egress must support both device playback and file output.
- Push-to-talk is a first-class backend control.
- Virtual-device support is limited in v1 to simple egress:
  - Send TTS output (or mic passthrough) to a virtual output device for another app.
- Force 16 kHz mono at the ASR ingress boundary only.
  - Do not force 16 kHz mono globally across all internal audio flows.

## Why this is separate

- Keeps core model loading/inference simple and stable.
- Allows deployments with no audio hardware (headless/API-only) to run unchanged.
- Makes device and routing concerns explicit (instead of hidden in model endpoints).

## Scope

### In scope

- Enumerating input/output devices.
- Selecting default capture/playback devices.
- Explicit route control (mic -> ASR, TTS -> speaker/file/virtual device).
- Stream lifecycle control (start/stop/pause).
- Duplex policy control using gating modes (`capture_gated_by_playback`, `playback_gated_by_capture`, `allow_overlap`, `barge_in_enabled`).
- Gain/mute controls and basic meters.
- Optional loopback capture for debugging/recording.
- Push-to-talk backend control.
- TTS egress to both speaker/headphones and file output.
- Limited virtual-device egress for TTS or mic passthrough.

### Out of scope (v1)

- DSP effects chains (AEC/NS/AGC) beyond placeholders.
- Advanced mixing console features.
- Cross-machine network audio transport.

## Proposed architecture

Add a new backend package area:

- `onnx_host/audio/`
  - `devices.py` - enumerate and normalize host device metadata.
  - `graph.py` - manage audio routes and stream graph definitions.
  - `engine.py` - stream runtime (capture/playback buffers, callbacks, thread lifecycle).
  - `state.py` - in-memory session/route/device state.
  - `schemas.py` - request/response models used by API layer.

Add a new API router:

- `onnx_host/api/audio.py`
  - Mounted only when audio module is enabled.

Config switch:

- `ENABLE_AUDIO_MODULE` (default `false`) in runtime config/env.

If disabled, all existing model endpoints continue to work as-is.

## Data-flow model

Represent audio as explicit nodes and routes:

- **Sources**: microphone, loopback, file input, test tone.
- **Processors**: ASR ingress, TTS egress formatter, optional resampler.
- **Sinks**: speakers/headphones, file writer, virtual cable.

ASR boundary rule:

- Streams are converted to 16 kHz mono at the point they become ASR input.
- Non-ASR paths (for example, TTS device playback) may use device-native format unless explicitly configured otherwise.

Example routes:

1. `mic(default) -> asr(model=whisper)`
2. `tts(model=piper, voice=emma) -> speakers(default)`
3. `mic(usb) -> asr -> text bus -> tts -> virtual_output(cable_a)`
4. `tts(model=piper, voice=emma) -> file(output.wav)`
5. `mic(default) -> passthrough -> virtual_output(cable_a)`

## Duplex and gating semantics

The module should treat duplex behavior as a policy object (per route group or session), not as a single boolean:

- `capture_gated_by_playback`
  - When playback is active, capture is suppressed unless override is set.
- `playback_gated_by_capture`
  - When capture is active, playback is suppressed unless override is set.
- `allow_overlap`
  - Capture and playback can run simultaneously.
- `barge_in_enabled`
  - New capture activity can interrupt or duck active playback according to route policy.

Recommended implementation order:

1. Implement `allow_overlap` and `capture_gated_by_playback` first.
2. Add `playback_gated_by_capture`.
3. Add `barge_in_enabled` with explicit interruption/ducking behavior.

## API sketch

- `GET /audio/devices`
  - Returns available capture/playback devices + defaults.
  - Status: implemented.
- `POST /audio/defaults`
  - Set default input/output device IDs.
  - Status: implemented.
- `GET /audio/routes`
  - List active route graph.
  - Status: implemented.
- `POST /audio/routes`
  - Create/update a route.
  - Status: implemented.
- `POST /audio/policy`
  - Set duplex gating policy for a route/session.
  - Status: implemented.
- `DELETE /audio/routes/{route_id}`
  - Remove route.
  - Status: implemented.
- `POST /audio/streams/{stream_id}/start`
  - Status: implemented (state-plane only).
- `POST /audio/streams/{stream_id}/stop`
  - Status: implemented (state-plane only).
- `POST /audio/streams/{stream_id}/pause`
  - Status: implemented (state-plane only).
- `POST /audio/controls`
  - Per-stream gain/mute + push-to-talk configuration.
  - Status: implemented (state-plane only).
- `GET /audio/meters`
  - Lightweight real-time level snapshots.
  - Status: implemented (state snapshots; live metering pending).

## UI additions (optional page)

Add `runtime-ui/src/routes/audio/+page.svelte` with:

- Device selectors (input/output).
- Route cards showing source -> processor -> sink.
- Stream transport controls (start/stop/pause).
- Per-route gain/mute + level meter.

Keep this page hidden when module is disabled.

## Runtime behavior and safety

- Start audio engine lazily only when first audio route starts.
- Fail route operations independently from model loading (fault isolation).
- Apply gating policy in the stream scheduler before enqueue/dequeue decisions.
- Implement barge-in as a deterministic state transition (interrupt/duck/resume), not an ad-hoc callback.
- Apply backpressure policy per route:
  - ASR ingress: drop oldest frames when overloaded.
  - TTS playback: prefer bounded queue + underrun telemetry.
- Emit structured logs for device change, route errors, and xruns.

## State model

Track in-memory state separately from model state:

- `audio_enabled`
- `default_input_device_id`
- `default_output_device_id`
- `routes[]`
- `streams[]`
- `duplex_policy`
- `push_to_talk`
- `meters`

Persist optional `audio_defaults.json` (device preferences + route templates), but not transient meter data.

## Phased rollout

### Phase 1: Control plane only

- Status: complete.
- Done:
  - Device enumeration endpoint.
  - Route CRUD with validation.
  - Optional module mount behind `ENABLE_AUDIO_MODULE=false` default.
  - Duplex policy endpoint and validation (`POST /audio/policy`).
  - No live streaming yet (dry-run graph state).
- Remaining in Phase 1:
  - Confirm/lock decision on best-effort device enumeration fallback vs fixed backend dependency.

### Phase 2: Basic stream plane

- Status: started.
- Done so far:
  - Stream lifecycle endpoints for start/stop/pause with in-memory state transitions.
  - Controls endpoint for gain/mute and push-to-talk state.
  - Meter endpoint with per-stream snapshots.
  - Initial duplex policy enforcement at stream start.
  - Initial ASR ingress conversion utility for 16 kHz mono boundary normalization.
  - Real runtime lifecycle wiring for stream start/pause/stop.
  - Live stream runtime for capture/playback workers and callbacks.
  - Live meter updates from runtime audio frames.
  - Basic ASR adapter ingestion from runtime ASR ingress buffers.
  - Basic TTS adapter waveform synthesis for `source.kind=tts` with tone fallback.
- Remaining:
- Harden model-specific ASR/TTS bindings per concrete model contracts.

### Phase 3: Operations hardening

- Status: not started.
- Device hot-swap handling.
- Better telemetry and diagnostics.
- Route templates/import-export.
- Virtual-device egress stabilization for third-party consumer apps.

## Integration points with existing modules

- `onnx_host/runtime.py`
  - Keep model session lifecycle unchanged.
  - Expose small adapter methods used by audio engine for ASR/TTS ingress/egress.
- `onnx_host/state.py`
  - Do not merge audio stream state into existing model state maps.
- `onnx_host/main.py`
  - Conditionally include `audio_router` when enabled.

## Remaining open design questions

- Which host audio backend should be the default abstraction on Windows?
- Should route templates be global, per model, or per user profile?
- For `barge_in_enabled`, should default behavior be hard interrupt or playback ducking?
