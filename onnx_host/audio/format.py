import numpy as np


def _as_float32(samples) -> np.ndarray:
    return np.asarray(samples, dtype=np.float32)


def to_mono(samples, channels: int | None = None) -> np.ndarray:
    """
    Collapse audio to mono.
    Accepts either shape [n] interleaved frames or [n, channels].
    """
    data = _as_float32(samples)
    if data.ndim == 2:
        return data.mean(axis=1, dtype=np.float32)

    if data.ndim == 1:
        if channels and channels > 1 and data.size >= channels and data.size % channels == 0:
            return data.reshape(-1, channels).mean(axis=1, dtype=np.float32)
        return data

    raise ValueError("Audio samples must be 1D or 2D")


def resample_linear(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    if src_rate <= 0 or dst_rate <= 0:
        raise ValueError("Sample rates must be positive")
    if samples.size == 0 or src_rate == dst_rate:
        return samples.astype(np.float32, copy=False)

    duration_seconds = samples.size / float(src_rate)
    target_length = max(1, int(round(duration_seconds * dst_rate)))

    old_index = np.linspace(0.0, 1.0, num=samples.size, endpoint=False, dtype=np.float32)
    new_index = np.linspace(0.0, 1.0, num=target_length, endpoint=False, dtype=np.float32)
    return np.interp(new_index, old_index, samples).astype(np.float32)


def convert_asr_ingress(
    samples,
    *,
    sample_rate: int,
    channels: int | None = None,
    target_sample_rate: int = 16000,
) -> np.ndarray:
    """
    Enforce the ASR boundary rule: convert to 16k mono only at ASR ingress.
    """
    mono = to_mono(samples, channels=channels)
    return resample_linear(mono, src_rate=sample_rate, dst_rate=target_sample_rate)


def compute_levels(samples) -> tuple[float, float, bool]:
    data = _as_float32(samples)
    if data.size == 0:
        return 0.0, 0.0, False

    abs_data = np.abs(data)
    peak = float(np.max(abs_data))
    rms = float(np.sqrt(np.mean(np.square(data))))
    clipped = peak >= 1.0
    return peak, rms, clipped
