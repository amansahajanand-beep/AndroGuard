from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def error_body(code: str, message: str, request_id: str | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if request_id:
        error["request_id"] = request_id
    return {"error": error}


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=exc.http_status,
        content=error_body(exc.code, exc.message, request_id),
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=500,
        content=error_body(
            "ANALYZER_ERROR",
            "An internal analyzer error occurred.",
            request_id,
        ),
    )
