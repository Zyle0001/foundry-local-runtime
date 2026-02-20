from pathlib import Path
import os


MODELS_DIR = Path("ONNX host service") / "models"
REGISTRY_PATH = MODELS_DIR / "models.json"


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

