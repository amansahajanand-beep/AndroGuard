from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobStage(str, Enum):
    """Ordered pipeline stages, each mapped to a coarse progress percentage."""

    QUEUED = "queued"
    STATIC_ANALYSIS = "static_analysis"
    EMULATOR_BOOT = "emulator_boot"
    APK_INSTALL = "apk_install"
    APP_LAUNCH = "app_launch"
    EXPLORING = "exploring"
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
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def public_payload(self) -> dict[str, Any]:
        """The shape returned by GET /analyze-apk/{job_id}."""
        body: dict[str, Any] = {
            "job_id": self.id,
            "status": self.status.value,
            "stage": self.stage.value,
            "progress": self.progress,
        }
        if self.status is JobStatus.COMPLETED and self.result is not None:
            data = self.result.get("data", {}) if isinstance(self.result, dict) else {}
            body["schema_version"] = self.result.get("schema_version")
            body["json_analysis"] = self.result
            # Surface exploration output as a sibling key for convenience.
            if isinstance(data, dict) and data.get("exploration") is not None:
                body["screenshots"] = data["exploration"]
        if self.status is JobStatus.FAILED:
            body["error"] = {
                "code": self.error_code or "ANALYZER_ERROR",
                "message": self.error_message or "Analysis failed.",
            }
        return body
