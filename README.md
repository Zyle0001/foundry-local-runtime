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


### OpenAI-compatible API for Odysseus and other clients

This runtime also exposes a small OpenAI-compatible surface under `/v1`, so tools that let you configure a custom OpenAI base URL can discover and call loaded local models:

- `GET /v1/models` - List discovered local models in an OpenAI-style response
- `GET /v1/models/{id}` - Inspect one model
- `POST /v1/chat/completions` - OpenAI-style chat completion envelope
- `POST /v1/completions` - OpenAI-style text completion envelope
- `POST /v1/embeddings` - OpenAI-style normalized text embeddings for configured embedding models
- `POST /v1/rerank` - score query/document pairs with a configured reranker
- `POST /v1/nli` - return contradiction, entailment, and neutral scores for text pairs
- `POST /v1/classify` - zero-shot label scoring through a configured NLI model

For Odysseus, use:

```text
Base URL: http://127.0.0.1:8000/v1
API key: local-anything
Model ID: the same id shown by GET /models or GET /v1/models
```

Important: ONNX files do not include a universal tokenizer/decoder contract. Until a model-specific text-generation adapter is added, chat/completion requests must include an `input_data` object containing the raw ONNX input tensors for the loaded model. Without `input_data`, the endpoint returns a clear `501` explaining that text generation needs an adapter.

Example raw-tensor chat request:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/v1/chat/completions `
  -ContentType "application/json" `
  -Body '{"model":"your-model-id","messages":[{"role":"user","content":"hello"}],"input_data":{"input_ids":[[1]],"attention_mask":[[1]]}}'
```

For detailed request/response examples, see `docs/overview.md`.

### MiniLM embeddings

Install the pinned Apache-2.0 `sentence-transformers/all-MiniLM-L6-v2` ONNX model:

```powershell
pwsh -File scripts/Install-MiniLM.ps1
```

Load it through the UI or API, then request embeddings:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/models/load `
  -ContentType "application/json" `
  -Body '{"id":"all-MiniLM-L6-v2"}'

Invoke-RestMethod -Method Post http://127.0.0.1:8000/v1/embeddings `
  -ContentType "application/json" `
  -Body '{"model":"all-MiniLM-L6-v2","input":["First sentence","Second sentence"]}'
```

The adapter tokenizes to at most 256 tokens, performs attention-mask-aware mean pooling, and L2-normalizes the resulting 384-dimensional vectors. The model runs on CPU by default because it is small and avoids unnecessary DirectML transfer overhead.

### Cognitive sequence models

Install the pinned Apache-2.0 quantized AVX2 models explicitly:

```powershell
pwsh -File scripts/Install-Reranker.ps1
pwsh -File scripts/Install-Nli.ps1
```

The installers pin upstream revisions and verify the ONNX SHA-256 before replacing the destination. They do not run during server startup. Sequence-classification adapters tokenize text pairs and run on CPU; reranking returns one bounded score per document, while NLI provides the fixed `contradiction`, `entailment`, and `neutral` label mapping used by zero-shot classification.

### Optional audio module (Phase 2 in progress)

Enable audio control-plane endpoints by setting:

```powershell
$env:ENABLE_AUDIO_MODULE = "true"
uvicorn onnx_host.main:app --reload
```

Endpoints:

- `GET /audio/devices` - List capture/playback devices (best effort)
- `POST /audio/defaults` - Set default input/output device ids
- `GET /audio/routes` - List route graph state
- `POST /audio/routes` - Create/update route graph nodes
- `POST /audio/policy` - Set duplex policy mode
- `DELETE /audio/routes/{route_id}` - Remove route
- `POST /audio/streams/{stream_id}/start` - Start stream runtime
- `POST /audio/streams/{stream_id}/stop` - Stop stream runtime
- `POST /audio/streams/{stream_id}/pause` - Pause stream runtime
- `POST /audio/controls` - Update gain/mute/push-to-talk state
- `GET /audio/meters` - Read per-stream live level snapshots

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

### Dependency audit status

As of 2026-08-08, `npm audit` reports one low-severity transitive `cookie <0.7.0` advisory through the latest available `@sveltejs/kit` (`2.70.2`). npm expands this to three low-severity dependency entries and suggests invalid major downgrades to historical SvelteKit and adapter versions. No forced or breaking audit fix has been applied; recheck when SvelteKit publishes a release using a patched `cookie` dependency.

---

## License

Dual-licensed under either:

- MIT (`LICENSE-MIT`)
- Apache-2.0 (`LICENSE-APACHE`)

You may choose either license.
