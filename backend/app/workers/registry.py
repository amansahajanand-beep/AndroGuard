"""Phase 12I — Worker registry, heartbeat, and health (in-process).

Does not introduce a new database. Runtime visibility for API enrichment and
stuck-worker detection.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WorkerHealth(str, Enum):
    IDLE = "IDLE"
    BUSY = "BUSY"
    STARTING = "STARTING"
    UNHEALTHY = "UNHEALTHY"
    DRAINING = "DRAINING"
    STOPPED = "STOPPED"


class WorkerLifecycle(str, Enum):
    IDLE = "IDLE"
    RESERVED = "RESERVED"
    STARTING_EMULATOR = "STARTING_EMULATOR"
    INSTALLING_APK = "INSTALLING_APK"
    RUNNING = "RUNNING"
    FINALIZING = "FINALIZING"
    CLEANING = "CLEANING"
    FAILED = "FAILED"


@dataclass
class WorkerRecord:
    worker_id: str
    health: WorkerHealth = WorkerHealth.IDLE
    lifecycle: WorkerLifecycle = WorkerLifecycle.IDLE
    current_job_id: str | None = None
    device_id: str | None = None
    adb_serial: str | None = None
    last_heartbeat: float = field(default_factory=time.monotonic)
    started_at: datetime = field(default_factory=_utcnow)
    jobs_received: int = 0
    jobs_completed: int = 0
    jobs_failed: int = 0
    jobs_cancelled: int = 0
    jobs_timed_out: int = 0
    job_retries: int = 0
    emulator_failures: int = 0
    cleanup_failures: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "health": self.health.value,
            "lifecycle": self.lifecycle.value,
            "current_job_id": self.current_job_id,
            "device_id": self.device_id,
            "adb_serial": self.adb_serial,
            "last_heartbeat_age_s": round(time.monotonic() - self.last_heartbeat, 2),
            "started_at": self.started_at.isoformat().replace("+00:00", "Z"),
            "metrics": {
                "jobs_received": self.jobs_received,
                "jobs_completed": self.jobs_completed,
                "jobs_failed": self.jobs_failed,
                "jobs_cancelled": self.jobs_cancelled,
                "jobs_timed_out": self.jobs_timed_out,
                "job_retries": self.job_retries,
                "emulator_failures": self.emulator_failures,
                "cleanup_failures": self.cleanup_failures,
            },
        }


class WorkerRegistry:
    """Thread-safe in-process registry of exploration workers."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._workers: dict[str, WorkerRecord] = {}
        self._job_to_worker: dict[str, str] = {}
        self._cancel_requested: set[str] = set()
        self._active_attempts: dict[str, int] = {}  # job_id -> attempt

    def register(self, worker_id: str) -> WorkerRecord:
        with self._lock:
            if worker_id not in self._workers:
                self._workers[worker_id] = WorkerRecord(worker_id=worker_id)
            return self._workers[worker_id]

    def heartbeat(
        self,
        worker_id: str,
        *,
        health: WorkerHealth | None = None,
        lifecycle: WorkerLifecycle | None = None,
        job_id: str | None = None,
        device_id: str | None = None,
        adb_serial: str | None = None,
    ) -> None:
        with self._lock:
            rec = self.register(worker_id)
            rec.last_heartbeat = time.monotonic()
            if health is not None:
                rec.health = health
            if lifecycle is not None:
                rec.lifecycle = lifecycle
            if job_id is not None:
                rec.current_job_id = job_id
            if device_id is not None:
                rec.device_id = device_id
            if adb_serial is not None:
                rec.adb_serial = adb_serial

    def assign_job(self, worker_id: str, job_id: str, *, attempt: int = 1) -> None:
        with self._lock:
            # Idempotency: same job already assigned to this worker.
            existing = self._job_to_worker.get(job_id)
            if existing is not None and existing != worker_id:
                raise RuntimeError(
                    f"job {job_id} already assigned to {existing}, cannot assign to {worker_id}"
                )
            rec = self.register(worker_id)
            rec.current_job_id = job_id
            rec.health = WorkerHealth.BUSY
            rec.lifecycle = WorkerLifecycle.RESERVED
            rec.jobs_received += 1
            self._job_to_worker[job_id] = worker_id
            self._active_attempts[job_id] = attempt
            rec.last_heartbeat = time.monotonic()

    def release_job(
        self,
        worker_id: str,
        job_id: str,
        *,
        outcome: str = "completed",
    ) -> None:
        with self._lock:
            rec = self._workers.get(worker_id)
            if rec is not None:
                if outcome == "completed":
                    rec.jobs_completed += 1
                elif outcome == "failed":
                    rec.jobs_failed += 1
                elif outcome == "cancelled":
                    rec.jobs_cancelled += 1
                elif outcome == "timeout":
                    rec.jobs_timed_out += 1
                if rec.current_job_id == job_id:
                    rec.current_job_id = None
                    rec.device_id = None
                    rec.adb_serial = None
                if rec.health not in {WorkerHealth.DRAINING, WorkerHealth.STOPPED}:
                    rec.health = WorkerHealth.IDLE
                    rec.lifecycle = WorkerLifecycle.IDLE
            self._job_to_worker.pop(job_id, None)
            self._active_attempts.pop(job_id, None)
            self._cancel_requested.discard(job_id)

    def request_cancel(self, job_id: str) -> bool:
        with self._lock:
            self._cancel_requested.add(job_id)
            return job_id in self._job_to_worker or True

    def is_cancel_requested(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancel_requested

    def clear_cancel(self, job_id: str) -> None:
        with self._lock:
            self._cancel_requested.discard(job_id)

    def worker_for_job(self, job_id: str) -> str | None:
        with self._lock:
            return self._job_to_worker.get(job_id)

    def attempt_for_job(self, job_id: str) -> int:
        with self._lock:
            return int(self._active_attempts.get(job_id) or 1)

    def get(self, worker_id: str) -> WorkerRecord | None:
        with self._lock:
            return self._workers.get(worker_id)

    def list_workers(self) -> list[dict[str, Any]]:
        with self._lock:
            return [w.to_dict() for w in self._workers.values()]

    def mark_stale(self, *, stale_after_seconds: float) -> list[str]:
        """Mark workers with stale heartbeats unhealthy. Returns affected job ids."""
        orphaned: list[str] = []
        now = time.monotonic()
        with self._lock:
            for rec in self._workers.values():
                if rec.health in {WorkerHealth.IDLE, WorkerHealth.STOPPED}:
                    continue
                if now - rec.last_heartbeat > stale_after_seconds:
                    rec.health = WorkerHealth.UNHEALTHY
                    if rec.current_job_id:
                        orphaned.append(rec.current_job_id)
        return orphaned

    def set_draining(self, worker_id: str) -> None:
        with self._lock:
            rec = self.register(worker_id)
            rec.health = WorkerHealth.DRAINING

    def snapshot_for_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            wid = self._job_to_worker.get(job_id)
            if not wid:
                return None
            rec = self._workers.get(wid)
            if rec is None:
                return None
            return {
                "worker_id": wid,
                "lifecycle": rec.lifecycle.value,
                "health": rec.health.value,
                "device_id": rec.device_id,
                "adb_serial": rec.adb_serial,
                "attempt": self._active_attempts.get(job_id, 1),
            }


_REGISTRY = WorkerRegistry()


def get_worker_registry() -> WorkerRegistry:
    return _REGISTRY


def reset_worker_registry_for_tests() -> WorkerRegistry:
    """Test helper — replace the global registry."""
    global _REGISTRY
    _REGISTRY = WorkerRegistry()
    return _REGISTRY
