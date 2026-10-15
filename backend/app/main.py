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
    if request.url.path.endswith(("/analyze", "/analyze-apk")):
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


def _cli(argv: list[str] | None = None) -> int:
    """Lightweight CLI entry for debug commands (does not start the API server).

    Examples::

        python -m app.main --inspect-ui
        python -m app.main --screenshot
        python -m app.main --compare-screenshot
        python -m app.main --explore --package com.example.app
        python -m app.main --explore-ads --package com.example.app
        python -m app.main --detect-ad --image path/to/shot.png
    """
    import argparse
    import sys

    from app.workers.detect_ad_cli import run_detect_ad_cli
    from app.workers.explore_cli import run_explore_cli
    from app.workers.inspect_ui import inspect_ui
    from app.workers.screenshot_cli import run_screenshot_cli

    parser = argparse.ArgumentParser(
        prog="python -m app.main",
        description="AndroGuard backend helpers (API is started via uvicorn).",
    )
    parser.add_argument(
        "--inspect-ui",
        action="store_true",
        help="Dump the UI hierarchy of a connected Android device via UIAutomator.",
    )
    parser.add_argument(
        "--screenshot",
        action="store_true",
        help="Capture a device screenshot (Phase 3).",
    )
    parser.add_argument(
        "--compare-screenshot",
        action="store_true",
        help="Compare two screenshots / visual states (Phase 3).",
    )
    parser.add_argument(
        "--explore",
        action="store_true",
        help="Run deterministic UI exploration (Phase 4).",
    )
    parser.add_argument(
        "--explore-ads",
        action="store_true",
        help="Run multi-pass advertisement placement discovery (Phase 5).",
    )
    parser.add_argument(
        "--detect-ad",
        action="store_true",
        help="Detect advertisements in a screenshot (Phase 6).",
    )
    args, remainder = parser.parse_known_args(argv)
    if args.inspect_ui:
        return inspect_ui(["--inspect-ui", *remainder])
    if args.screenshot:
        return run_screenshot_cli(["--screenshot", *remainder])
    if args.compare_screenshot:
        return run_screenshot_cli(["--compare-screenshot", *remainder])
    if args.detect_ad:
        return run_detect_ad_cli(["--detect-ad", *remainder])
    if args.explore_ads:
        return run_explore_cli(["--explore-ads", *remainder])
    if args.explore:
        return run_explore_cli(["--explore", *remainder])
    parser.print_help()
    print("\nStart the API with: uvicorn app.main:app --reload --host 0.0.0.0 --port 8000")
    return 0 if argv in (None, []) else 2

if __name__ == "__main__":
    import sys

    sys.exit(_cli())
