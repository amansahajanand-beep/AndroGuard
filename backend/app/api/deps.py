from __future__ import annotations

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.errors import AppError
from app.core.security import decode_access_token
from app.db.session import engine
from app.db.user_repository import get_user_by_id
from app.schemas.auth import UserProfile

bearer_scheme = HTTPBearer(auto_error=False)


def require_database() -> None:
    if engine is None:
        raise AppError(
            "DATABASE_UNAVAILABLE",
            "PostgreSQL is not configured.",
            http_status=503,
        )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> UserProfile:
    unauthorized = AppError(
        "UNAUTHORIZED",
        "A valid bearer token is required.",
        http_status=401,
    )
    if credentials is None or not credentials.credentials:
        raise unauthorized
    payload = decode_access_token(credentials.credentials)
    if payload is None or not payload.get("sub"):
        raise unauthorized
    require_database()
    user = get_user_by_id(str(payload["sub"]))
    if user is None:
        raise unauthorized
    return user
