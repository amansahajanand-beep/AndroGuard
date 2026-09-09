from fastapi import APIRouter

from app.core.config import settings
from app.db.session import database_ready, engine
from app.jobs.store import store_backend
from app.modules.apk_analyzer.aapt import aapt_available
from app.modules.exploration.adb import capability_report
from app.storage.s3 import s3_ready

router = APIRouter()


@router.get("/health")
def health() -> dict:
    db_configured = engine is not None
    db_ok = database_ready() if db_configured else False
    return {
        "status": "ok",
        "analyzer_version": settings.analyzer_version,
        "schema_version": settings.schema_version,
        "aapt_available": aapt_available(),
        "dex_analysis_enabled": settings.dex_analysis_enabled,
        "database": {
            "configured": db_configured,
            "ready": db_ok,
        },
        "screenshots": {
            "backend": (
                "s3" if settings.s3_enabled else "postgres" if db_ok else "local"
            ),
            "s3_configured": settings.s3_enabled,
            "s3_ready": s3_ready() if settings.s3_enabled else False,
        },
        "jobs": {"backend": store_backend()},
        "exploration": _exploration_status(),
    }


def _exploration_status() -> dict:
    """Never let a missing adb binary break the liveness check."""
    if not settings.exploration_enabled:
        return {"enabled": False, "adb_available": False, "ready": False}
    try:
        return capability_report()
    except Exception:
        return {"enabled": True, "adb_available": False, "ready": False}
