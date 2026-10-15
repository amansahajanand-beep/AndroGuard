from __future__ import annotations

from fastapi import Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.errors import AppError
from app.core.security import decode_access_token
from app.db.session import engine
from app.db.repository import job_owner_id
from app.db.user_repository import get_user_by_id
from app.jobs.models import JobRecord
from app.jobs.store import get_job_store
from app.schemas.auth import UserProfile

bearer_scheme = HTTPBearer(auto_error=False)


def require_database() -> None:
    if engine is None:
        raise AppError(
            "DATABASE_UNAVAILABLE",
            "PostgreSQL is not configured.",
            http_status=503,
        )


def _user_from_token(token: str | None) -> UserProfile:
    unauthorized = AppError(
        "UNAUTHORIZED",
        "A valid bearer token is required.",
        http_status=401,
    )
    if not token:
        raise unauthorized
    payload = decode_access_token(token)
    if payload is None or not payload.get("sub") or payload.get("purpose"):
        raise unauthorized
    require_database()
    user = get_user_by_id(str(payload["sub"]))
    if user is None:
        raise unauthorized
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> UserProfile:
    return _user_from_token(credentials.credentials if credentials else None)


def get_current_user_header_or_query(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    access_token: str | None = Query(default=None),
) -> UserProfile:
    """Like ``get_current_user`` but also accepts ``?access_token=``.

    Only for routes the browser opens without custom headers (``<img>`` tags and
    the operator page). Everything else must use the Authorization header.
    """
    token = credentials.credentials if credentials else access_token
    return _user_from_token(token)


def _not_found() -> AppError:
    return AppError("NOT_FOUND", "Unknown job.", http_status=404)


def owned_job(job_id: str, user: UserProfile) -> JobRecord:
    """Load a job only if ``user`` owns it; otherwise behave as if it does not exist."""
    from app.utils.files import is_uuid

    if not is_uuid(job_id):
        raise _not_found()
    record = get_job_store().get(job_id)
    if record is None or record.user_id != user.id:
        raise _not_found()
    return record


def require_job_access(job_id: str, user: UserProfile) -> None:
    """Ownership check for job-scoped resources (files), via the job or analysis row."""
    from app.utils.files import is_uuid

    if not is_uuid(job_id):
        raise _not_found()
    record = get_job_store().get(job_id)
    owner = record.user_id if record is not None else job_owner_id(job_id)
    if owner != user.id:
        raise _not_found()
