from fastapi import APIRouter, Query

from app.core.errors import AppError
from app.db.repository import get_analysis, list_analyses
from app.db.session import engine

router = APIRouter()


@router.get("/analyses")
def list_analysis_history(limit: int = Query(default=20, ge=1, le=100)) -> dict:
    if engine is None:
        raise AppError(
            "DATABASE_UNAVAILABLE",
            "PostgreSQL is not configured.",
            http_status=503,
        )
    return {"items": list_analyses(limit)}


@router.get("/analysis/{analysis_id}")
def get_analysis_history(analysis_id: str) -> dict:
    if engine is None:
        raise AppError(
            "DATABASE_UNAVAILABLE",
            "PostgreSQL is not configured.",
            http_status=503,
        )
    result = get_analysis(analysis_id)
    if result is None:
        raise AppError("NOT_FOUND", "Analysis was not found.", http_status=404)
    return result
