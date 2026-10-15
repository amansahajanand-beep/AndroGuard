from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import ValidationError

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.errors import AppError
from app.schemas.analysis import AppSubmission
from app.schemas.auth import UserProfile
from app.services.analysis_service import analyze_apk
from app.services.ai_report import attach_ai_review
from app.services.artifacts import publish_static_artifacts
from app.storage.local import LocalTempStorage
from app.utils.files import new_job_id, safe_filename
from app.utils.hashing import stream_to_file

logger = logging.getLogger(__name__)
router = APIRouter()
storage = LocalTempStorage()

ALLOWED_SUFFIXES = {".apk"}


async def read_policy_upload(upload: UploadFile | None) -> tuple[str | None, str | None]:
    """Text of an uploaded privacy policy, or (None, reason). Never fails the audit."""
    if upload is None or not upload.filename:
        return None, None
    from app.services.policy_text import MAX_BYTES, extract_policy_text

    try:
        data = await upload.read(MAX_BYTES + 1)
    finally:
        await upload.close()
    if len(data) > MAX_BYTES:
        return None, "The privacy policy file is too large to read."
    return extract_policy_text(upload.filename, data)


def _validate_filename(filename: str | None) -> str:
    if not filename:
        raise AppError("INVALID_FILE", "The uploaded file is missing a name.")
    name = safe_filename(filename, fallback="upload.apk")
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise AppError("INVALID_FILE", "The uploaded file is not a valid Android APK.")
    return name


def _build_submission(
    app_name: str | None,
    app_description: str | None,
    privacy_policy: str | None,
    play_store_url: str | None,
    policy_text: str | None = None,
    policy_error: str | None = None,
) -> AppSubmission:
    try:
        return AppSubmission(
            app_name=app_name,
            app_description=app_description,
            privacy_policy=privacy_policy,
            play_store_url=play_store_url,
            privacy_policy_text=policy_text,
            privacy_policy_error=policy_error,
        )
    except ValidationError as exc:
        field = ".".join(str(part) for part in exc.errors()[0]["loc"]) or "submission"
        raise AppError(
            "INVALID_SUBMISSION",
            f"Field '{field}' is invalid: {exc.errors()[0]['msg']}",
        ) from exc


@router.post("/analyze")
async def analyze(
    file: UploadFile = File(...),
    app_name: str | None = Form(default=None),
    app_description: str | None = Form(default=None),
    privacy_policy: str | None = Form(default=None),
    play_store_url: str | None = Form(default=None),
    privacy_policy_file: UploadFile | None = File(default=None),
    user: UserProfile = Depends(get_current_user),
) -> dict:
    original_name = _validate_filename(file.filename)
    policy_text, policy_error = await read_policy_upload(privacy_policy_file)
    submission = _build_submission(
        app_name, app_description, privacy_policy, play_store_url, policy_text, policy_error
    )
    job_id = new_job_id()
    apk_path = storage.apk_path(job_id)
    try:
        size, sha256 = await stream_to_file(
            file.read,
            apk_path,
            settings.max_apk_size_bytes,
        )
        logger.info("Accepted APK job=%s size=%s sha256=%s", job_id, size, sha256)
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    analyze_apk,
                    apk_path,
                    file_name=original_name,
                    file_size=size,
                    sha256=sha256,
                    job_id=job_id,
                    storage=storage,
                    submission=submission,
                ),
                timeout=settings.analysis_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise AppError(
                "ANALYSIS_TIMEOUT",
                "APK analysis exceeded the allowed time limit.",
                http_status=504,
            ) from exc
        result.data.analysis.id = job_id
        # Network + model calls: keep them off the event loop.
        await asyncio.to_thread(
            attach_ai_review,
            result,
            policy_text=submission.privacy_policy_text,
            policy_error=submission.privacy_policy_error,
        )
        publish_static_artifacts(job_id, result, storage, user_id=user.id)
        return result.model_dump()
    finally:
        await file.close()
        storage.delete_apk(job_id)
