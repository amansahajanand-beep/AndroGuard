"""Phase 12I — Bounded exploration worker pool (queue + concurrency).

Reuses the existing ``run_analysis_job`` pipeline. Does not implement a second
exploration engine. Enforces: one active job per worker slot / device.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.core.config import settings
from app.jobs.models import JobStatus
from app.jobs.store import get_job_store
from app.workers.device_pool import DeviceSlot, get_device_pool
from app.workers.device_session import AndroidDeviceSession
from app.workers.registry import (
    WorkerHealth,
    WorkerLifecycle,
    get_worker_registry,
)
from app.workers.retry import classify_failure, is_retryable_job_failure

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class QueuedJob:
    job_id: str
    kwargs: dict[str, Any]
    attempt: int = 1
    enqueued_at: float = field(default_factory=time.monotonic)
    future: Future | None = None


class ExplorationWorkerPool:
    """In-process queue with bounded worker concurrency.

    API enqueues; workers claim jobs up to ``exploration_worker_concurrency``
    (and available device slots). Extra jobs remain queued.
    """

    def __init__(
        self,
        *,
        concurrency: int | None = None,
        worker_id_prefix: str | None = None,
        runner: Callable[..., dict] | None = None,
    ) -> None:
        self.concurrency = max(
            1,
            int(
                concurrency
                if concurrency is not None
                else getattr(settings, "exploration_worker_concurrency", None)
                or settings.job_max_workers
                or 1
            ),
        )
        # Align with device pool capacity (safe default: 1 shared AVD).
        pool_cap = get_device_pool().capacity
        self.concurrency = min(self.concurrency, max(1, pool_cap))
        self.worker_id_prefix = worker_id_prefix or "worker"
        self._runner = runner
        self._executor = ThreadPoolExecutor(
            max_workers=self.concurrency,
            thread_name_prefix="explore-worker",
        )
        self._lock = threading.RLock()
        self._queue: list[QueuedJob] = []
        self._active: dict[str, QueuedJob] = {}
        self._draining = False
        self._metrics = {
            "jobs_enqueued": 0,
            "jobs_started": 0,
            "jobs_finished": 0,
            "duplicate_rejects": 0,
        }
        # Pre-register worker identities.
        registry = get_worker_registry()
        for i in range(self.concurrency):
            registry.register(f"{self.worker_id_prefix}-{i+1:02d}")

    @property
    def queued_count(self) -> int:
        with self._lock:
            return len(self._queue)

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._active)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "concurrency": self.concurrency,
                "queued": len(self._queue),
                "active": len(self._active),
                "draining": self._draining,
                "active_job_ids": list(self._active.keys()),
                "queued_job_ids": [q.job_id for q in self._queue],
                "metrics": dict(self._metrics),
                "device_pool": get_device_pool().snapshot(),
                "workers": get_worker_registry().list_workers(),
            }

    def enqueue(self, job_id: str, **kwargs: Any) -> bool:
        """Queue a job for a worker. Returns False if duplicate active/queued."""
        with self._lock:
            if self._draining:
                logger.warning("[QUEUE] reject enqueue job=%s reason=draining", job_id)
                return False
            if job_id in self._active or any(q.job_id == job_id for q in self._queue):
                self._metrics["duplicate_rejects"] += 1
                logger.info("[QUEUE] duplicate delivery ignored job=%s", job_id)
                return False
            item = QueuedJob(job_id=job_id, kwargs=dict(kwargs), attempt=1)
            self._queue.append(item)
            self._metrics["jobs_enqueued"] += 1
            logger.info(
                "[QUEUE] enqueued job=%s queue_depth=%s active=%s",
                job_id,
                len(self._queue),
                len(self._active),
            )
        self._pump()
        return True

    def request_cancel(self, job_id: str) -> bool:
        registry = get_worker_registry()
        registry.request_cancel(job_id)
        store = get_job_store()
        record = store.get(job_id)
        if record is None:
            return False
        if record.status in {
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.TIMEOUT,
            JobStatus.PARTIAL,
        }:
            return False
        # Soft signal — worker honors between stages.
        logger.info("[JOB] cancel requested job=%s", job_id)
        return True

    def drain(self) -> None:
        with self._lock:
            self._draining = True
            for i in range(self.concurrency):
                get_worker_registry().set_draining(f"{self.worker_id_prefix}-{i+1:02d}")
        logger.info("[WORKER] pool draining")

    def shutdown(self, *, wait: bool = True) -> None:
        self.drain()
        self._executor.shutdown(wait=wait, cancel_futures=False)

    def _pump(self) -> None:
        with self._lock:
            while self._queue and len(self._active) < self.concurrency and not self._draining:
                item = self._queue.pop(0)
                worker_id = self._pick_idle_worker_locked()
                self._active[item.job_id] = item
                self._metrics["jobs_started"] += 1
                future = self._executor.submit(self._run_wrapped, worker_id, item)
                item.future = future

                def _done(fut: Future, jid: str = item.job_id) -> None:
                    exc = fut.exception()
                    if exc is not None:
                        logger.error(
                            "[WORKER] job=%s ended with %s: %s",
                            jid,
                            type(exc).__name__,
                            exc,
                        )
                    with self._lock:
                        self._active.pop(jid, None)
                        self._metrics["jobs_finished"] += 1
                    self._pump()

                future.add_done_callback(_done)
                logger.info(
                    "[WORKER] %s assigned job=%s attempt=%s",
                    worker_id,
                    item.job_id,
                    item.attempt,
                )

    def _pick_idle_worker_locked(self) -> str:
        registry = get_worker_registry()
        for i in range(self.concurrency):
            wid = f"{self.worker_id_prefix}-{i+1:02d}"
            rec = registry.get(wid)
            if rec is None or rec.current_job_id is None:
                return wid
        return f"{self.worker_id_prefix}-{uuid.uuid4().hex[:4]}"

    def _run_wrapped(self, worker_id: str, item: QueuedJob) -> dict | None:
        from app.workers.job_runner import run_job_with_worker

        return run_job_with_worker(
            worker_id=worker_id,
            job_id=item.job_id,
            attempt=item.attempt,
            runner=self._runner,
            **item.kwargs,
        )


_POOL_INSTANCE: ExplorationWorkerPool | None = None
_POOL_INSTANCE_LOCK = threading.Lock()


def get_worker_pool() -> ExplorationWorkerPool:
    global _POOL_INSTANCE
    with _POOL_INSTANCE_LOCK:
        if _POOL_INSTANCE is None:
            _POOL_INSTANCE = ExplorationWorkerPool()
        return _POOL_INSTANCE


def reset_worker_pool_for_tests(**kwargs: Any) -> ExplorationWorkerPool:
    global _POOL_INSTANCE
    with _POOL_INSTANCE_LOCK:
        if _POOL_INSTANCE is not None:
            try:
                _POOL_INSTANCE.shutdown(wait=False)
            except Exception:
                pass
        _POOL_INSTANCE = ExplorationWorkerPool(**kwargs)
        return _POOL_INSTANCE
