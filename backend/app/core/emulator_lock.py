"""Process-wide emulator exclusivity.

A single AVD must never be driven by two analysis jobs at once. Both the
analysis pipeline and HITL pause/resume paths share this lock so waiting for a
human does not free the device for another job.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

# One AVD ⇒ one device session. Concurrent jobs queue here rather than fighting
# over the same emulator.
_DEVICE_LOCK = threading.Semaphore(1)
_HOLDER_LOCK = threading.Lock()
_HOLDER_JOB_ID: str | None = None


def try_acquire_emulator(job_id: str) -> bool:
    """Non-blocking acquire. Returns False if another job holds the emulator."""
    global _HOLDER_JOB_ID
    if not _DEVICE_LOCK.acquire(blocking=False):
        with _HOLDER_LOCK:
            return _HOLDER_JOB_ID == job_id
    with _HOLDER_LOCK:
        _HOLDER_JOB_ID = job_id
    return True


def acquire_emulator(job_id: str, *, blocking: bool = True, timeout: float | None = None) -> bool:
    """Acquire the emulator lock for ``job_id``."""
    global _HOLDER_JOB_ID
    if timeout is None:
        ok = _DEVICE_LOCK.acquire(blocking=blocking)
    else:
        ok = _DEVICE_LOCK.acquire(blocking=blocking, timeout=timeout)
    if not ok:
        return False
    with _HOLDER_LOCK:
        _HOLDER_JOB_ID = job_id
    return True


def release_emulator(job_id: str | None = None) -> None:
    """Release the emulator lock. Ignores mismatched job ids when provided."""
    global _HOLDER_JOB_ID
    with _HOLDER_LOCK:
        if job_id is not None and _HOLDER_JOB_ID is not None and _HOLDER_JOB_ID != job_id:
            return
        holder = _HOLDER_JOB_ID
        _HOLDER_JOB_ID = None
    if holder is not None or job_id is None:
        try:
            _DEVICE_LOCK.release()
        except ValueError:
            # Already unlocked.
            pass


def current_emulator_holder() -> str | None:
    with _HOLDER_LOCK:
        return _HOLDER_JOB_ID


def emulator_is_locked() -> bool:
    return current_emulator_holder() is not None or _DEVICE_LOCK._value == 0  # noqa: SLF001


@contextmanager
def emulator_session(job_id: str) -> Iterator[None]:
    """Hold the emulator exclusively for the duration of a job's device stage."""
    acquire_emulator(job_id, blocking=True)
    try:
        yield
    finally:
        release_emulator(job_id)
