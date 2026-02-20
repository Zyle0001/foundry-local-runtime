from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import engine_router, logs_router, models_router, status_router
from .logs import setup_runtime_logging


setup_runtime_logging()

app = FastAPI(title="Minimal ONNX Host")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(engine_router)
app.include_router(logs_router)
app.include_router(models_router)
app.include_router(status_router)
