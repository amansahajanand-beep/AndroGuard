"""Phase 12I — Bounded device/emulator slot pool.

Extends the original single-lock model so concurrency matches configured
emulator serials. Default remains one exclusive slot when only one device
is available — jobs queue rather than share an AVD.
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeviceSlot:
    slot_id: str
    adb_serial: str | None
    avd_name: str | None = None


def _configured_serials() -> list[str]:
    raw = (getattr(settings, "exploration_emulator_serials", None) or "").strip()
    if raw:
        return [s.strip() for s in raw.split(",") if s.strip()]
    single = (settings.emulator_serial or "").strip()
    return [single] if single else []


def configured_device_slots() -> list[DeviceSlot]:
    serials = _configured_serials()
    concurrency = max(1, int(getattr(settings, "exploration_worker_concurrency", None) or 1))
    # Never claim more slots than serials when serials are explicit.
    if serials:
        n = min(concurrency, len(serials))
        return [
            DeviceSlot(slot_id=f"slot-{i+1}", adb_serial=serials[i], avd_name=settings.avd_name)
            for i in range(n)
        ]
    # No explicit serials: one logical slot (shared AVD / auto-detect).
    return [
        DeviceSlot(slot_id="slot-1", adb_serial=None, avd_name=settings.avd_name)
        for _ in range(1)  # force 1 when serials unknown — safe default
    ]


class DevicePool:
    """Assign exclusive device slots to jobs (one job per slot)."""

    def __init__(self, slots: list[DeviceSlot] | None = None) -> None:
        self._slots = list(slots or configured_device_slots())
        self._lock = threading.Lock()
        self._available = list(self._slots)
        self._held: dict[str, DeviceSlot] = {}  # job_id -> slot
        self._cond = threading.Condition(self._lock)

    @property
    def capacity(self) -> int:
        return len(self._slots)

    def acquire(self, job_id: str, *, timeout: float | None = None) -> DeviceSlot | None:
        import time

        with self._cond:
            if job_id in self._held:
                return self._held[job_id]
            deadline = None if timeout is None else time.monotonic() + float(timeout)
            while not self._available:
                if timeout is not None:
                    remaining = (deadline or 0) - time.monotonic()
                    if remaining <= 0:
                        return None
                    self._cond.wait(timeout=remaining)
                else:
                    self._cond.wait()
            slot = self._available.pop(0)
            self._held[job_id] = slot
            logger.info(
                "[EMULATOR] job=%s acquired device=%s slot=%s",
                job_id,
                slot.adb_serial or "auto",
                slot.slot_id,
            )
            return slot

    def release(self, job_id: str) -> None:
        with self._cond:
            slot = self._held.pop(job_id, None)
            if slot is None:
                return
            self._available.append(slot)
            self._cond.notify()
            logger.info(
                "[EMULATOR] job=%s released device=%s slot=%s",
                job_id,
                slot.adb_serial or "auto",
                slot.slot_id,
            )

    def holder(self, job_id: str) -> DeviceSlot | None:
        with self._lock:
            return self._held.get(job_id)

    def active_count(self) -> int:
        with self._lock:
            return len(self._held)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "capacity": len(self._slots),
                "active": len(self._held),
                "available": len(self._available),
                "held_jobs": list(self._held.keys()),
            }


_POOL: DevicePool | None = None
_POOL_LOCK = threading.Lock()


def get_device_pool() -> DevicePool:
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            _POOL = DevicePool()
        return _POOL


def reset_device_pool_for_tests(slots: list[DeviceSlot] | None = None) -> DevicePool:
    global _POOL
    with _POOL_LOCK:
        _POOL = DevicePool(slots=slots)
        return _POOL


@contextmanager
def device_session(job_id: str, *, timeout: float | None = None) -> Iterator[DeviceSlot]:
    """Acquire an exclusive device slot for the job (blocks until available)."""
    pool = get_device_pool()
    slot = pool.acquire(job_id, timeout=timeout)
    if slot is None:
        raise TimeoutError(f"No device slot available for job {job_id}")
    try:
        yield slot
    finally:
        pool.release(job_id)
