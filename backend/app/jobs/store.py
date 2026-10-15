from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from app.core.config import settings
from app.db.session import SessionLocal, engine
from app.jobs.models import JobRecord, JobStage, JobStatus, progress_for

logger = logging.getLogger(__name__)


class JobStore(Protocol):
    """Storage contract for async job lifecycle.

    Two drivers ship today: Postgres (durable, survives restarts) and in-memory
    (single process, used when DATABASE_URL is unset). A Redis driver can be added
    behind this same interface without touching call sites.
    """

    def create(self, record: JobRecord) -> JobRecord: ...

    def get(self, job_id: str) -> JobRecord | None: ...

    def update(self, job_id: str, **changes: Any) -> JobRecord | None: ...

    def mark_stage(self, job_id: str, stage: JobStage) -> JobRecord | None: ...

    def mark_completed(self, job_id: str, result: dict[str, Any]) -> JobRecord | None: ...

    def mark_failed(self, job_id: str, code: str, message: str) -> JobRecord | None: ...

    def purge_expired(self) -> int: ...


def _apply(record: JobRecord, changes: dict[str, Any]) -> JobRecord:
    for key, value in changes.items():
        if hasattr(record, key):
            setattr(record, key, value)
    record.updated_at = datetime.now(timezone.utc)
    return record


class InMemoryJobStore:
    """Thread-safe fallback used when PostgreSQL is not configured."""

    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._lock = threading.Lock()

    def create(self, record: JobRecord) -> JobRecord:
        with self._lock:
            self._jobs[record.id] = record
            return record

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **changes: Any) -> JobRecord | None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return None
            return _apply(record, changes)

    def mark_stage(self, job_id: str, stage: JobStage) -> JobRecord | None:
        return self.update(
            job_id,
            stage=stage,
            progress=progress_for(stage),
            status=JobStatus.PROCESSING,
        )

    def mark_completed(self, job_id: str, result: dict[str, Any]) -> JobRecord | None:
        return self.update(
            job_id,
            status=JobStatus.COMPLETED,
            stage=JobStage.DONE,
            progress=100,
            result=result,
            finished_at=datetime.now(timezone.utc),
        )

    def mark_failed(self, job_id: str, code: str, message: str) -> JobRecord | None:
        return self.update(
            job_id,
            status=JobStatus.FAILED,
            error_code=code,
            error_message=message,
            finished_at=datetime.now(timezone.utc),
        )

    def purge_expired(self) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.job_retention_seconds)
        with self._lock:
            stale = [key for key, value in self._jobs.items() if value.updated_at < cutoff]
            for key in stale:
                self._jobs.pop(key, None)
            return len(stale)


class PostgresJobStore:
    """Durable driver backed by the ``analysis_jobs`` table."""

    def _to_record(self, row: Any) -> JobRecord:
        return JobRecord(
            id=row.id,
            status=JobStatus(row.status),
            stage=JobStage(row.stage),
            progress=row.progress or 0,
            file_name=row.file_name,
            file_size=row.file_size,
            sha256=row.sha256,
            package_name=row.package_name,
            exploration_requested=bool(row.exploration_requested),
            result=row.result,
            error_code=row.error_code,
            error_message=row.error_message,
            created_at=row.created_at,
            updated_at=row.updated_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
        )

    def create(self, record: JobRecord) -> JobRecord:
        from app.db.models import AnalysisJob

        session = SessionLocal()  # type: ignore[misc]
        try:
            session.add(
                AnalysisJob(
                    id=record.id,
                    status=record.status.value,
                    stage=record.stage.value,
                    progress=record.progress,
                    file_name=record.file_name,
                    file_size=record.file_size,
                    sha256=record.sha256,
                    package_name=record.package_name,
                    exploration_requested=record.exploration_requested,
                )
            )
            session.commit()
            return record
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get(self, job_id: str) -> JobRecord | None:
        from app.db.models import AnalysisJob

        session = SessionLocal()  # type: ignore[misc]
        try:
            row = session.get(AnalysisJob, job_id)
            return self._to_record(row) if row is not None else None
        finally:
            session.close()

    def update(self, job_id: str, **changes: Any) -> JobRecord | None:
        from app.db.models import AnalysisJob

        session = SessionLocal()  # type: ignore[misc]
        try:
            row = session.get(AnalysisJob, job_id)
            if row is None:
                return None
            for key, value in changes.items():
                if isinstance(value, (JobStatus, JobStage)):
                    value = value.value
                if hasattr(row, key):
                    setattr(row, key, value)
            session.commit()
            session.refresh(row)
            return self._to_record(row)
        except Exception:
            session.rollback()
            logger.exception("Failed to update job %s", job_id)
            raise
        finally:
            session.close()

    def mark_stage(self, job_id: str, stage: JobStage) -> JobRecord | None:
        changes: dict[str, Any] = {
            "stage": stage,
            "progress": progress_for(stage),
            "status": JobStatus.PROCESSING,
        }
        if stage is JobStage.STATIC_ANALYSIS:
            changes["started_at"] = datetime.now(timezone.utc)
        return self.update(job_id, **changes)

    def mark_completed(self, job_id: str, result: dict[str, Any]) -> JobRecord | None:
        return self.update(
            job_id,
            status=JobStatus.COMPLETED,
            stage=JobStage.DONE,
            progress=100,
            result=result,
            finished_at=datetime.now(timezone.utc),
        )

    def mark_failed(self, job_id: str, code: str, message: str) -> JobRecord | None:
        return self.update(
            job_id,
            status=JobStatus.FAILED,
            error_code=code,
            error_message=message,
            finished_at=datetime.now(timezone.utc),
        )

    def purge_expired(self) -> int:
        from sqlalchemy import delete

        from app.db.models import AnalysisJob

        cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.job_retention_seconds)
        session = SessionLocal()  # type: ignore[misc]
        try:
            result = session.execute(
                delete(AnalysisJob).where(AnalysisJob.updated_at < cutoff)
            )
            session.commit()
            return int(result.rowcount or 0)
        except Exception:
            session.rollback()
            return 0
        finally:
            session.close()


_memory_store = InMemoryJobStore()
_postgres_store = PostgresJobStore()


def get_job_store() -> JobStore:
    """Pick the most durable driver currently available."""
    if engine is not None and SessionLocal is not None:
        return _postgres_store
    return _memory_store


def store_backend() -> str:
    return "postgres" if (engine is not None and SessionLocal is not None) else "memory"
