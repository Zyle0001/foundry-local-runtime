from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from tokenizers import Tokenizer

from .config import MODELS_DIR


class EmbeddingAdapterError(ValueError):
    pass


_tokenizer_cache: dict[tuple[str, int], Tokenizer] = {}


def _load_adapter(model_id: str) -> tuple[Path, dict[str, Any]]:
    model_root = (MODELS_DIR / model_id).resolve()
    models_root = MODELS_DIR.resolve()
    if model_root.parent != models_root:
        raise EmbeddingAdapterError("Invalid model id")

    adapter_path = model_root / "adapter.json"
    if not adapter_path.exists():
        raise EmbeddingAdapterError(
            f"Model '{model_id}' does not provide an embedding adapter configuration"
        )

    try:
        adapter = json.loads(adapter_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EmbeddingAdapterError(f"Invalid embedding adapter configuration: {exc}") from exc

    if str(adapter.get("task", "")).lower() not in {"embedding", "text-embedding"}:
        raise EmbeddingAdapterError(f"Model '{model_id}' is not configured for text embeddings")
    if str(adapter.get("pooling", "mean")).lower() != "mean":
        raise EmbeddingAdapterError("Only mean pooling is supported")
    if adapter.get("normalize", True) is not True:
        raise EmbeddingAdapterError("Embedding adapters must enable L2 normalization")
    return model_root, adapter


def _load_tokenizer(model_root: Path, adapter: dict[str, Any]) -> tuple[Tokenizer, int]:
    tokenizer_name = str(adapter.get("tokenizer", "tokenizer.json"))
    tokenizer_path = (model_root / tokenizer_name).resolve()
    if tokenizer_path.parent != model_root or not tokenizer_path.exists():
        raise EmbeddingAdapterError(f"Tokenizer file not found: {tokenizer_name}")

    max_length = int(adapter.get("max_length", 256))
    if max_length <= 0:
        raise EmbeddingAdapterError("max_length must be positive")

    cache_key = (str(tokenizer_path), max_length)
    tokenizer = _tokenizer_cache.get(cache_key)
    if tokenizer is None:
        tokenizer = Tokenizer.from_file(str(tokenizer_path))
        tokenizer.enable_truncation(max_length=max_length)
        tokenizer.enable_padding(
            direction="right",
            pad_id=int(adapter.get("pad_id", 0)),
            pad_token=str(adapter.get("pad_token", "[PAD]")),
        )
        _tokenizer_cache[cache_key] = tokenizer
    return tokenizer, max_length


def mean_pool_and_normalize(
    token_embeddings: np.ndarray,
    attention_mask: np.ndarray,
) -> np.ndarray:
    if token_embeddings.ndim != 3:
        raise EmbeddingAdapterError(
            f"Expected rank-3 token embeddings, received shape {token_embeddings.shape}"
        )
    if attention_mask.shape != token_embeddings.shape[:2]:
        raise EmbeddingAdapterError(
            "Attention-mask shape does not match the token-embedding batch and sequence dimensions"
        )

    expanded_mask = attention_mask.astype(np.float32)[..., None]
    pooled = (token_embeddings.astype(np.float32) * expanded_mask).sum(axis=1)
    pooled /= np.clip(expanded_mask.sum(axis=1), 1e-9, None)
    norms = np.linalg.norm(pooled, axis=1, keepdims=True)
    return pooled / np.clip(norms, 1e-12, None)


def create_embeddings(
    session: Any,
    model_id: str,
    texts: list[str],
) -> tuple[np.ndarray, list[int]]:
    if not texts:
        raise EmbeddingAdapterError("At least one input string is required")
    if any(not isinstance(text, str) for text in texts):
        raise EmbeddingAdapterError("Embedding input must contain only strings")

    model_root, adapter = _load_adapter(model_id)
    tokenizer, _ = _load_tokenizer(model_root, adapter)
    encodings = tokenizer.encode_batch(texts)

    input_ids = np.asarray([encoding.ids for encoding in encodings], dtype=np.int64)
    attention_mask = np.asarray([encoding.attention_mask for encoding in encodings], dtype=np.int64)
    token_type_ids = np.asarray([encoding.type_ids for encoding in encodings], dtype=np.int64)

    available = {
        "input_ids": input_ids,
        "attention_mask": attention_mask,
        "token_type_ids": token_type_ids,
    }
    input_names = {item.name for item in session.get_inputs()}
    missing = input_names.difference(available)
    if missing:
        raise EmbeddingAdapterError(
            f"Embedding adapter cannot provide model input(s): {', '.join(sorted(missing))}"
        )

    outputs = session.run(None, {name: available[name] for name in input_names})
    output_name = str(adapter.get("output", "last_hidden_state"))
    output_names = [item.name for item in session.get_outputs()]
    if output_name in output_names:
        token_embeddings = outputs[output_names.index(output_name)]
    else:
        token_embeddings = next((output for output in outputs if output.ndim == 3), None)
        if token_embeddings is None:
            raise EmbeddingAdapterError(
                f"Embedding output '{output_name}' was not found and no rank-3 output is available"
            )

    embeddings = mean_pool_and_normalize(token_embeddings, attention_mask)
    expected_dimensions = adapter.get("dimensions")
    if expected_dimensions is not None and embeddings.shape[1] != int(expected_dimensions):
        raise EmbeddingAdapterError(
            f"Expected {expected_dimensions} embedding dimensions, received {embeddings.shape[1]}"
        )

    token_counts = attention_mask.sum(axis=1).astype(int).tolist()
    return embeddings, token_counts
