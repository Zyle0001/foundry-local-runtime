from fastapi import APIRouter

from ..config import get_audio_module_enabled
from ..dxgi import get_vram_status


router = APIRouter()


@router.get("/status")
async def get_gpu_status():
    """Returns VRAM usage via DXGI for the first detected adapter."""
    payload = get_vram_status()
    payload["features"] = {
        "audio_module_enabled": get_audio_module_enabled(),
    }
    return payload
