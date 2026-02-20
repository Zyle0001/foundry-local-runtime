# ONNX Host Service (Local, Beginner-Friendly)

A small **local AI runtime** for Windows that lets you:

- keep ONNX models on your own machine,
- load/unload them from a simple web UI,
- run basic inference over HTTP,
- and monitor GPU VRAM usage.

If you are new to AI tooling, think of this project as a **local model control panel + API**.

---

## What this is (and is not)

### ✅ This project is good for
- Learning how local ONNX model serving works.
- Running models privately on your own Windows machine.
- Simple experiments with model loading, inference, and runtime status.

### ❌ This project is not
- A cloud platform.
- A production-hardened serving stack.
- A one-click installer (you still set up Python + Node once).

---

## How it works (in plain English)

There are two parts:

1. **Backend API (Python / FastAPI)** in `onnx_host/`
   - Scans your local `ONNX host service/models/` folder.
   - Keeps a model registry (`models.json`).
   - Loads ONNX models with ONNX Runtime.
   - Exposes endpoints like `/models`, `/predict/{model_name}`, and `/status`.

2. **Frontend UI (SvelteKit)** in `runtime-ui/`
   - A browser dashboard at `http://localhost:5173`.
   - Lets you view models and trigger actions without manually calling APIs.

---

## Repository layout

- `onnx_host/` - Python backend package (API, runtime, model registry, DXGI status)
- `runtime-ui/` - SvelteKit frontend
- `ONNX host service/` - compatibility entrypoint + local models folder
- `docs/overview.md` - deeper architecture and endpoint notes
- `Dev.ps1` - convenience script to start backend + UI in separate PowerShell windows

---

## Prerequisites (Windows)

Install these once:

- **Python 3.10+**
- **Node.js 18+** (includes npm)
- **Git** (optional, but recommended)

You can verify installs in PowerShell:

```powershell
python --version
node --version
npm --version
```

---

## Quick start (first-time setup)

From the repository root:

### 1) Install backend dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2) Install frontend dependencies

```powershell
cd runtime-ui
npm install
cd ..
```

### 3) Add your models

Put model files under:

```text
ONNX host service/models/<your-model-folder>/...
```

Example:

```text
ONNX host service/models/whisper/whisper_fp16.onnx
```

### 4) Start both services

Option A (recommended convenience script):

```powershell
./Dev.ps1
```

Option B (manual, two terminals):

Terminal 1 (backend):

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn onnx_host.main:app --reload
```

Terminal 2 (frontend):

```powershell
cd runtime-ui
npm run dev
```

### 5) Open the app

- UI: `http://localhost:5173`
- API docs: `http://127.0.0.1:8000/docs`
- API status: `http://127.0.0.1:8000/status`

---

## First run walkthrough (for beginners)

1. Open the UI in your browser.
2. Go to models and confirm your model appears.
3. Load a model.
4. Check `/status` to see adapter/VRAM info.
5. Run a smoke test or prediction call.

If you are unsure what input shape to send, call:

- `GET /models/{id}/inputs`

That endpoint tells you the expected ONNX input names and shapes.

---

## Common API endpoints

- `GET /models` - Discover models from disk and return registry
- `POST /models/load` - Load a model (`id`, optional `variant`)
- `POST /models/unload` - Unload a model
- `GET /models/{id}/inputs` - Inspect expected input tensors
- `GET /models/{id}/options` - List optional `voices/` and `configs/`
- `POST /models/{id}/active` - Set active `voice`/`config` in memory
- `POST /models/{id}/smoke` - Minimal forward pass check
- `POST /predict/{model_name}` - Run inference
- `GET /status` - VRAM and GPU adapter details

For detailed request/response examples, see `docs/overview.md`.

---

## Troubleshooting

### UI loads, but API calls fail
- Confirm backend is running on `127.0.0.1:8000`.
- Open `http://127.0.0.1:8000/docs` directly.

### No models are listed
- Check folder path spelling exactly: `ONNX host service/models/...`.
- Make sure `.onnx` files exist inside a model subfolder.

### PowerShell blocks venv activation
Run once in an elevated PowerShell session:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### ONNX model fails to load
- Try a different ONNX export variant (`fp16`, `int8`, etc.).
- Use `/models/{id}/inputs` to verify expected tensor names and types.

---

## Development notes

- This repo is local-workflow-first.
- Model binaries and common local artifacts are intentionally git-ignored.
- Backend dependencies are in `requirements.txt`.
- Frontend scripts live in `runtime-ui/package.json`.
- A Visual Studio solution file is not required for normal backend/UI development.

---

## License

Dual-licensed under either:

- MIT (`LICENSE-MIT`)
- Apache-2.0 (`LICENSE-APACHE`)

You may choose either license.
