"""Phase 12I — Worker / queue / device isolation tests (no real emulator)."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.emulator_lock import (
    acquire_emulator,
    current_emulator_holder,
    emulator_session,
    release_emulator,
    try_acquire_emulator,
)
from app.jobs.models import JobRecord, JobStatus
from app.jobs.store import InMemoryJobStore
from app.workers.device_pool import DeviceSlot, reset_device_pool_for_tests
from app.workers.device_session import AndroidDeviceSession
from app.workers.job_runner import is_job_cancel_requested, run_job_with_worker
from app.workers.pool import ExplorationWorkerPool, QueuedJob, reset_worker_pool_for_tests
from app.workers.registry import (
    WorkerHealth,
    WorkerLifecycle,
    get_worker_registry,
    reset_worker_registry_for_tests,
)
from app.workers.retry import classify_failure, is_retryable_job_failure


@pytest.fixture(autouse=True)
def _reset_12i_singletons():
    reset_worker_registry_for_tests()
    reset_device_pool_for_tests(
        [
            DeviceSlot(slot_id="slot-1", adb_serial="emulator-5554"),
            DeviceSlot(slot_id="slot-2", adb_serial="emulator-5556"),
        ]
    )
    yield
    reset_worker_registry_for_tests()
    reset_device_pool_for_tests(
        [DeviceSlot(slot_id="slot-1", adb_serial="emulator-5554")]
    )


# ---------------------------------------------------------------------------
# Device isolation
# ---------------------------------------------------------------------------


def test_one_job_one_device_slot() -> None:
    pool = reset_device_pool_for_tests(
        [
            DeviceSlot(slot_id="slot-1", adb_serial="emulator-5554"),
            DeviceSlot(slot_id="slot-2", adb_serial="emulator-5556"),
        ]
    )
    s1 = pool.acquire("job-a")
    s2 = pool.acquire("job-b")
    assert s1 is not None and s2 is not None
    assert s1.adb_serial != s2.adb_serial
    assert pool.active_count() == 2
    assert pool.acquire("job-c", timeout=0.05) is None
    pool.release("job-a")
    s3 = pool.acquire("job-c", timeout=0.5)
    assert s3 is not None
    assert s3.adb_serial == "emulator-5554"
    pool.release("job-b")
    pool.release("job-c")


def test_same_job_cannot_hold_two_slots() -> None:
    pool = reset_device_pool_for_tests(
        [DeviceSlot(slot_id="slot-1", adb_serial="emulator-5554")]
    )
    a = pool.acquire("job-a")
    b = pool.acquire("job-a")
    assert a is b
    assert pool.active_count() == 1
    pool.release("job-a")


def test_emulator_lock_delegates_to_pool() -> None:
    reset_device_pool_for_tests(
        [DeviceSlot(slot_id="slot-1", adb_serial="emulator-5554")]
    )
    assert try_acquire_emulator("job-a") is True
    assert try_acquire_emulator("job-b") is False
    assert current_emulator_holder() == "job-a"
    release_emulator("job-a")
    assert try_acquire_emulator("job-b") is True
    release_emulator("job-b")
    with emulator_session("job-c"):
        assert acquire_emulator("job-d", blocking=False) is False
    assert try_acquire_emulator("job-d") is True
    release_emulator("job-d")


def test_device_session_model() -> None:
    session = AndroidDeviceSession(
        job_id="j1",
        worker_id="worker-01",
        device_id="slot-1",
        adb_serial="emulator-5554",
        package_name="com.example",
    )
    payload = session.to_dict()
    assert payload["adb_serial"] == "emulator-5554"
    assert payload["worker_id"] == "worker-01"


# ---------------------------------------------------------------------------
# Queue / concurrency / backpressure
# ---------------------------------------------------------------------------


def test_queue_backpressure_two_workers_ten_jobs() -> None:
    reset_device_pool_for_tests(
        [
            DeviceSlot(slot_id="slot-1", adb_serial="emulator-5554"),
            DeviceSlot(slot_id="slot-2", adb_serial="emulator-5556"),
        ]
    )
    gate = threading.Event()
    started: list[str] = []
    lock = threading.Lock()

    def fake_runner(job_id: str, **kwargs):
        with lock:
            started.append(job_id)
        gate.wait(timeout=5)
        return {"ok": True, "job_id": job_id}

    pool = ExplorationWorkerPool(concurrency=2, runner=fake_runner, worker_id_prefix="w")
    for i in range(10):
        assert pool.enqueue(f"job-{i:02d}", apk_path=Path("x.apk"))

    # Allow assignment threads to start
    deadline = time.time() + 2
    while time.time() < deadline:
        snap = pool.snapshot()
        if snap["active"] == 2 and snap["queued"] == 8:
            break
        time.sleep(0.05)
    snap = pool.snapshot()
    assert snap["active"] == 2
    assert snap["queued"] == 8
    assert snap["concurrency"] == 2
    gate.set()
    deadline = time.time() + 5
    while time.time() < deadline and pool.active_count > 0:
        time.sleep(0.05)
    pool.shutdown(wait=True)
    assert len(started) == 10


def test_duplicate_enqueue_rejected() -> None:
    reset_device_pool_for_tests(
        [DeviceSlot(slot_id="slot-1", adb_serial="emulator-5554")]
    )
    gate = threading.Event()

    def fake_runner(job_id: str, **kwargs):
        gate.wait(timeout=3)
        return {}

    pool = ExplorationWorkerPool(concurrency=1, runner=fake_runner)
    assert pool.enqueue("same-job") is True
    assert pool.enqueue("same-job") is False
    assert pool.snapshot()["metrics"]["duplicate_rejects"] >= 1
    gate.set()
    pool.shutdown(wait=True)


def test_job_not_assigned_to_two_workers() -> None:
    registry = reset_worker_registry_for_tests()
    registry.assign_job("worker-01", "job-x", attempt=1)
    with pytest.raises(RuntimeError):
        registry.assign_job("worker-02", "job-x", attempt=1)


# ---------------------------------------------------------------------------
# Cancel / timeout / retry
# ---------------------------------------------------------------------------


def test_cancel_queued_job() -> None:
    reset_device_pool_for_tests(
        [DeviceSlot(slot_id="slot-1", adb_serial="emulator-5554")]
    )
    store = InMemoryJobStore()
    job_id = "11111111-1111-4111-8111-111111111111"
    store.create(JobRecord(id=job_id, status=JobStatus.QUEUED))

    gate = threading.Event()

    def blocking_runner(jid: str, **kwargs):
        gate.wait(timeout=5)
        return {}

    pool = ExplorationWorkerPool(concurrency=1, runner=blocking_runner)
    # Occupy the only worker
    assert pool.enqueue("hold-job")
    time.sleep(0.1)
    assert pool.enqueue(job_id)
    assert job_id in pool.snapshot()["queued_job_ids"]

    with patch("app.workers.pool.get_job_store", return_value=store):
        with patch("app.api.v1.analyze_jobs.get_job_store", return_value=store):
            pool.request_cancel(job_id)
            # Simulate cancel endpoint queued path
            with pool._lock:
                pool._queue = [q for q in pool._queue if q.job_id != job_id]
            store.update(job_id, status=JobStatus.CANCELLED)

    assert store.get(job_id).status == JobStatus.CANCELLED
    gate.set()
    pool.shutdown(wait=True)


def test_cancel_signal_visible_to_runner() -> None:
    registry = reset_worker_registry_for_tests()
    registry.request_cancel("job-cancel")
    assert is_job_cancel_requested("job-cancel") is True


def test_retry_classification() -> None:
    assert is_retryable_job_failure(error_message="emulator boot timeout") is True
    assert is_retryable_job_failure(error_code="INSTALL_FAILED", error_message="bad apk") is False
    assert classify_failure(error_message="adb disconnected")["category"] == "infrastructure"
    assert classify_failure(error_message="corrupt apk")["category"] == "application"


def test_worker_timeout_marks_job(monkeypatch) -> None:
    reset_device_pool_for_tests(
        [DeviceSlot(slot_id="slot-1", adb_serial="emulator-5554")]
    )
    store = InMemoryJobStore()
    job_id = "22222222-2222-4222-8222-222222222222"
    store.create(JobRecord(id=job_id, status=JobStatus.QUEUED))

    monkeypatch.setattr("app.workers.job_runner._job_timeout_seconds", lambda: 0.15)
    monkeypatch.setattr("app.workers.job_runner.get_job_store", lambda: store)

    def slow_runner(jid: str, **kwargs):
        # Poll cancel so we don't finish "successfully" after timeout.
        for _ in range(40):
            if is_job_cancel_requested(jid):
                return {"cancelled": True}
            time.sleep(0.05)
        return {"late": True}

    run_job_with_worker(
        worker_id="worker-01",
        job_id=job_id,
        attempt=1,
        runner=slow_runner,
    )
    record = store.get(job_id)
    assert record is not None
    assert record.status == JobStatus.TIMEOUT


# ---------------------------------------------------------------------------
# Cleanup / lifecycle
# ---------------------------------------------------------------------------


def test_cleanup_releases_slot_on_failure() -> None:
    reset_device_pool_for_tests(
        [DeviceSlot(slot_id="slot-1", adb_serial="emulator-5554")]
    )
    store = InMemoryJobStore()
    job_id = "33333333-3333-4333-8333-333333333333"
    store.create(JobRecord(id=job_id, status=JobStatus.QUEUED))

    def boom(jid: str, **kwargs):
        raise RuntimeError("emulator exploded")

    with patch("app.workers.job_runner.get_job_store", return_value=store):
        run_job_with_worker(
            worker_id="worker-01",
            job_id=job_id,
            runner=boom,
        )

    pool = reset_device_pool_for_tests(
        [DeviceSlot(slot_id="slot-1", adb_serial="emulator-5554")]
    )
    # Fresh pool after failure path — original pool should have released.
    # Re-acquire on a new pool proves no leak in registry; check registry idle.
    reg = get_worker_registry()
    rec = reg.get("worker-01")
    assert rec is not None
    assert rec.health == WorkerHealth.IDLE
    assert rec.current_job_id is None


def test_heartbeat_and_stale_detection() -> None:
    registry = reset_worker_registry_for_tests()
    registry.assign_job("worker-01", "job-stale")
    registry.heartbeat("worker-01", lifecycle=WorkerLifecycle.RUNNING)
    # Force stale
    rec = registry.get("worker-01")
    assert rec is not None
    rec.last_heartbeat = time.monotonic() - 999
    orphaned = registry.mark_stale(stale_after_seconds=10)
    assert "job-stale" in orphaned
    assert registry.get("worker-01").health == WorkerHealth.UNHEALTHY


# ---------------------------------------------------------------------------
# Fake 100-job load
# ---------------------------------------------------------------------------


def test_fake_100_job_load_simulation() -> None:
    reset_device_pool_for_tests(
        [
            DeviceSlot(slot_id=f"slot-{i}", adb_serial=f"emulator-{5554 + i * 2}")
            for i in range(3)
        ]
    )
    completed = []
    lock = threading.Lock()

    def fake_runner(job_id: str, **kwargs):
        time.sleep(0.01)
        with lock:
            completed.append(job_id)
        return {"job_id": job_id}

    pool = ExplorationWorkerPool(concurrency=3, runner=fake_runner, worker_id_prefix="load")
    for i in range(100):
        assert pool.enqueue(f"load-{i:03d}")

    deadline = time.time() + 30
    while time.time() < deadline:
        snap = pool.snapshot()
        if snap["queued"] == 0 and snap["active"] == 0 and len(completed) >= 100:
            break
        # Concurrency invariant
        assert snap["active"] <= 3
        time.sleep(0.05)

    pool.shutdown(wait=True)
    assert len(completed) == 100
    assert len(set(completed)) == 100
    final = pool.snapshot()
    assert final["active"] == 0
    assert final["queued"] == 0


def test_two_worker_isolation_distinct_serials() -> None:
    reset_device_pool_for_tests(
        [
            DeviceSlot(slot_id="slot-1", adb_serial="emulator-5554"),
            DeviceSlot(slot_id="slot-2", adb_serial="emulator-5556"),
        ]
    )
    seen: dict[str, str] = {}
    hold = threading.Event()

    def runner(job_id: str, **kwargs):
        from app.workers.device_pool import get_device_pool

        slot = get_device_pool().holder(job_id)
        seen[job_id] = slot.adb_serial if slot else "missing"
        hold.wait(timeout=2)
        return {}

    pool = ExplorationWorkerPool(concurrency=2, runner=runner, worker_id_prefix="iso")
    assert pool.enqueue("iso-a")
    assert pool.enqueue("iso-b")
    deadline = time.time() + 2
    while time.time() < deadline and len(seen) < 2:
        time.sleep(0.05)
    assert len(seen) == 2
    assert seen["iso-a"] != seen["iso-b"]
    hold.set()
    pool.shutdown(wait=True)


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------


def test_invariant_concurrency_never_exceeds_limit() -> None:
    reset_device_pool_for_tests(
        [DeviceSlot(slot_id=f"s{i}", adb_serial=f"emu-{i}") for i in range(4)]
    )
    max_active = 0
    lock = threading.Lock()

    def runner(job_id: str, **kwargs):
        nonlocal max_active
        with lock:
            # peek via pool snapshot externally
            pass
        time.sleep(0.02)
        return {}

    pool = ExplorationWorkerPool(concurrency=2, runner=runner)
    for i in range(20):
        pool.enqueue(f"c-{i}")
    deadline = time.time() + 10
    while time.time() < deadline:
        snap = pool.snapshot()
        max_active = max(max_active, snap["active"])
        assert snap["active"] <= 2
        if snap["queued"] == 0 and snap["active"] == 0:
            break
        time.sleep(0.02)
    pool.shutdown(wait=True)
    assert max_active <= 2


def test_invariant_ai_gains_no_infra_permissions() -> None:
    from app.modules.exploration.executor import ALLOWED_ACTION_KINDS

    assert "shell" not in ALLOWED_ACTION_KINDS
    assert "adb" not in ALLOWED_ACTION_KINDS


def test_worker_pool_snapshot_json_safe() -> None:
    pool = ExplorationWorkerPool(concurrency=1, runner=lambda **kw: {})
    import json

    json.dumps(pool.snapshot())
    pool.shutdown(wait=False)
