"""Process-wide emulator exclusivity (Phase 12I: multi-slot device pool).

A single AVD must never be driven by two analysis jobs at once. When multiple
emulator serials are configured, each job gets an exclusive slot. HITL pause
paths share the same pool so waiting for a human does not free the device
for another job.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from app.workers.device_pool import DeviceSlot, get_device_pool

logger = logging.getLogger(__name__)


def try_acquire_emulator(job_id: str) -> bool:
    """Non-blocking acquire. Returns False if no slot is available."""
    pool = get_device_pool()
    if pool.holder(job_id) is not None:
        return True
    slot = pool.acquire(job_id, timeout=0.0)
    return slot is not None


def acquire_emulator(job_id: str, *, blocking: bool = True, timeout: float | None = None) -> bool:
    """Acquire a device slot for ``job_id``."""
    pool = get_device_pool()
    if pool.holder(job_id) is not None:
        return True
    if not blocking and timeout is None:
        timeout = 0.0
    slot = pool.acquire(job_id, timeout=timeout)
    return slot is not None


def release_emulator(job_id: str | None = None) -> None:
    """Release the device slot held by ``job_id``."""
    if not job_id:
        return
    get_device_pool().release(job_id)


def current_emulator_holder() -> str | None:
    snap = get_device_pool().snapshot()
    held = snap.get("held_jobs") or []
    return held[0] if held else None


def emulator_is_locked() -> bool:
    return get_device_pool().active_count() > 0


def current_slot(job_id: str) -> DeviceSlot | None:
    return get_device_pool().holder(job_id)


@contextmanager
def emulator_session(job_id: str) -> Iterator[None]:
    """Hold an exclusive device slot for the duration of a job's device stage.

    If the worker pool already reserved a slot for this job, reuse it (do not
    double-acquire).
    """
    pool = get_device_pool()
    owned = pool.holder(job_id) is not None
    if not owned:
        slot = pool.acquire(job_id, timeout=None)
        if slot is None:
            raise RuntimeError(f"Could not acquire emulator slot for job {job_id}")
    try:
        yield
    finally:
        if not owned:
            pool.release(job_id)
