# Overview

This is a minimal, local Windows ONNX host with a tiny web UI. It scans a `models/` folder, lets you load/unload models,
and exposes simple endpoints to run inference and check VRAM status. The goal is lean, pragmatic functionality for DirectML/WindowsML 
workflows. This is not a framework, not production-hardened, and not actively maintained. It exists to solve a specific local workflow 
problem.

## Why this exists

This project exists to support my own local ONNX workflows on Windows.
It is intentionally minimal and opinionated.
If it does not fit your use case, it is not intended to.
This exists because I need it. If you also need it, great. If not, fork it.

## Quick Start

1. Put models on disk under `ONNX host service/models/<model-folder>/`.
2. Start dev servers:
   - Run `Dev.ps1` from the repo root.
   - UI: `http://localhost:5173`
   - API: `http://127.0.0.1:8000`
3. Open the Models page, load a model, and watch VRAM usage.

## Model Discovery

- Each top-level folder under `models/` is treated as a model.
- Variants are inferred from ONNX filename suffixes (e.g. `_fp16`, `_int8`).
- The registry (`models.json`) is updated from disk on each `/models` call.

## Core Endpoints

- `GET /models` — scan disk and return the registry.
- `POST /models/load` — load a model by id (variant optional).
- `POST /models/unload` — unload a model by id.
- `GET /models/{id}/inputs` — list ONNX inputs for a loaded model.
- `GET /models/{id}/options` — list selectable `voices/` and `configs/` for a model.
- `POST /models/{id}/active` — set active voice/config (in‑memory only).
- `POST /models/{id}/smoke` — run a single minimal forward pass.
- `POST /predict/{model_name}` — run inference on a loaded model.
- `GET /status` — VRAM usage and GPU info.

## Endpoint Usage

### `GET /models`
Returns the registry with discovered models and variants.

### `POST /models/load`
Body:
```json
{ "id": "Ministral-3-3B-Instruct-2512-ONNX", "variant": "fp16" }
```
Notes:
- `variant` is optional. If omitted, the first `.onnx` artifact is used.
- TTS models load on CPU by default; others use DML.

### `POST /models/unload`
Body:
```json
{ "id": "Ministral-3-3B-Instruct-2512-ONNX" }
```

### `GET /models/{id}/inputs`
Returns:
```json
{
  "inputs": [
    { "name": "input_ids", "shape": [1, "sequence_length"], "type": "tensor(int64)" }
  ]
}
```

### `GET /models/{id}/options`
Scans only `configs/` and `voices/` under the model folder.
Returns:
```json
{ "voices": ["emma"], "configs": ["fast", "high_quality"] }
```

### `POST /models/{id}/active`
Body:
```json
{ "voice": "emma", "config": "high_quality" }
```
Notes:
- In‑memory only, no file writes.
- Missing or empty values clear the active selection.

### `POST /models/{id}/smoke`
Runs a minimal forward pass and returns timing only.
Response:
```json
{ "id": "whisper", "status": "ok", "runtime_ms": 12, "note": "single forward pass" }
```

### `POST /predict/{model_name}`
Body:
```json
{ "input_ids": [[1, 2, 3]], "attention_mask": [[1, 1, 1]] }
```
Notes:
- Input keys must match the ONNX input names.
- See `/models/{id}/inputs` for the exact shape/type.

### `GET /status`
Returns VRAM usage for the first DXGI adapter.

## Backend Layout & Architecture

The backend is a small FastAPI app packaged under `onnx_host/`, with a thin compatibility shim in `ONNX host service/server.py`:

- **Entry point**: `server.py` imports `onnx_host.main.app` and runs Uvicorn when started directly. Tooling can still refer to `"ONNX host service.server:app"`.
- **FastAPI app**: `onnx_host/main.py` creates the `FastAPI` instance, configures CORS for the SvelteKit UI, and includes the API routers from `onnx_host.api`.
- **API layer (`onnx_host/api/`)**:
  - `engine.py` — `/Load` and `/predict/{model_name}` endpoints.
  - `models.py` — `/models` endpoints (listing, load/unload, options, active selection, inputs, smoke tests).
  - `status.py` — `/status` endpoint that reports VRAM/GPU info.
  - `__init__.py` — re‑exports the routers (`engine_router`, `models_router`, `status_router`) that `main.py` plugs into the app.
- **Model/runtime domain layer**:
  - `registry.py` — scans the `models/` folder, infers variants from filenames, and maintains the in‑memory registry used by `/models`.
  - `state.py` — keeps track of loaded models, hot models, and active options (per‑model voices/configs) in memory.
  - `selectors.py` — helpers for model kind and selectable options (voices/configs) so routers stay thin.
  - `runtime.py` — ONNX Runtime integration: session creation, input shape/type helpers, and simple smoke‑test helpers for different model types.
- **Infrastructure layer**:
  - `dxgi.py` — wraps the DXGI interop needed to query VRAM usage behind a small function used by `/status`.
  - `config.py` — central place for paths (e.g., models directory, registry file) and related configuration helpers.
- **Client/UI**:
  - `client.py` (outside the package) is a thin HTTP client that talks to the same public endpoints described above.
  - The SvelteKit UI only sees the HTTP surface; it does not depend on internal Python modules.

When adding new features, prefer to:

- Put **HTTP shapes and routing** in `onnx_host/api/*`.
- Put **model/domain logic and state** in `registry.py`, `state.py`, `selectors.py`, or `runtime.py`.
- Add **system‑level or Windows/DXGI concerns** in `dxgi.py` or `config.py`.

## Notes

- Variants are selectable at load time (defaults to the first `.onnx` artifact).
- Error feedback is minimal by design; use logs/HTTP responses for details.
- VRAM status currently reports the first DXGI adapter.
- TTS models load on CPU by default (DML provider limitations).

## Audio Path (Planned Optional Module)

For planned audio routing/control work (device selection, route graph, and stream transport controls around ASR/TTS), see `docs/audio-path-module-plan.md`.

Current implementation status:
- Phase 1 control plane is available behind `ENABLE_AUDIO_MODULE=true`.
- Phase 1 is complete and Phase 2 is started (state-plane).
- Implemented endpoints:
  - `GET /audio/devices`
  - `POST /audio/defaults`
  - `GET /audio/routes`
  - `POST /audio/routes`
  - `POST /audio/policy`
  - `DELETE /audio/routes/{route_id}`
  - `POST /audio/streams/{stream_id}/start`
  - `POST /audio/streams/{stream_id}/stop`
  - `POST /audio/streams/{stream_id}/pause`
  - `POST /audio/controls`
  - `GET /audio/meters`
