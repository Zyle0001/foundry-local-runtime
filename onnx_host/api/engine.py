from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..runtime import create_session
from ..state import hot_models


router = APIRouter()


class ModelLoadRequest(BaseModel):
    name: str
    path: str
    is_hot: bool = False
    providers: list[str] | None = None


@router.post("/Load")
async def load_model(request: ModelLoadRequest):
    try:
        if not Path(request.path).exists():
            raise HTTPException(
                status_code=404,
                detail=f"Model file not found: {request.path}",
            )

        session = create_session(request.path, request.providers)
        hot_models[request.name] = session
        return {"status": "success", "message": f"Model {request.name} loaded."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/predict/{model_name}")
async def predict(model_name: str, input_data: dict):
    if model_name not in hot_models:
        raise HTTPException(status_code=404, detail="Model not loaded")

    session = hot_models[model_name]
    outputs = session.run(None, input_data)
    return {"output": str(outputs)}

