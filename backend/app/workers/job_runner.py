"""Phase 12I — Job runner: worker lifecycle around existing analysis pipeline.

Invokes ``run_analysis_job`` (unchanged exploration intelligence). Adds:
device slot acquisition, heartbeat, cancel, job timeout, cleanup, retries.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.core.config import settings
from app.jobs.models import JobStage, JobStatus
from app.jobs.store import get_job_store
from app.workers.device_pool import device_session, get_device_pool
from app.workers.device_session import AndroidDeviceSession
from app.workers.registry import (
    WorkerHealth,
    WorkerLifecycle,
    get_worker_registry,
)
from app.workers.retry import classify_failure, is_retryable_job_failure

logger = logging.getLogger(__name__)


def _job_timeout_seconds() -> float:
    # Worker timeout slightly above exploration so cleanup can run.
    base = float(settings.job_timeout_seconds or 1800)
    explore = float(settings.exploration_timeout_seconds or 300)
    return max(base, explore + 120)


def _max_attempts() -> int:
    return max(1, int(getattr(settings, "exploration_job_max_attempts", None) or 2))


def _cleanup_timeout() -> float:
    return max(5.0, float(getattr(settings, "exploration_cleanup_timeout_seconds", None) or 60))


def run_job_with_worker(
    *,
    worker_id: str,
    job_id: str,
    attempt: int = 1,
    runner: Callable[..., dict] | None = None,
    **kwargs: Any,
) -> dict | None:
    """Execute one job attempt under a worker identity + exclusive device slot."""
    registry = get_worker_registry()
    store = get_job_store()
    registry.assign_job(worker_id, job_id, attempt=attempt)
    registry.heartbeat(
        worker_id,
        health=WorkerHealth.BUSY,
        lifecycle=WorkerLifecycle.RESERVED,
        job_id=job_id,
    )
    logger.info("[WORKER] %s job=%s state=RESERVED attempt=%s", worker_id, job_id, attempt)

    outcome = "failed"
    result: dict | None = None
    cancel_flag = threading.Event()
    watchdog_stop = threading.Event()

    def _watch_cancel_and_timeout() -> None:
        started = time.monotonic()
        limit = _job_timeout_seconds()
        while not watchdog_stop.wait(1.0):
            registry.heartbeat(worker_id, job_id=job_id)
            if registry.is_cancel_requested(job_id):
                cancel_flag.set()
                logger.info("[JOB] job=%s cancel observed by watchdog", job_id)
                return
            if time.monotonic() - started >= limit:
                cancel_flag.set()
                registry.request_cancel(job_id)
                logger.warning("[JOB] job=%s worker timeout after %.0fs", job_id, limit)
                try:
                    store.update(
                        job_id,
                        status=JobStatus.TIMEOUT,
                        error_code="JOB_TIMEOUT",
                        error_message=f"Job exceeded {limit:.0f}s worker timeout.",
                        finished_at=datetime.now(timezone.utc),
                    )
                except Exception:
                    pass
                return

    watcher = threading.Thread(
        target=_watch_cancel_and_timeout,
        name=f"watch-{job_id[:8]}",
        daemon=True,
    )
    watcher.start()

    try:
        if cancel_flag.is_set() or registry.is_cancel_requested(job_id):
            store.update(
                job_id,
                status=JobStatus.CANCELLED,
                stage=JobStage.DONE,
                progress=100,
                finished_at=datetime.now(timezone.utc),
                error_code="CANCELLED",
                error_message="Cancelled before execution.",
            )
            outcome = "cancelled"
            return None

        registry.heartbeat(worker_id, lifecycle=WorkerLifecycle.STARTING_EMULATOR)
        logger.info("[EMULATOR] job=%s starting", job_id)

        with device_session(job_id) as slot:
            session = AndroidDeviceSession(
                job_id=job_id,
                worker_id=worker_id,
                device_id=slot.slot_id,
                adb_serial=slot.adb_serial or (settings.emulator_serial or "auto"),
                emulator_id=slot.slot_id,
                avd_name=slot.avd_name,
                temp_dir=str(Path(settings.temp_root) / "jobs" / job_id),
            )
            registry.heartbeat(
                worker_id,
                lifecycle=WorkerLifecycle.RUNNING,
                device_id=session.device_id,
                adb_serial=session.adb_serial,
            )
            logger.info(
                "[WORKER] %s job=%s state=RUNNING device=%s",
                worker_id,
                job_id,
                session.adb_serial,
            )

            # Prefer configured serial for this slot when present.
            if slot.adb_serial and "apk_path" in kwargs:
                # Stash for downstream device stage via thread-local / kwargs.
                kwargs = dict(kwargs)
                kwargs["_device_session"] = session

            if cancel_flag.is_set():
                raise _JobCancelled()

            run = runner
            if run is None:
                from app.services.analysis_pipeline import run_analysis_job

                run = run_analysis_job

            registry.heartbeat(worker_id, lifecycle=WorkerLifecycle.RUNNING)
            result = run(job_id, **{k: v for k, v in kwargs.items() if not k.startswith("_")})

            if cancel_flag.is_set() or registry.is_cancel_requested(job_id):
                record = store.get(job_id)
                if record and record.status == JobStatus.TIMEOUT:
                    outcome = "timeout"
                else:
                    outcome = "cancelled"
                    store.update(
                        job_id,
                        status=JobStatus.CANCELLED,
                        finished_at=datetime.now(timezone.utc),
                    )
            else:
                record = store.get(job_id)
                status = record.status if record else JobStatus.COMPLETED
                if status == JobStatus.TIMEOUT:
                    outcome = "timeout"
                elif status == JobStatus.CANCELLED:
                    outcome = "cancelled"
                elif status == JobStatus.FAILED:
                    outcome = "failed"
                else:
                    outcome = "completed"

            registry.heartbeat(worker_id, lifecycle=WorkerLifecycle.FINALIZING)
            logger.info("[JOB] job=%s finalizing outcome=%s", job_id, outcome)

    except _JobCancelled:
        outcome = "cancelled"
        try:
            store.update(
                job_id,
                status=JobStatus.CANCELLED,
                stage=JobStage.DONE,
                progress=100,
                finished_at=datetime.now(timezone.utc),
                error_code="CANCELLED",
                error_message="Cancelled by request.",
            )
        except Exception:
            pass
    except Exception as exc:
        outcome = "failed"
        info = classify_failure(exc=exc)
        logger.exception("[JOB] job=%s failed category=%s", job_id, info["category"])
        try:
            from app.core.errors import AppError

            code = "WORKER_ERROR"
            message = str(exc)[:500]
            if isinstance(exc, AppError):
                code = exc.code or code
                message = (exc.message or message)[:500]
            # Prefer a more specific failure already recorded by the pipeline.
            record = store.get(job_id)
            if (
                record
                and record.status == JobStatus.FAILED
                and record.error_code
                and record.error_code not in {"WORKER_ERROR", "INTERNAL_ERROR"}
            ):
                pass
            else:
                store.mark_failed(job_id, code, message)
        except Exception:
            pass
        # Bounded job-level retry for infrastructure failures.
        if (
            attempt < _max_attempts()
            and is_retryable_job_failure(exc=exc)
            and not registry.is_cancel_requested(job_id)
        ):
            registry.job_retries_bump = True  # type: ignore[attr-defined]
            try:
                rec = registry.get(worker_id)
                if rec:
                    rec.job_retries += 1
            except Exception:
                pass
            logger.info(
                "[JOB] job=%s scheduling retry attempt=%s",
                job_id,
                attempt + 1,
            )
            # Re-enqueue via pool if available (best-effort).
            try:
                from app.workers.pool import get_worker_pool

                pool = get_worker_pool()
                with pool._lock:
                    from app.workers.pool import QueuedJob

                    # Only if not already active/queued
                    if job_id not in pool._active and not any(
                        q.job_id == job_id for q in pool._queue
                    ):
                        pool._queue.append(
                            QueuedJob(
                                job_id=job_id,
                                kwargs={
                                    k: v
                                    for k, v in kwargs.items()
                                    if not k.startswith("_")
                                },
                                attempt=attempt + 1,
                            )
                        )
                pool._pump()
            except Exception:
                logger.warning("[JOB] job=%s retry enqueue failed", job_id, exc_info=True)
    finally:
        watchdog_stop.set()
        registry.heartbeat(worker_id, lifecycle=WorkerLifecycle.CLEANING)
        logger.info("[EMULATOR] job=%s cleanup start", job_id)
        _bounded_cleanup(job_id, worker_id)
        registry.release_job(worker_id, job_id, outcome=outcome)
        logger.info("[WORKER] %s idle after job=%s outcome=%s", worker_id, job_id, outcome)

    return result


def _bounded_cleanup(job_id: str, worker_id: str) -> None:
    """Best-effort cleanup with a hard time bound."""
    done = threading.Event()

    def _work() -> None:
        try:
            # Ensure device slot released even if context manager aborted.
            get_device_pool().release(job_id)
            if settings.emulator_stop_when_done and settings.exploration_enabled:
                try:
                    from app.modules.exploration.emulator import EmulatorManager

                    # Only stop if this environment owns a dedicated serial;
                    # shared single-AVD hosts may keep the process warm.
                    serials = (getattr(settings, "exploration_emulator_serials", None) or "").strip()
                    if serials:
                        EmulatorManager().stop()
                except Exception:
                    logger.warning(
                        "[EMULATOR] job=%s stop during cleanup failed",
                        job_id,
                        exc_info=True,
                    )
                    rec = get_worker_registry().get(worker_id)
                    if rec:
                        rec.cleanup_failures += 1
            # Temp APK removal is handled by analysis_pipeline finally.
        finally:
            done.set()

    thread = threading.Thread(target=_work, name=f"cleanup-{job_id[:8]}", daemon=True)
    thread.start()
    if not done.wait(timeout=_cleanup_timeout()):
        logger.error("[RELIABILITY] job=%s cleanup timed out", job_id)
        rec = get_worker_registry().get(worker_id)
        if rec:
            rec.cleanup_failures += 1


class _JobCancelled(Exception):
    pass


def is_job_cancel_requested(job_id: str) -> bool:
    return get_worker_registry().is_cancel_requested(job_id)
