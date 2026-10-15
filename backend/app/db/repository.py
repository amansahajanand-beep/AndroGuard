from __future__ import annotations

import logging

from sqlalchemy import select

from app.db.models import AnalysisRecord, ScreenshotFile
from app.db.session import SessionLocal, engine
from app.schemas.analysis import AnalysisResponse, ScreenshotInfo

logger = logging.getLogger(__name__)


def persist_analysis(job_id: str, response: AnalysisResponse, user_id: str | None = None) -> None:
    if engine is None or SessionLocal is None:
        return
    payload = response.model_dump()
    record = AnalysisRecord(
        id=job_id,
        user_id=user_id,
        sha256=response.data.apk.sha256,
        package_name=response.data.apk.package_name,
        file_name=response.data.apk.file_name,
        file_size=response.data.apk.file_size,
        status=response.status,
        analyzer_version=response.data.analysis.analyzer_version,
        result=payload,
    )
    session = SessionLocal()
    try:
        session.merge(record)
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("Failed to persist analysis %s", job_id)
        raise
    finally:
        session.close()


def get_analysis(job_id: str, user_id: str) -> dict | None:
    """Return the stored result only when it belongs to ``user_id``."""
    if engine is None or SessionLocal is None:
        return None
    session = SessionLocal()
    try:
        record = session.get(AnalysisRecord, job_id)
        if record is None or record.user_id != user_id:
            return None
        return record.result
    finally:
        session.close()


def _submitted_app_name(result: dict | None) -> str | None:
    if not isinstance(result, dict):
        return None
    submission = result.get("data", {}).get("submission")
    return submission.get("app_name") if isinstance(submission, dict) else None


def list_analyses(user_id: str, limit: int = 20) -> list[dict]:
    if engine is None or SessionLocal is None:
        return []
    session = SessionLocal()
    try:
        stmt = (
            select(AnalysisRecord)
            .where(AnalysisRecord.user_id == user_id)
            .order_by(AnalysisRecord.created_at.desc())
            .limit(min(limit, 100))
        )
        rows = session.scalars(stmt).all()
        return [
            {
                "id": row.id,
                "sha256": row.sha256,
                "package_name": row.package_name,
                "file_name": row.file_name,
                "file_size": row.file_size,
                "app_name": _submitted_app_name(row.result),
                "status": row.status,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    finally:
        session.close()


def job_owner_id(job_id: str) -> str | None:
    """Owner of a job/analysis, or None when unknown or unowned (legacy rows)."""
    if engine is None or SessionLocal is None:
        return None
    from app.db.models import AnalysisJob

    session = SessionLocal()
    try:
        job = session.get(AnalysisJob, job_id)
        if job is not None and job.user_id:
            return job.user_id
        record = session.get(AnalysisRecord, job_id)
        return record.user_id if record is not None else None
    finally:
        session.close()


CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
}


def persist_screenshots(job_id: str, screenshots: list[ScreenshotInfo], files: dict[str, bytes]) -> int:
    if engine is None or SessionLocal is None or not files:
        return 0
    session = SessionLocal()
    saved = 0
    try:
        for item in screenshots:
            data = files.get(item.file_name)
            if not data:
                continue
            stmt = select(ScreenshotFile).where(
                ScreenshotFile.analysis_id == job_id,
                ScreenshotFile.file_name == item.file_name,
            )
            row = session.scalars(stmt).first()
            content_type = CONTENT_TYPES.get((item.format or "").lower(), "application/octet-stream")
            if row is None:
                session.add(
                    ScreenshotFile(
                        analysis_id=job_id,
                        file_name=item.file_name,
                        original_path=item.original_path,
                        content_type=content_type,
                        width=item.width,
                        height=item.height,
                        byte_size=len(data),
                        data=data,
                    )
                )
            else:
                row.original_path = item.original_path
                row.content_type = content_type
                row.width = item.width
                row.height = item.height
                row.byte_size = len(data)
                row.data = data
            saved += 1
        session.commit()
        return saved
    except Exception:
        session.rollback()
        logger.exception("Failed to persist screenshots for %s", job_id)
        raise
    finally:
        session.close()


def get_screenshot(job_id: str, file_name: str) -> tuple[bytes, str] | None:
    if engine is None or SessionLocal is None:
        return None
    session = SessionLocal()
    try:
        stmt = select(ScreenshotFile).where(
            ScreenshotFile.analysis_id == job_id,
            ScreenshotFile.file_name == file_name,
        )
        row = session.scalars(stmt).first()
        if row is None:
            return None
        return row.data, row.content_type
    finally:
        session.close()
