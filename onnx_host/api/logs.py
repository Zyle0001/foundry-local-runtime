from fastapi import APIRouter, Query

from ..logs import clear_logs, get_recent_logs


router = APIRouter()


@router.get("/logs")
def get_logs(
    limit: int = Query(250, ge=1, le=2000),
    level: str | None = Query(default=None),
    include_access: bool = Query(default=False),
):
    return {
        "logs": get_recent_logs(
            limit=limit,
            min_level=level,
            include_access_logs=include_access,
        )
    }


@router.post("/logs/clear")
def clear_logs_endpoint():
    clear_logs()
    return {"status": "cleared"}
