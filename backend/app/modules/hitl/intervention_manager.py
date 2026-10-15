"""Coordinate pause / continue / skip / stop for HITL interventions."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from app.core.config import settings
from app.jobs.models import JobStage, JobStatus
from app.jobs.store import get_job_store
from app.modules.hitl.hitl_state import ExplorationCheckpoint
from app.modules.hitl.intervention_detector import InterventionDetector
from app.modules.hitl.intervention_store import InterventionStore, get_intervention_store
from app.modules.hitl.intervention_types import (
    DetectionResult,
    HumanDecision,
    Intervention,
    InterventionStatus,
    new_intervention_id,
)

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class InterventionManager:
    """Blocks the exploration worker until a human Continues, Skips, or Stops.

    The worker thread remains associated with the job and keeps the emulator
    lock. Continue does **not** auto-tap consent/permission buttons.
    """

    def __init__(
        self,
        job_id: str,
        *,
        run_id: str | None = None,
        store: InterventionStore | None = None,
        timeout_seconds: float | None = None,
        detector: InterventionDetector | None = None,
        artifact_dir: str | Path | None = None,
    ) -> None:
        self.job_id = job_id
        self.run_id = run_id or job_id
        self.store = store or get_intervention_store()
        self.timeout_seconds = float(
            timeout_seconds
            if timeout_seconds is not None
            else getattr(settings, "hitl_timeout_seconds", 1800)
        )
        self.detector = detector or InterventionDetector()
        if artifact_dir is not None:
            self.artifact_dir = Path(artifact_dir)
        else:
            from app.modules.exploration.screenshot_storage import local_hitl_dir

            self.artifact_dir = local_hitl_dir(None, job_id)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

        self._events: dict[str, threading.Event] = {}
        self._decisions: dict[str, HumanDecision] = {}
        self._lock = threading.RLock()
        self._active_intervention_id: str | None = None
        self._last_checkpoint: ExplorationCheckpoint | None = None
        self._stopped = False
        self._partial_result: dict[str, Any] | None = None

    @property
    def active_intervention_id(self) -> str | None:
        return self._active_intervention_id

    @property
    def last_checkpoint(self) -> ExplorationCheckpoint | None:
        return self._last_checkpoint

    @property
    def stopped(self) -> bool:
        return self._stopped

    def request_intervention(
        self,
        detection: DetectionResult,
        *,
        package: str | None,
        activity: str | None,
        screenshot_bytes: bytes | None = None,
        ui_dump_xml: str | None = None,
        checkpoint: ExplorationCheckpoint | None = None,
        fingerprint: str | None = None,
    ) -> tuple[Intervention, HumanDecision]:
        """Create an intervention, mark the job waiting, and block until a decision."""
        if not detection.required or detection.type is None:
            raise ValueError("DetectionResult.required must be True")

        intervention_id = new_intervention_id()
        screenshot_path = None
        screenshot_s3_key = None
        screenshot_s3_url = None
        ui_dump_path = None
        if screenshot_bytes:
            screenshot_path = str(self.artifact_dir / f"{intervention_id}.png")
            Path(screenshot_path).write_bytes(screenshot_bytes)
            # Phase 8: best-effort S3 publish for HITL screenshots.
            try:
                from app.modules.exploration.screenshot_storage import ScreenshotStorage

                storage = ScreenshotStorage(
                    app_id=package or self.job_id,
                    run_id=self.run_id,
                )
                meta = storage.upload_bytes(
                    screenshot_bytes,
                    page="hitl",
                    state_id=intervention_id,
                    kind="hitl",
                    triggering_action="hitl_pause",
                    local_path=screenshot_path,
                    screenshot_id=intervention_id,
                )
                screenshot_s3_key = meta.s3_key
                screenshot_s3_url = meta.s3_url
                if meta.upload_error:
                    logger.warning(
                        "HITL screenshot S3 upload deferred job=%s err=%s",
                        self.job_id,
                        meta.upload_error,
                    )
            except Exception:
                logger.warning(
                    "HITL screenshot S3 upload failed job=%s",
                    self.job_id,
                    exc_info=True,
                )
        if ui_dump_xml is not None:
            ui_dump_path = str(self.artifact_dir / f"{intervention_id}.xml")
            Path(ui_dump_path).write_text(ui_dump_xml, encoding="utf-8")

        timeout_at = _now() + timedelta(seconds=self.timeout_seconds)
        intervention = Intervention(
            intervention_id=intervention_id,
            job_id=self.job_id,
            run_id=self.run_id,
            type=detection.type,
            title=detection.title or detection.type.value,
            message=detection.message or "Human action required",
            package=package,
            activity=activity,
            screenshot_path=screenshot_path,
            screenshot_s3_key=screenshot_s3_key,
            screenshot_s3_url=screenshot_s3_url,
            ui_dump_path=ui_dump_path,
            status=InterventionStatus.WAITING,
            timeout_at=timeout_at,
            evidence=list(detection.evidence),
            state_id=checkpoint.current_state_id if checkpoint else None,
            parent_state_id=checkpoint.parent_state_id if checkpoint else None,
            depth=checkpoint.depth if checkpoint else 0,
            is_system_ui=detection.is_system_ui,
            confidence=detection.confidence,
            suggested_action=detection.suggested_action,
            steps=list(detection.steps or []),
            extras={
                "suggested_action": detection.suggested_action,
                "steps": list(detection.steps or []),
                "fingerprint": fingerprint,
            },
        )
        if checkpoint is None:
            checkpoint = ExplorationCheckpoint(
                job_id=self.job_id,
                intervention_id=intervention_id,
                current_activity=activity,
                current_package=package,
                blocked_fingerprint=fingerprint,
            )
        else:
            checkpoint.intervention_id = intervention_id
            checkpoint.blocked_fingerprint = fingerprint or checkpoint.blocked_fingerprint

        self.store.save(intervention)
        self.store.save_checkpoint(checkpoint)
        self._last_checkpoint = checkpoint
        try:
            from app.db.phase11_repository import persist_intervention_from_dataclass

            persist_intervention_from_dataclass(intervention)
        except Exception:
            logger.debug("Phase 11 HITL persist (create) skipped", exc_info=True)

        event = threading.Event()
        with self._lock:
            self._events[intervention_id] = event
            self._active_intervention_id = intervention_id

        self._publish_waiting(intervention, checkpoint)
        logger.info(
            "HITL pause job=%s intervention=%s type=%s timeout=%ss",
            self.job_id,
            intervention_id,
            intervention.type.value,
            self.timeout_seconds,
        )

        finished = event.wait(timeout=self.timeout_seconds)
        with self._lock:
            decision = self._decisions.pop(intervention_id, None)
            self._events.pop(intervention_id, None)
            self._active_intervention_id = None

        if not finished or decision is None:
            decision = HumanDecision.TIMEOUT
            self.store.update(
                intervention_id,
                status=InterventionStatus.TIMEOUT,
                decision=decision,
                resolved_at=_now(),
            )
            self._publish_timeout(intervention_id)
            logger.info("HITL timeout job=%s intervention=%s", self.job_id, intervention_id)
            try:
                from app.db.phase11_repository import persist_intervention_from_dataclass

                fresh_timeout = self.store.get(intervention_id)
                if fresh_timeout is not None:
                    persist_intervention_from_dataclass(fresh_timeout)
            except Exception:
                logger.debug("Phase 11 HITL persist (timeout) skipped", exc_info=True)
            return intervention, decision

        status_map = {
            HumanDecision.CONTINUE: InterventionStatus.RESOLVED,
            HumanDecision.SKIP: InterventionStatus.SKIPPED,
            HumanDecision.STOP: InterventionStatus.STOPPED,
            HumanDecision.TIMEOUT: InterventionStatus.TIMEOUT,
        }
        self.store.update(
            intervention_id,
            status=status_map.get(decision, InterventionStatus.RESOLVED),
            decision=decision,
            resolved_at=_now(),
        )
        if decision is HumanDecision.STOP:
            self._stopped = True
        elif decision in (HumanDecision.CONTINUE, HumanDecision.SKIP):
            self._publish_running()
        logger.info(
            "HITL decision job=%s intervention=%s decision=%s",
            self.job_id,
            intervention_id,
            decision.value,
        )
        # Refresh intervention object
        fresh = self.store.get(intervention_id) or intervention
        try:
            from app.db.phase11_repository import persist_intervention_from_dataclass

            persist_intervention_from_dataclass(fresh)
        except Exception:
            logger.debug("Phase 11 HITL persist (resolve) skipped", exc_info=True)
        return fresh, decision

    def signal_continue(self, intervention_id: str) -> dict[str, Any]:
        return self._signal(intervention_id, HumanDecision.CONTINUE)

    def signal_skip(self, intervention_id: str) -> dict[str, Any]:
        return self._signal(intervention_id, HumanDecision.SKIP)

    def signal_stop(self, intervention_id: str) -> dict[str, Any]:
        self._stopped = True
        return self._signal(intervention_id, HumanDecision.STOP)

    def verify_cleared(
        self,
        *,
        elements,
        package: str | None,
        activity: str | None,
        previous: DetectionResult | None,
        previous_fingerprint: str | None = None,
        current_fingerprint: str | None = None,
    ) -> bool:
        """Return True when the blocking screen appears gone."""
        return not self.detector.still_blocked(
            elements=elements,
            package=package,
            activity=activity,
            previous=previous,
            previous_fingerprint=previous_fingerprint,
            current_fingerprint=current_fingerprint,
        )

    # ------------------------------------------------------------------ internal

    def _signal(self, intervention_id: str, decision: HumanDecision) -> dict[str, Any]:
        intervention = self.store.get(intervention_id)
        if intervention is None or intervention.job_id != self.job_id:
            return {"success": False, "message": "Unknown intervention."}
        if intervention.status is not InterventionStatus.WAITING:
            return {
                "success": False,
                "message": f"Intervention is already {intervention.status.value}.",
            }
        with self._lock:
            event = self._events.get(intervention_id)
            if event is None:
                return {"success": False, "message": "No worker is waiting on this intervention."}
            self._decisions[intervention_id] = decision
            event.set()
        return {
            "success": True,
            "decision": decision.value,
            "intervention_id": intervention_id,
            "message": f"Recorded decision: {decision.value}",
        }

    def _publish_waiting(
        self, intervention: Intervention, checkpoint: ExplorationCheckpoint
    ) -> None:
        try:
            get_job_store().update(
                self.job_id,
                status=JobStatus.WAITING_FOR_HUMAN,
                stage=JobStage.WAITING_FOR_HUMAN,
                intervention=intervention.public_payload(),
                exploration_checkpoint=checkpoint.to_dict(),
            )
        except Exception:
            logger.warning("Could not publish WAITING_FOR_HUMAN for %s", self.job_id, exc_info=True)

    def _publish_running(self) -> None:
        try:
            get_job_store().update(
                self.job_id,
                status=JobStatus.RUNNING,
                stage=JobStage.EXPLORING,
                intervention=None,
            )
        except Exception:
            logger.warning("Could not publish RUNNING after HITL for %s", self.job_id, exc_info=True)

    def _publish_timeout(self, intervention_id: str) -> None:
        try:
            intervention = self.store.get(intervention_id)
            get_job_store().update(
                self.job_id,
                status=JobStatus.TIMEOUT,
                intervention=intervention.public_payload() if intervention else None,
            )
        except Exception:
            logger.warning("Could not publish TIMEOUT for %s", self.job_id, exc_info=True)


# Process-wide registry so API handlers can signal the worker that owns a job.
_MANAGERS: dict[str, InterventionManager] = {}
_MANAGERS_LOCK = threading.RLock()


def register_manager(manager: InterventionManager) -> None:
    with _MANAGERS_LOCK:
        _MANAGERS[manager.job_id] = manager


def unregister_manager(job_id: str) -> None:
    with _MANAGERS_LOCK:
        _MANAGERS.pop(job_id, None)


def get_manager(job_id: str) -> InterventionManager | None:
    with _MANAGERS_LOCK:
        return _MANAGERS.get(job_id)


def wait_poll(
    predicate: Callable[[], bool],
    *,
    timeout: float,
    interval: float = 0.25,
) -> bool:
    """Utility for tests — poll until predicate or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False
