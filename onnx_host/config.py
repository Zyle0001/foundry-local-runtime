from pathlib import Path
import os


MODELS_DIR = Path("ONNX host service") / "models"
REGISTRY_PATH = MODELS_DIR / "models.json"


def get_env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


_AUDIO_MODULE_ENABLED = get_env_bool("ENABLE_AUDIO_MODULE", default=False)

# Backward-compatible read-only snapshot at import time.
ENABLE_AUDIO_MODULE = _AUDIO_MODULE_ENABLED


def get_audio_module_enabled() -> bool:
    return _AUDIO_MODULE_ENABLED


def set_audio_module_enabled(enabled: bool) -> bool:
    global _AUDIO_MODULE_ENABLED
    _AUDIO_MODULE_ENABLED = bool(enabled)
    return _AUDIO_MODULE_ENABLED


def normalize_model_path(path: Path) -> str:
    """
    Normalize a model path for use with ONNX Runtime, including
    long-path handling on Windows.
    """
    resolved = path.resolve()
    model_path = str(resolved)
    if os.name == "nt" and len(model_path) >= 260:
        return "\\\\?\\" + model_path
    return model_path
