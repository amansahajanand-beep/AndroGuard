from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    # Alias kept so older call sites / DB rows using "processing" still work.
    PROCESSING = "running"
    WAITING_FOR_HUMAN = "waiting_for_human"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


def coerce_job_status(value: str | JobStatus) -> JobStatus:
    """Parse status strings, including legacy ``processing``."""
    if isinstance(value, JobStatus):
        return value
    raw = (value or "").strip().lower()
    if raw == "processing":
        return JobStatus.RUNNING
    return JobStatus(raw)


class JobStage(str, Enum):
    """Ordered pipeline stages, each mapped to a coarse progress percentage."""

    QUEUED = "queued"
    STATIC_ANALYSIS = "static_analysis"
    EMULATOR_BOOT = "emulator_boot"
    APK_INSTALL = "apk_install"
    APP_LAUNCH = "app_launch"
    EXPLORING = "exploring"
    WAITING_FOR_HUMAN = "waiting_for_human"
    AD_ANALYSIS = "ad_analysis"
    UPLOADING = "uploading"
    PERSISTING = "persisting"
    DONE = "done"


# Progress is reported as a percentage so clients can render a bar without
# knowing anything about our internal stage names.
STAGE_PROGRESS: dict[JobStage, int] = {
    JobStage.QUEUED: 0,
    JobStage.STATIC_ANALYSIS: 10,
    JobStage.EMULATOR_BOOT: 25,
    JobStage.APK_INSTALL: 35,
    JobStage.APP_LAUNCH: 45,
    JobStage.EXPLORING: 55,
    JobStage.WAITING_FOR_HUMAN: 55,
    JobStage.AD_ANALYSIS: 80,
    JobStage.UPLOADING: 88,
    JobStage.PERSISTING: 95,
    JobStage.DONE: 100,
}


def progress_for(stage: JobStage) -> int:
    return STAGE_PROGRESS.get(stage, 0)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class JobRecord:
    id: str
    user_id: str | None = None
    status: JobStatus = JobStatus.QUEUED
    stage: JobStage = JobStage.QUEUED
    progress: int = 0
    file_name: str | None = None
    file_size: int | None = None
    sha256: str | None = None
    package_name: str | None = None
    exploration_requested: bool = False
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    intervention: dict[str, Any] | None = None
    exploration_checkpoint: dict[str, Any] | None = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def public_payload(self) -> dict[str, Any]:
        """The shape returned by GET /analyze-apk/{job_id} (Phase 9 unified)."""
        from app.services.unified_result import enrich_job_public_payload, public_job_status

        status = self.status
        status_value = status.value if isinstance(status, JobStatus) else str(status)
        if status_value == "processing":
            status_value = JobStatus.RUNNING.value
        body: dict[str, Any] = {
            "job_id": self.id,
            "status": public_job_status(status_value),
            "stage": self.stage.value if isinstance(self.stage, JobStage) else str(self.stage),
            "progress": self.progress,
        }
        if self.package_name:
            body["package_name"] = self.package_name
        if self.file_name:
            body["file_name"] = self.file_name

        if (
            self.intervention is not None
            and status_value == JobStatus.WAITING_FOR_HUMAN.value
        ):
            body["intervention"] = self.intervention
        if (
            self.exploration_checkpoint is not None
            and status_value == JobStatus.WAITING_FOR_HUMAN.value
        ):
            body["exploration_checkpoint"] = {
                "current_state_id": self.exploration_checkpoint.get("current_state_id"),
                "parent_state_id": self.exploration_checkpoint.get("parent_state_id"),
                "current_activity": self.exploration_checkpoint.get("current_activity"),
                "current_package": self.exploration_checkpoint.get("current_package"),
                "depth": self.exploration_checkpoint.get("depth"),
                "intervention_id": self.exploration_checkpoint.get("intervention_id"),
            }

        terminal_with_result = {
            JobStatus.COMPLETED.value,
            JobStatus.PARTIAL.value,
            JobStatus.CANCELLED.value,
            JobStatus.TIMEOUT.value,
        }
        if status_value in terminal_with_result and self.result is not None:
            body = enrich_job_public_payload(
                body,
                result=self.result,
                file_name=self.file_name,
                package_name=self.package_name,
            )
        if status_value == JobStatus.FAILED.value:
            body["success"] = False
            body["error"] = {
                "code": self.error_code or "ANALYZER_ERROR",
                "message": self.error_message or "Analysis failed.",
            }
            # Static analysis may still be present on some failure paths.
            if self.result is not None:
                body["json_analysis"] = self.result
        return body
