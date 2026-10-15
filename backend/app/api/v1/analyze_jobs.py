from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile

from app.api.v1.analyze import _build_submission, _validate_filename
from app.core.config import settings
from app.core.errors import AppError
from app.jobs.models import JobRecord, JobStatus
from app.jobs.store import get_job_store
from app.services.analysis_pipeline import run_analysis_job
from app.storage.local import LocalTempStorage
from app.utils.files import is_uuid, new_job_id
from app.utils.hashing import stream_to_file

logger = logging.getLogger(__name__)
router = APIRouter()
storage = LocalTempStorage()

# Emulator work must not run in the request; hand it to a worker thread.
_executor = ThreadPoolExecutor(
    max_workers=max(1, settings.job_max_workers),
    thread_name_prefix="analysis-job",
)


def _submit(job_id: str, **kwargs) -> None:
    future = _executor.submit(run_analysis_job, job_id, **kwargs)

    def _log_result(done) -> None:
        exc = done.exception()
        if exc is not None:
            # run_analysis_job already recorded the failure on the job record.
            logger.error("Job %s ended with %s: %s", job_id, type(exc).__name__, exc)

    future.add_done_callback(_log_result)


@router.post("/analyze-apk")
async def create_analysis_job(
    file: UploadFile = File(...),
    app_name: str | None = Form(default=None),
    app_description: str | None = Form(default=None),
    privacy_policy: str | None = Form(default=None),
    play_store_url: str | None = Form(default=None),
    explore: bool = Form(default=True),
) -> dict:
    """Accept an APK and run static analysis plus emulator exploration in the background.

    Returns immediately with a job id; poll ``GET /analyze-apk/{job_id}``.
    The uploaded APK is kept on disk for the worker and removed when the job ends.
    """
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
    except Exception:
        storage.delete_job(job_id)
        raise
    finally:
        await file.close()

    logger.info("Queued analysis job=%s size=%s explore=%s", job_id, size, explore)
    store = get_job_store()
    record = JobRecord(
        id=job_id,
        status=JobStatus.QUEUED,
        file_name=original_name,
        file_size=size,
        sha256=sha256,
        exploration_requested=bool(explore),
    )
    try:
        store.create(record)
    except Exception:
        storage.delete_job(job_id)
        logger.exception("Could not create job record %s", job_id)
        raise AppError(
            "JOB_CREATE_FAILED",
            "The analysis job could not be created.",
            http_status=500,
        )

    _submit(
        job_id,
        apk_path=Path(apk_path),
        file_name=original_name,
        file_size=size,
        sha256=sha256,
        submission=submission,
        explore=bool(explore),
        storage=storage,
    )

    return {
        "success": True,
        "job_id": job_id,
        "status": "processing",
        "status_url": f"/api/v1/analyze-apk/{job_id}",
    }


@router.get("/analyze-apk/{job_id}")
def get_analysis_job(job_id: str) -> dict:
    """Poll job progress; returns the unified result once completed."""
    if not is_uuid(job_id):
        raise AppError("NOT_FOUND", "Unknown job.", http_status=404)
    record = get_job_store().get(job_id)
    if record is None:
        raise AppError("NOT_FOUND", "Unknown job.", http_status=404)
    return record.public_payload()
