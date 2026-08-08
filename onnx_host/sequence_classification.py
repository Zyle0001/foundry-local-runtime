from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from tokenizers import Tokenizer

from .config import MODELS_DIR


class SequenceAdapterError(ValueError):
    pass


_tokenizer_cache: dict[tuple[str, int], Tokenizer] = {}


def _adapter(model_id: str, expected: set[str]) -> tuple[Path, dict[str, Any]]:
    root = (MODELS_DIR / model_id).resolve()
    if root.parent != MODELS_DIR.resolve():
        raise SequenceAdapterError("Invalid model id")
    try:
        adapter = json.loads((root / "adapter.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SequenceAdapterError(f"Model '{model_id}' has no valid adapter configuration") from exc
    if str(adapter.get("task", "")).casefold() not in expected:
        raise SequenceAdapterError(f"Model '{model_id}' does not support the requested sequence task")
    return root, adapter


def _tokenizer(root: Path, adapter: dict[str, Any]) -> Tokenizer:
    path = (root / str(adapter.get("tokenizer", "tokenizer.json"))).resolve()
    if path.parent != root or not path.is_file():
        raise SequenceAdapterError("Configured tokenizer is missing")
    maximum = int(adapter.get("max_length", 512))
    key = (str(path), maximum)
    tokenizer = _tokenizer_cache.get(key)
    if tokenizer is None:
        tokenizer = Tokenizer.from_file(str(path))
        tokenizer.enable_truncation(max_length=maximum)
        tokenizer.enable_padding(
            direction="right", pad_id=int(adapter.get("pad_id", 0)),
            pad_token=str(adapter.get("pad_token", "[PAD]")),
        )
        _tokenizer_cache[key] = tokenizer
    return tokenizer


def _logits(session: Any, root: Path, adapter: dict[str, Any], pairs: list[tuple[str, str]]) -> np.ndarray:
    if not pairs or any(not isinstance(left, str) or not isinstance(right, str) for left, right in pairs):
        raise SequenceAdapterError("At least one text pair is required")
    encodings = _tokenizer(root, adapter).encode_batch(pairs)
    available = {
        "input_ids": np.asarray([item.ids for item in encodings], dtype=np.int64),
        "attention_mask": np.asarray([item.attention_mask for item in encodings], dtype=np.int64),
        "token_type_ids": np.asarray([item.type_ids for item in encodings], dtype=np.int64),
    }
    input_names = {item.name for item in session.get_inputs()}
    missing = input_names - set(available)
    if missing:
        raise SequenceAdapterError(f"Adapter cannot provide model input(s): {', '.join(sorted(missing))}")
    outputs = session.run(None, {name: available[name] for name in input_names})
    output_names = [item.name for item in session.get_outputs()]
    requested = str(adapter.get("output", "logits"))
    values = outputs[output_names.index(requested)] if requested in output_names else next(
        (item for item in outputs if item.ndim == 2), None
    )
    if values is None:
        raise SequenceAdapterError("No rank-2 classification output is available")
    return np.asarray(values, dtype=np.float32)


def _softmax(values: np.ndarray) -> np.ndarray:
    shifted = values - values.max(axis=1, keepdims=True)
    exponent = np.exp(shifted)
    return exponent / np.clip(exponent.sum(axis=1, keepdims=True), 1e-12, None)


def rerank(session: Any, model_id: str, query: str, documents: list[str]) -> list[float]:
    root, adapter = _adapter(model_id, {"reranker", "reranking", "text-ranking"})
    values = _logits(session, root, adapter, [(query, document) for document in documents])
    if values.shape[1] == 1:
        return (1.0 / (1.0 + np.exp(-values[:, 0]))).tolist()
    positive = int(adapter.get("positive_label", values.shape[1] - 1))
    return _softmax(values)[:, positive].tolist()


def nli(session: Any, model_id: str, pairs: list[tuple[str, str]]) -> list[dict[str, float]]:
    root, adapter = _adapter(model_id, {"nli", "natural-language-inference", "classification"})
    values = _softmax(_logits(session, root, adapter, pairs))
    labels = adapter.get("labels", {"0": "contradiction", "1": "entailment", "2": "neutral"})
    output = []
    for row in values:
        mapped = {str(labels.get(str(index), index)): float(score) for index, score in enumerate(row)}
        output.append({name: mapped.get(name, 0.0) for name in ("contradiction", "entailment", "neutral")})
    return output


def classify(session: Any, model_id: str, texts: list[str], labels: list[str]) -> list[dict[str, float]]:
    if not labels:
        raise SequenceAdapterError("At least one candidate label is required")
    output = []
    for text in texts:
        rows = nli(session, model_id, [(text, f"This text is about {label}.") for label in labels])
        raw = [row["entailment"] for row in rows]
        total = sum(raw)
        output.append({label: score / total if total else 0.0 for label, score in zip(labels, raw)})
    return output
