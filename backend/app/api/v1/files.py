from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.api.deps import get_current_user_header_or_query, require_job_access
from app.core.errors import AppError
from app.schemas.auth import UserProfile
from app.storage.images import load_screenshot
from app.storage.local import LocalTempStorage
from app.utils.files import is_uuid, safe_filename

router = APIRouter()
storage = LocalTempStorage()


@router.get("/files/{job_id}/{file_name}")
def get_file(
    job_id: str,
    file_name: str,
    user: UserProfile = Depends(get_current_user_header_or_query),
) -> Response:
    require_job_access(job_id, user)
    if not is_uuid(job_id):
        raise AppError("INVALID_FILE", "Unknown file.")
    name = safe_filename(file_name)
    if name != file_name or "/" in file_name or "\\" in file_name or ".." in file_name:
        raise AppError("INVALID_FILE", "Unknown file.")
    loaded = load_screenshot(job_id, name, storage)
    if loaded is None:
        raise AppError("INVALID_FILE", "Unknown file.", http_status=404)
    data, content_type = loaded
    return Response(content=data, media_type=content_type)
