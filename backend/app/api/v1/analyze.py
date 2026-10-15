from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import ValidationError

from app.core.config import settings
from app.core.errors import AppError
from app.db.repository import persist_analysis, persist_screenshots
from app.db.session import engine
from app.schemas.analysis import AppSubmission
from app.services.analysis_service import analyze_apk
from app.storage.images import read_local_screenshots
from app.storage.local import LocalTempStorage
from app.storage.s3 import upload_screenshots
from app.utils.files import new_job_id, safe_filename
from app.utils.hashing import stream_to_file

logger = logging.getLogger(__name__)
router = APIRouter()
storage = LocalTempStorage()

ALLOWED_SUFFIXES = {".apk"}


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
) -> AppSubmission:
    try:
        return AppSubmission(
            app_name=app_name,
            app_description=app_description,
            privacy_policy=privacy_policy,
            play_store_url=play_store_url,
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
) -> dict:
    original_name = _validate_filename(file.filename)
    submission = _build_submission(app_name, app_description, privacy_policy, play_store_url)
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
        blobs = read_local_screenshots(
            job_id,
            [item.file_name for item in result.data.screenshots],
            storage,
        )
        if settings.s3_enabled and blobs:
            try:
                formats = {item.file_name: item.format for item in result.data.screenshots}
                urls = upload_screenshots(job_id, blobs, formats)
                for item in result.data.screenshots:
                    if item.file_name in urls:
                        item.url = urls[item.file_name]
            except Exception:
                logger.exception("Could not upload screenshots for %s to S3", job_id)
                result.data.analysis.warnings.append(
                    "Analysis completed but screenshots were not uploaded to S3."
                )
        if engine is not None:
            try:
                persist_analysis(job_id, result)
                persist_screenshots(job_id, result.data.screenshots, blobs)
                result.data.analysis.persisted = True
            except Exception:
                logger.exception("Could not save analysis %s to PostgreSQL", job_id)
                result.data.analysis.warnings.append(
                    "Analysis completed but was not saved to the database."
                )
        return result.model_dump()
    finally:
        await file.close()
        storage.delete_apk(job_id)
