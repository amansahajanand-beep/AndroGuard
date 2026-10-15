from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.api.deps import get_current_user, owned_job
from app.api.v1.analyze import _build_submission, _validate_filename, read_policy_upload
from app.core.config import settings
from app.core.errors import AppError
from app.jobs.models import JobRecord, JobStatus
from app.jobs.store import get_job_store
from app.schemas.auth import UserProfile
from app.storage.local import LocalTempStorage
from app.utils.files import is_uuid, new_job_id
from app.utils.hashing import stream_to_file
from app.workers.pool import get_worker_pool
from app.workers.registry import get_worker_registry

logger = logging.getLogger(__name__)
router = APIRouter()
storage = LocalTempStorage()


@router.post("/analyze-apk")
async def create_analysis_job(
    file: UploadFile = File(...),
    app_name: str | None = Form(default=None),
    app_description: str | None = Form(default=None),
    privacy_policy: str | None = Form(default=None),
    privacy_policy_file: UploadFile | None = File(default=None),
    play_store_url: str | None = Form(default=None),
    explore: bool = Form(default=True),
    user: UserProfile = Depends(get_current_user),
) -> dict:
    """Accept an APK and enqueue analysis+exploration on the worker pool.

    Returns immediately with a job id; poll ``GET /analyze-apk/{job_id}``.
    The uploaded APK is kept on disk for the worker and removed when the job ends.
    """
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
    except Exception:
        storage.delete_job(job_id)
        raise
    finally:
        await file.close()

    logger.info("Queued analysis job=%s size=%s explore=%s", job_id, size, explore)
    store = get_job_store()
    record = JobRecord(
        id=job_id,
        user_id=user.id,
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

    pool = get_worker_pool()
    ok = pool.enqueue(
        job_id,
        apk_path=Path(apk_path),
        file_name=original_name,
        file_size=size,
        sha256=sha256,
        submission=submission,
        explore=bool(explore),
        storage=storage,
    )
    if not ok:
        logger.warning("Job %s was not newly enqueued (duplicate or draining)", job_id)

    snap = pool.snapshot()
    return {
        "success": True,
        "job_id": job_id,
        "status": "processing",
        "status_url": f"/api/v1/analyze-apk/{job_id}",
        "queue": {
            "queued": snap["queued"],
            "active": snap["active"],
            "concurrency": snap["concurrency"],
        },
    }


@router.get("/analyze-apk/{job_id}")
def get_analysis_job(job_id: str, user: UserProfile = Depends(get_current_user)) -> dict:
    """Poll job progress; returns the unified result once completed."""
    record = owned_job(job_id, user)
    payload = record.public_payload()
    worker = get_worker_registry().snapshot_for_job(job_id)
    if worker:
        payload["worker"] = worker
    return payload


@router.post("/analyze-apk/{job_id}/cancel")
def cancel_analysis_job(job_id: str, user: UserProfile = Depends(get_current_user)) -> dict:
    """Request cooperative cancellation of a running/queued analysis job."""
    record = owned_job(job_id, user)
    store = get_job_store()
    if record.status in {
        JobStatus.COMPLETED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
        JobStatus.TIMEOUT,
        JobStatus.PARTIAL,
    }:
        return {
            "success": True,
            "job_id": job_id,
            "status": record.status.value,
            "message": "Job already finished.",
        }
    pool = get_worker_pool()
    pool.request_cancel(job_id)
    snap = pool.snapshot()
    if job_id in snap.get("queued_job_ids", []):
        with pool._lock:
            pool._queue = [q for q in pool._queue if q.job_id != job_id]
        from datetime import datetime, timezone

        store.update(
            job_id,
            status=JobStatus.CANCELLED,
            error_code="CANCELLED",
            error_message="Cancelled while queued.",
            finished_at=datetime.now(timezone.utc),
        )
        return {
            "success": True,
            "job_id": job_id,
            "status": "cancelled",
            "message": "Queued job cancelled.",
        }
    return {
        "success": True,
        "job_id": job_id,
        "status": "cancelling",
        "message": "Cancel signal sent to worker.",
    }


@router.get("/workers/health")
def workers_health(_user: UserProfile = Depends(get_current_user)) -> dict:
    """Lightweight worker/queue health snapshot (no secrets)."""
    pool = get_worker_pool()
    return {
        "success": True,
        "pool": pool.snapshot(),
    }
