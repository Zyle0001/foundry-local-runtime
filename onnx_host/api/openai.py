from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..registry import scan_models_registry
from ..state import hot_models, loaded_models


router = APIRouter(prefix="/v1", tags=["openai-compatible"])


class ChatMessage(BaseModel):
    role: str
    content: str | list[dict[str, Any]] | None = None
    name: str | None = None


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stream: bool = False
    stop: str | list[str] | None = None
    # Escape hatch for this ONNX host: callers that know their model's tensor
    # contract can provide the raw ONNX inputs while still using an
    # OpenAI-compatible route and response envelope.
    input_data: dict[str, Any] | None = None


class CompletionRequest(BaseModel):
    model: str
    prompt: str | list[str] | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stream: bool = False
    stop: str | list[str] | None = None
    input_data: dict[str, Any] | None = None


class ModelPermission(BaseModel):
    id: str = "modelperm-local"
    object: str = "model_permission"
    created: int = Field(default_factory=lambda: int(time.time()))
    allow_create_engine: bool = False
    allow_sampling: bool = True
    allow_logprobs: bool = False
    allow_search_indices: bool = False
    allow_view: bool = True
    allow_fine_tuning: bool = False
    organization: str = "*"
    group: str | None = None
    is_blocking: bool = False


def _model_record(model_id: str, loaded: bool) -> dict[str, Any]:
    return {
        "id": model_id,
        "object": "model",
        "created": 0,
        "owned_by": "foundry-local-runtime",
        "permission": [ModelPermission().dict()],
        "root": model_id,
        "parent": None,
        "loaded": loaded,
    }


def _loaded_model_or_404(model_id: str):
    session = hot_models.get(model_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Model '{model_id}' is not loaded. Load it first with POST /models/load.",
        )
    return session


def _run_raw_onnx(session, input_data: dict[str, Any]) -> str:
    try:
        outputs = session.run(None, input_data)
    except Exception as exc:  # surface ONNX Runtime validation details to the client
        raise HTTPException(status_code=400, detail=f"ONNX inference failed: {exc}") from exc
    return str(outputs)


def _unsupported_text_generation(model_id: str) -> HTTPException:
    return HTTPException(
        status_code=501,
        detail=(
            f"Model '{model_id}' is available through the OpenAI-compatible API, "
            "but this runtime does not yet include tokenizer/decoder support for free-form text generation. "
            "Send model-specific ONNX tensors in the 'input_data' field, or add a text-generation adapter for this model."
        ),
    )


def _usage(prompt_tokens: int = 0, completion_tokens: int = 0) -> dict[str, int]:
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


@router.get("/models")
def list_openai_models():
    registry = scan_models_registry()
    registry_models = registry.get("models", [])
    ids = {m.get("id") for m in registry_models if m.get("id")}
    ids.update(loaded_models)
    ids.update(hot_models.keys())
    data = [_model_record(model_id, model_id in hot_models) for model_id in sorted(ids)]
    return {"object": "list", "data": data}


@router.get("/models/{model_id}")
def get_openai_model(model_id: str):
    known_ids = {m.get("id") for m in scan_models_registry().get("models", []) if m.get("id")}
    known_ids.update(loaded_models)
    known_ids.update(hot_models.keys())
    if model_id not in known_ids:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' was not found")
    return _model_record(model_id, model_id in hot_models)


@router.post("/chat/completions")
def create_chat_completion(request: ChatCompletionRequest):
    session = _loaded_model_or_404(request.model)
    if request.stream:
        raise HTTPException(status_code=400, detail="Streaming chat completions are not supported yet")
    if request.input_data is None:
        raise _unsupported_text_generation(request.model)

    content = _run_raw_onnx(session, request.input_data)
    created = int(time.time())
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": created,
        "model": request.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": _usage(),
    }


@router.post("/completions")
def create_completion(request: CompletionRequest):
    session = _loaded_model_or_404(request.model)
    if request.stream:
        raise HTTPException(status_code=400, detail="Streaming completions are not supported yet")
    if request.input_data is None:
        raise _unsupported_text_generation(request.model)

    text = _run_raw_onnx(session, request.input_data)
    created = int(time.time())
    return {
        "id": f"cmpl-{uuid.uuid4().hex}",
        "object": "text_completion",
        "created": created,
        "model": request.model,
        "choices": [
            {
                "text": text,
                "index": 0,
                "logprobs": None,
                "finish_reason": "stop",
            }
        ],
        "usage": _usage(),
    }
