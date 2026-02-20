from fastapi import APIRouter

from ..dxgi import get_vram_status


router = APIRouter()


@router.get("/status")
async def get_gpu_status():
    """Returns VRAM usage via DXGI for the first detected adapter."""
    return get_vram_status()

