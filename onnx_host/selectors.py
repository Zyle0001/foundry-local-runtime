from pathlib import Path

from fastapi import HTTPException

from .config import MODELS_DIR


def model_kind(model_id: str) -> str:
    lid = model_id.lower()
    if lid.startswith("kokoro"):
        return "tts"
    if lid.startswith("whisper"):
        return "asr"
    return "llm"


def _list_selectables(model_id: str) -> dict:
    model_root = MODELS_DIR / model_id
    if not model_root.exists():
        raise HTTPException(404, "Model folder missing on disk")

    def list_names(folder: Path) -> list[str]:
        if not folder.exists() or not folder.is_dir():
            return []
        items = []
        for entry in folder.iterdir():
            if entry.is_file():
                items.append(entry.stem)
        return sorted(items, key=lambda s: s.lower())

    return {
        "voices": list_names(model_root / "voices"),
        "configs": list_names(model_root / "configs"),
    }

