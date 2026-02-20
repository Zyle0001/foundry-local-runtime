# ONNX Host Service

Minimal local Windows ONNX host with a small Svelte UI.

This project scans a local `models/` folder, lets you load/unload ONNX models, exposes lightweight inference endpoints, and reports adapter VRAM status through DXGI.

## Stack

- Backend: FastAPI + ONNX Runtime (`onnx_host/`)
- UI: SvelteKit (`runtime-ui/`)
- Runtime target: Windows (DirectML / DXGI focus)

## Repo Layout

- `onnx_host/` - backend package (API routers, runtime/session logic, registry, DXGI, logs)
- `ONNX host service/server.py` - thin compatibility entry point
- `runtime-ui/` - dashboard UI
- `docs/overview.md` - architecture and endpoint overview
- `Dev.ps1` - starts UI + API dev servers

## Quick Start

1. Create and activate a Python environment (recommended).
2. Install backend dependencies:
   - `pip install -r requirements.txt`
3. Install UI dependencies:
   - `cd runtime-ui`
   - `npm install`
4. Start both services from repo root:
   - `./Dev.ps1`
5. Open:
   - UI: `http://localhost:5173`
   - API: `http://127.0.0.1:8000`

## Models

Model binaries are intentionally ignored in Git.

Place local model files under:

- `ONNX host service/models/<model-folder>/...`

The host updates `models.json` by scanning this folder.

## Notes for GitHub

- `node_modules/`, local Python envs, IDE files, and model artifacts are ignored via root `.gitignore`.
- This repo is designed for local workflows first; production hardening is out of scope.

## License

Dual-licensed under either:

- MIT (`LICENSE-MIT`)
- Apache-2.0 (`LICENSE-APACHE`)

You may choose either license.
