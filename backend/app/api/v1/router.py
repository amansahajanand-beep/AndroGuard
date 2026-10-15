from fastapi import APIRouter

from app.api.v1.analyze import router as analyze_router
from app.api.v1.auth import router as auth_router
from app.api.v1.files import router as files_router
from app.api.v1.health import router as health_router
from app.api.v1.history import router as history_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(auth_router, tags=["auth"])
api_router.include_router(analyze_router, tags=["analysis"])
api_router.include_router(history_router, tags=["analysis"])
api_router.include_router(files_router, tags=["files"])
