from .audio import router as audio_router
from .engine import router as engine_router
from .logs import router as logs_router
from .models import router as models_router
from .status import router as status_router

__all__ = [
    "audio_router",
    "engine_router",
    "logs_router",
    "models_router",
    "status_router",
]
