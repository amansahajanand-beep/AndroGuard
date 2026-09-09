from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import AppError, app_error_handler, error_body, unhandled_error_handler
from app.core.logging import setup_logging
from app.db.session import init_db

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        init_db()
    except Exception:
        logger.exception("Failed to initialize PostgreSQL schema.")
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.analyzer_version,
    description="Upload an Android APK and receive structured manifest, component, DEX code-analysis, and image metadata.",
    lifespan=lifespan,
)

app.include_router(api_router, prefix="/api/v1")


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    return response


@app.exception_handler(AppError)
async def handle_app_error(request: Request, exc: AppError):
    return await app_error_handler(request, exc)


@app.exception_handler(RequestValidationError)
async def handle_validation(request: Request, exc: RequestValidationError):
    request_id = getattr(request.state, "request_id", None)
    if request.url.path.endswith("/analyze"):
        return JSONResponse(
            status_code=400,
            content=error_body("INVALID_FILE", "The request is missing a valid APK upload.", request_id),
        )
    body = error_body("VALIDATION_ERROR", "The request payload is invalid.", request_id)
    body["error"]["details"] = [
        {
            "field": ".".join(str(part) for part in error["loc"][1:]) or "body",
            "message": error["msg"],
        }
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content=body)


@app.exception_handler(Exception)
async def handle_unhandled(request: Request, exc: Exception):
    return await unhandled_error_handler(request, exc)
