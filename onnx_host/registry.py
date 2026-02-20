import json
from pathlib import Path

from .config import MODELS_DIR, REGISTRY_PATH
from .state import loaded_models


KNOWN_VARIANT_SUFFIXES = {
    "fp32", "fp16", "bf16", "int8", "int4", "int3", "int2",
    "q8", "q6", "q5", "q4", "q3", "q2", "uint8"
}


def _variant_id_from_filename(file_path: Path) -> str:
    stem = file_path.stem
    if "_" in stem:
        suffix = stem.rsplit("_", 1)[-1].lower()
        if suffix in KNOWN_VARIANT_SUFFIXES:
            return suffix
    return stem


def _collect_artifacts(onnx_path: Path) -> list[str]:
    artifacts = [onnx_path]
    for extra in onnx_path.parent.glob(f"{onnx_path.stem}.onnx_data*"):
        artifacts.append(extra)
    return [str(p.relative_to(MODELS_DIR)) for p in artifacts]


def scan_models_registry() -> dict:
    registry: dict = {"models": []}
    if REGISTRY_PATH.exists():
        try:
            registry = json.loads(REGISTRY_PATH.read_text())
        except Exception:
            registry = {"models": []}

    existing_by_id = {m.get("id"): m for m in registry.get("models", []) if m.get("id")}
    found_ids = set()
    models_out = []

    if MODELS_DIR.exists():
        for model_dir in sorted([p for p in MODELS_DIR.iterdir() if p.is_dir()], key=lambda p: p.name.lower()):
            model_id = model_dir.name
            found_ids.add(model_id)

            onnx_files = list(model_dir.rglob("*.onnx"))
            variants_map: dict[str, list[str]] = {}
            for onnx_path in onnx_files:
                variant_id = _variant_id_from_filename(onnx_path)
                variants_map.setdefault(variant_id, []).extend(_collect_artifacts(onnx_path))

            variants = [
                {
                    "id": vid,
                    "artifacts": sorted(set(artifacts))
                }
                for vid, artifacts in sorted(variants_map.items(), key=lambda item: item[0])
            ]

            model_entry: dict = {
                "id": model_id,
                "root": str(model_dir.relative_to(MODELS_DIR)),
                "path": None,
                "variants": variants,
                "missing": False,
                "loaded": model_id in loaded_models
            }

            for variant in variants:
                onnx_artifacts = [a for a in variant["artifacts"] if a.endswith(".onnx")]
                if onnx_artifacts:
                    model_entry["path"] = onnx_artifacts[0]
                    break

            models_out.append(model_entry)

    for model_id, model in existing_by_id.items():
        if model_id not in found_ids:
            model["missing"] = True
            model["loaded"] = False
            models_out.append(model)

    registry = {"models": models_out}
    REGISTRY_PATH.write_text(json.dumps(registry, indent=2))
    return registry

