from __future__ import annotations

import logging
from typing import Any

import numpy as np

from ..selectors import model_kind
from ..state import hot_models


LOGGER = logging.getLogger(__name__)


def _dtype_for_input(input_type: str):
    t = (input_type or "").lower()
    if "int64" in t:
        return np.int64
    if "int32" in t:
        return np.int32
    if "int8" in t:
        return np.int8
    if "bool" in t:
        return np.bool_
    if "float16" in t:
        return np.float16
    if "double" in t or "float64" in t:
        return np.float64
    return np.float32


def _shape_for_input(shape) -> list[int]:
    cooked: list[int] = []
    for d in shape:
        if isinstance(d, int):
            cooked.append(1 if d < 0 else d)
        else:
            cooked.append(1)
    return cooked


def _resolve_loaded_model(kind: str, preferred_model_id: str | None = None) -> tuple[str, Any] | None:
    if preferred_model_id:
        session = hot_models.get(preferred_model_id)
        if session is not None and model_kind(preferred_model_id) == kind:
            return preferred_model_id, session

    for candidate_id, session in hot_models.items():
        if model_kind(candidate_id) == kind:
            return candidate_id, session
    return None


def _build_feature_tensor(samples_16k_mono: np.ndarray, shape: list[int]) -> np.ndarray:
    t = shape[2] if len(shape) >= 3 else max(16, int(samples_16k_mono.size / 200))
    t = max(1, int(t))
    features = np.zeros((1, 80, t), dtype=np.float32)
    if samples_16k_mono.size == 0:
        return features

    abs_samples = np.abs(samples_16k_mono)
    chunk = max(1, int(abs_samples.size / t))
    for idx in range(t):
        start = idx * chunk
        end = min(abs_samples.size, start + chunk)
        energy = float(abs_samples[start:end].mean()) if end > start else 0.0
        features[0, :, idx] = energy
    return features


def _fit_waveform_tensor(samples: np.ndarray, shape: list[int]) -> np.ndarray:
    if len(shape) == 1:
        target = shape[0]
        out = np.zeros((target,), dtype=np.float32)
        copy_n = min(target, samples.size)
        out[:copy_n] = samples[:copy_n]
        return out

    if len(shape) == 2:
        target = shape[1]
        out = np.zeros((1, target), dtype=np.float32)
        copy_n = min(target, samples.size)
        out[0, :copy_n] = samples[:copy_n]
        return out

    out = np.zeros(shape, dtype=np.float32)
    flat = out.reshape(-1)
    copy_n = min(flat.size, samples.size)
    flat[:copy_n] = samples[:copy_n]
    return out


def ingest_asr_frame(
    samples_16k_mono: np.ndarray,
    *,
    model_id: str | None = None,
) -> dict[str, object]:
    resolved = _resolve_loaded_model("asr", preferred_model_id=model_id)
    if resolved is None:
        return {"status": "no_model"}

    resolved_id, session = resolved
    frame = np.asarray(samples_16k_mono, dtype=np.float32).reshape(-1)
    inputs: dict[str, np.ndarray] = {}

    try:
        for inp in session.get_inputs():
            lname = inp.name.lower()
            dtype = _dtype_for_input(inp.type)
            shape = _shape_for_input(inp.shape)

            if inp.name == "input_features":
                value = _build_feature_tensor(frame, shape).astype(dtype)
            elif "audio" in lname or "wave" in lname or "sample" in lname:
                value = _fit_waveform_tensor(frame, shape).astype(dtype)
            elif "length" in lname or lname.endswith("len") or "_len" in lname:
                value = np.array([frame.size], dtype=np.int64).astype(dtype)
            elif inp.name == "input_ids":
                value = np.array([[1]], dtype=np.int64).astype(dtype)
            elif "attention_mask" in lname:
                value = np.array([[1]], dtype=np.int64).astype(dtype)
            else:
                value = np.zeros(shape, dtype=dtype)
            inputs[inp.name] = value

        outputs = session.run(None, inputs)
        output_shapes = [list(np.asarray(out).shape) for out in outputs]
        return {
            "status": "ok",
            "model_id": resolved_id,
            "output_shapes": output_shapes,
        }
    except Exception as exc:
        LOGGER.debug("ASR adapter ingest failed for %s", resolved_id, exc_info=True)
        return {
            "status": "error",
            "model_id": resolved_id,
            "error": str(exc),
        }


def _tokenize_text(text: str, *, max_tokens: int = 128) -> np.ndarray:
    raw = list(text.encode("utf-8")[:max_tokens])
    if not raw:
        raw = [1]
    return np.asarray([[(b % 255) + 1 for b in raw]], dtype=np.int64)


def _select_audio_output(outputs: list[Any]) -> np.ndarray:
    for out in outputs:
        arr = np.asarray(out)
        if arr.size == 0:
            continue
        if np.issubdtype(arr.dtype, np.floating):
            audio = arr.astype(np.float32).reshape(-1)
            if audio.size > 0:
                return audio
        if np.issubdtype(arr.dtype, np.integer):
            audio = arr.astype(np.float32).reshape(-1)
            max_abs = float(np.max(np.abs(audio)))
            if max_abs > 0:
                audio = audio / max_abs
            if audio.size > 0:
                return audio
    return np.zeros((0,), dtype=np.float32)


def synthesize_tts_signal(
    *,
    text: str,
    model_id: str | None = None,
) -> tuple[np.ndarray, dict[str, object]]:
    resolved = _resolve_loaded_model("tts", preferred_model_id=model_id)
    if resolved is None:
        return np.zeros((0,), dtype=np.float32), {"status": "no_model"}

    resolved_id, session = resolved
    token_ids = _tokenize_text(text)
    token_len = token_ids.shape[1]
    inputs: dict[str, np.ndarray] = {}

    try:
        for inp in session.get_inputs():
            lname = inp.name.lower()
            dtype = _dtype_for_input(inp.type)
            shape = _shape_for_input(inp.shape)

            if inp.name == "input_ids":
                value = token_ids.astype(dtype)
            elif inp.name == "style":
                value = np.zeros((1, 256), dtype=np.float32).astype(dtype)
            elif inp.name == "speed":
                value = np.array([1.0], dtype=np.float32).astype(dtype)
            elif "length" in lname or lname.endswith("len") or "_len" in lname:
                value = np.array([token_len], dtype=np.int64).astype(dtype)
            elif "attention_mask" in lname:
                value = np.ones((1, token_len), dtype=np.int64).astype(dtype)
            else:
                value = np.zeros(shape, dtype=dtype)
            inputs[inp.name] = value

        outputs = session.run(None, inputs)
        audio = _select_audio_output(outputs)
        if audio.size == 0:
            return audio, {
                "status": "no_audio_output",
                "model_id": resolved_id,
                "output_shapes": [list(np.asarray(out).shape) for out in outputs],
            }

        peak = float(np.max(np.abs(audio)))
        if peak > 1e-6:
            audio = (audio / peak) * 0.8

        return audio.astype(np.float32, copy=False), {
            "status": "ok",
            "model_id": resolved_id,
            "sample_count": int(audio.size),
        }
    except Exception as exc:
        LOGGER.debug("TTS adapter synth failed for %s", resolved_id, exc_info=True)
        return np.zeros((0,), dtype=np.float32), {
            "status": "error",
            "model_id": resolved_id,
            "error": str(exc),
        }
