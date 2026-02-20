import gc
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import MODELS_DIR, REGISTRY_PATH, normalize_model_path
from ..registry import scan_models_registry
from ..runtime import run_smoke_test
from ..selectors import _list_selectables, model_kind
from ..state import active_model_options, hot_models, loaded_models
from .engine import ModelLoadRequest, load_model


router = APIRouter()


def _verify_external_data(model_path: Path):
    data_files = list(model_path.parent.glob(f"{model_path.stem}.onnx_data*"))
    if not data_files:
        return
    indexed = {}
    for data_file in data_files:
        suffix = data_file.name.replace(f"{model_path.stem}.onnx_data", "")
        if suffix.startswith("_") and suffix[1:].isdigit():
            indexed[int(suffix[1:])] = data_file
    if indexed:
        max_idx = max(indexed)
        missing = [i for i in range(1, max_idx + 1) if i not in indexed]
        if missing:
            missing_names = ", ".join(f"{model_path.stem}.onnx_data_{i}" for i in missing)
            raise HTTPException(400, f"Missing external data shard(s): {missing_names}")
    for data_file in data_files:
        try:
            if not data_file.exists():
                raise HTTPException(400, f"Missing external data shard: {data_file.name}")
            size = data_file.stat().st_size
            if size == 0:
                raise HTTPException(400, f"External data shard is empty: {data_file.name}")
            with data_file.open("rb") as handle:
                header = handle.read(64)
                if header.startswith(b"version https://git-lfs.github.com/spec/v1"):
                    raise HTTPException(
                        400,
                        f"External data shard is a Git LFS pointer: {data_file.name}. Run 'git lfs pull'.",
                    )
        except Exception as e:
            if isinstance(e, HTTPException):
                raise
            raise HTTPException(400, f"External data file error: {data_file} ({e})")


@router.get("/models")
def list_models():
    return scan_models_registry()


@router.get("/models/{model_id}/options")
def get_model_options(model_id: str):
    return _list_selectables(model_id)


class ModelActiveRequest(BaseModel):
    voice: str | None = None
    config: str | None = None


@router.post("/models/{model_id}/active")
def set_model_active(model_id: str, req: ModelActiveRequest):
    options = _list_selectables(model_id)
    active = active_model_options.get(model_id, {"voice": None, "config": None})
    if req.voice is not None:
        if req.voice == "":
            active["voice"] = None
        else:
            if req.voice not in options.get("voices", []):
                raise HTTPException(400, "Voice option not found")
            active["voice"] = req.voice
    if req.config is not None:
        if req.config == "":
            active["config"] = None
        else:
            if req.config not in options.get("configs", []):
                raise HTTPException(400, "Config option not found")
            active["config"] = req.config
    active_model_options[model_id] = active
    return {"id": model_id, "active": active}


class UILoadRequest(BaseModel):
    id: str
    variant: str | None = None


@router.post("/models/load")
async def load_model_ui(req: UILoadRequest):
    model_id = req.id
    variant_id = req.variant

    # validate against registry
    if not REGISTRY_PATH.exists():
        raise HTTPException(500, "models.json missing")

    registry = scan_models_registry()
    models = registry.get("models", [])

    if model_id not in [m.get("id") for m in models]:
        raise HTTPException(404, "Model not registered")

    model = next(m for m in models if m.get("id") == model_id)
    if model.get("missing"):
        raise HTTPException(404, "Model folder missing on disk")
    if not model.get("path"):
        raise HTTPException(400, "Model has no .onnx artifacts to load")

    if variant_id:
        variants = model.get("variants") or []
        variant = next((v for v in variants if v.get("id") == variant_id), None)
        if not variant:
            raise HTTPException(404, "Variant not found")
        onnx_candidates = [a for a in (variant.get("artifacts") or []) if a.endswith(".onnx")]
        if not onnx_candidates:
            raise HTTPException(400, "Variant has no .onnx artifacts to load")
        model["path"] = onnx_candidates[0]

    # delegate to your existing loader
    model_path = (MODELS_DIR / model["path"]).resolve()
    _verify_external_data(model_path)

    providers = ["CPUExecutionProvider"] if model_kind(model_id) == "tts" else ["DmlExecutionProvider"]

    engine_req = ModelLoadRequest(
        name=model["id"],
        path=normalize_model_path(model_path),
        is_hot=model.get("autoload", False),
        providers=providers,
    )
    await load_model(engine_req)  # call existing function

    loaded_models.add(model_id)

    return {"status": "loaded", "id": model_id}


class UIUnloadRequest(BaseModel):
    id: str


@router.post("/models/unload")
def unload_model_ui(req: UIUnloadRequest):
    model_id = req.id

    if model_id not in loaded_models:
        return {
            "status": "not_loaded",
            "id": model_id,
        }

    session = hot_models.pop(model_id, None)
    if session is not None:
        del session
        gc.collect()

    loaded_models.remove(model_id)

    return {
        "status": "unloaded",
        "id": model_id,
    }


@router.get("/models/{model_id}/inputs")
def get_model_inputs(model_id: str):
    if model_id not in hot_models:
        raise HTTPException(404, "Model not loaded")

    session = hot_models[model_id]
    return {
        "inputs": [
            {
                "name": i.name,
                "shape": i.shape,
                "type": i.type,
            }
            for i in session.get_inputs()
        ]
    }


@router.post("/models/{model_id}/smoke")
def smoke_test(model_id: str):
    if model_id not in hot_models:
        raise HTTPException(404, "Model not loaded")

    session = hot_models[model_id]
    kind = model_kind(model_id)

    start = time.perf_counter()
    try:
        run_smoke_test(session, kind)
    except Exception as e:
        raise HTTPException(500, f"Smoke test failed: {e}")

    return {
        "id": model_id,
        "status": "ok",
        "runtime_ms": int((time.perf_counter() - start) * 1000),
        "note": "single forward pass",
    }

