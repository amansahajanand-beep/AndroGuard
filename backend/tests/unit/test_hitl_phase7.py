"""Phase 7 HITL unit tests."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from app.core.emulator_lock import (
    acquire_emulator,
    current_emulator_holder,
    emulator_session,
    release_emulator,
    try_acquire_emulator,
)
from app.jobs.models import JobRecord, JobStatus
from app.modules.exploration.ui_element import UIElement
from app.modules.hitl import (
    ExplorationCheckpoint,
    HumanDecision,
    InterventionDetector,
    InterventionManager,
    InterventionStatus,
    InterventionType,
    get_intervention_store,
    register_manager,
    unregister_manager,
)
from app.modules.hitl.intervention_types import DetectionResult


def _el(
    text: str = "",
    *,
    desc: str = "",
    rid: str = "",
    package: str = "com.example.app",
    clickable: bool = True,
) -> UIElement:
    return UIElement(
        text=text,
        content_description=desc,
        resource_id=rid,
        package=package,
        bounds=(0, 0, 100, 80),
        clickable=clickable,
        enabled=True,
        visible=True,
    )


@pytest.fixture
def detector() -> InterventionDetector:
    return InterventionDetector(target_package="com.example.app")


# --------------------------------------------------------------------------- detection


def test_terms_screen_detected(detector: InterventionDetector) -> None:
    result = detector.detect(
        elements=[
            _el("Terms and Conditions"),
            _el("I Agree"),
            _el("Decline", clickable=True),
        ],
        package="com.example.app",
        activity="com.example.app/.TermsActivity",
    )
    assert result.required
    assert result.type is InterventionType.TERMS_CONSENT


def test_privacy_consent_detected(detector: InterventionDetector) -> None:
    result = detector.detect(
        elements=[_el("Privacy Policy"), _el("Agree to Privacy Policy")],
        package="com.example.app",
        activity="com.example.app/.PrivacyPolicySetting",
    )
    assert result.required
    assert result.type is InterventionType.PRIVACY_CONSENT


def test_permission_dialog_detected(detector: InterventionDetector) -> None:
    result = detector.detect(
        elements=[
            _el("Allow Notifications?", package="com.android.permissioncontroller"),
            _el("Allow", package="com.android.permissioncontroller"),
            _el("Don't allow", package="com.android.permissioncontroller"),
        ],
        package="com.android.permissioncontroller",
        activity="com.android.permissioncontroller/.permission.ui.GrantPermissionsActivity",
    )
    assert result.required
    assert result.type is InterventionType.PERMISSION
    assert result.is_system_ui


def test_default_app_screen_detected(detector: InterventionDetector) -> None:
    result = detector.detect(
        elements=[_el("Set as default"), _el("Always"), _el("Just once")],
        package="com.android.settings",
        activity="com.android.settings/.Settings$ManageApplicationsActivity",
    )
    assert result.required
    assert result.type is InterventionType.DEFAULT_APP


def test_system_settings_screen_detected(detector: InterventionDetector) -> None:
    result = detector.detect(
        elements=[_el("Display over other apps"), _el("Allow")],
        package="com.android.settings",
        activity="com.android.settings/.Settings",
    )
    assert result.required
    assert result.type in {
        InterventionType.SYSTEM_SETTINGS,
        InterventionType.DEFAULT_APP,
        InterventionType.PERMISSION,
    }


def test_login_detected(detector: InterventionDetector) -> None:
    result = detector.detect(
        elements=[_el("Email"), _el("Password"), _el("Sign in")],
        package="com.example.app",
        activity="com.example.app/.LoginActivity",
    )
    assert result.required
    assert result.type is InterventionType.LOGIN


def test_otp_detected(detector: InterventionDetector) -> None:
    result = detector.detect(
        elements=[_el("Enter verification code"), _el("OTP"), _el("Submit")],
        package="com.example.app",
        activity="com.example.app/.VerifyActivity",
    )
    assert result.required
    assert result.type is InterventionType.OTP


def test_captcha_detected(detector: InterventionDetector) -> None:
    result = detector.detect(
        elements=[_el("Verify you are human"), _el("I'm not a robot")],
        package="com.example.app",
        activity="com.example.app/.WebViewActivity",
    )
    assert result.required
    assert result.type is InterventionType.CAPTCHA


def test_unknown_blocking_screen_detected(detector: InterventionDetector) -> None:
    result = detector.detect(
        elements=[
            _el("Please review and accept to continue"),
            _el("Agree"),
            _el("Continue"),
        ],
        package="com.example.app",
        activity="com.example.app/.GateActivity",
    )
    assert result.required
    assert result.type in {
        InterventionType.UNKNOWN_BLOCKING_SCREEN,
        InterventionType.TERMS_CONSENT,
        InterventionType.PRIVACY_CONSENT,
    }


def test_normal_app_screen_does_not_trigger_hitl(detector: InterventionDetector) -> None:
    result = detector.detect(
        elements=[
            _el("Home"),
            _el("Alarms"),
            _el("Settings"),
            _el("Add alarm"),
        ],
        package="com.example.app",
        activity="com.example.app/.MainActivity",
    )
    assert result.required is False


# --------------------------------------------------------------------------- job / manager


def test_running_to_waiting_for_human(tmp_path: Path) -> None:
    from app.jobs.store import get_job_store

    job_id = "11111111-1111-4111-8111-111111111111"
    store = get_job_store()
    if store.get(job_id) is None:
        store.create(JobRecord(id=job_id, status=JobStatus.RUNNING))
    else:
        store.update(job_id, status=JobStatus.RUNNING, intervention=None)

    manager = InterventionManager(
        job_id,
        timeout_seconds=5,
        artifact_dir=tmp_path,
    )
    register_manager(manager)
    try:
        detection = DetectionResult(
            required=True,
            type=InterventionType.PERMISSION,
            title="Allow notifications",
            message="Human action required",
        )
        started = threading.Event()

        def worker() -> None:
            started.set()
            manager.request_intervention(
                detection,
                package="com.example",
                activity="com.android.permissioncontroller/.X",
                screenshot_bytes=b"\x89PNG",
                checkpoint=ExplorationCheckpoint(job_id=job_id, intervention_id=""),
            )

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        assert started.wait(2)
        time.sleep(0.3)
        record = store.get(job_id)
        assert record is not None
        assert record.status is JobStatus.WAITING_FOR_HUMAN
        assert record.intervention is not None
        assert record.intervention["type"] == "permission"
        payload = record.public_payload()
        assert payload["status"] == "waiting_for_human"
        assert "intervention" in payload

        iid = record.intervention["id"]
        assert manager.signal_continue(iid)["success"] is True
        t.join(timeout=3)
        assert not t.is_alive()
        assert store.get(job_id).status is JobStatus.RUNNING
    finally:
        unregister_manager(job_id)


def test_continue_resumes_exploration(tmp_path: Path) -> None:
    from app.jobs.store import get_job_store

    job_id = "22222222-2222-4222-8222-222222222222"
    store = get_job_store()
    if store.get(job_id) is None:
        store.create(JobRecord(id=job_id, status=JobStatus.RUNNING))
    else:
        store.update(job_id, status=JobStatus.RUNNING)

    manager = InterventionManager(job_id, timeout_seconds=5, artifact_dir=tmp_path)
    register_manager(manager)
    decisions: list[HumanDecision] = []

    def worker() -> None:
        _i, decision = manager.request_intervention(
            DetectionResult(
                required=True,
                type=InterventionType.TERMS_CONSENT,
                title="Accept Terms",
            ),
            package="com.example",
            activity="terms",
            checkpoint=ExplorationCheckpoint(
                job_id=job_id,
                intervention_id="",
                current_state_id="shot-entry",
                parent_state_id=None,
                depth=0,
            ),
        )
        decisions.append(decision)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    time.sleep(0.3)
    record = store.get(job_id)
    assert record and record.status is JobStatus.WAITING_FOR_HUMAN
    checkpoint = record.exploration_checkpoint
    assert checkpoint and checkpoint.get("current_state_id") == "shot-entry"
    iid = record.intervention["id"]
    manager.signal_continue(iid)
    t.join(timeout=3)
    assert decisions == [HumanDecision.CONTINUE]
    assert store.get(job_id).status is JobStatus.RUNNING
    unregister_manager(job_id)


def test_skip_resumes_exploration(tmp_path: Path) -> None:
    from app.jobs.store import get_job_store

    job_id = "33333333-3333-4333-8333-333333333333"
    store = get_job_store()
    if store.get(job_id) is None:
        store.create(JobRecord(id=job_id, status=JobStatus.RUNNING))
    manager = InterventionManager(job_id, timeout_seconds=5, artifact_dir=tmp_path)
    register_manager(manager)
    out: list[HumanDecision] = []

    def worker() -> None:
        _i, d = manager.request_intervention(
            DetectionResult(required=True, type=InterventionType.LOGIN, title="Sign in"),
            package="com.example",
            activity="login",
            checkpoint=ExplorationCheckpoint(job_id=job_id, intervention_id=""),
        )
        out.append(d)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    time.sleep(0.3)
    iid = store.get(job_id).intervention["id"]
    manager.signal_skip(iid)
    t.join(timeout=3)
    assert out == [HumanDecision.SKIP]
    assert get_intervention_store().get(iid).status is InterventionStatus.SKIPPED
    unregister_manager(job_id)


def test_stop_terminates_exploration(tmp_path: Path) -> None:
    from app.jobs.store import get_job_store

    job_id = "44444444-4444-4444-8444-444444444444"
    store = get_job_store()
    if store.get(job_id) is None:
        store.create(JobRecord(id=job_id, status=JobStatus.RUNNING))
    manager = InterventionManager(job_id, timeout_seconds=5, artifact_dir=tmp_path)
    register_manager(manager)
    out: list[HumanDecision] = []

    def worker() -> None:
        _i, d = manager.request_intervention(
            DetectionResult(required=True, type=InterventionType.CAPTCHA, title="CAPTCHA"),
            package="com.example",
            activity="captcha",
            checkpoint=ExplorationCheckpoint(job_id=job_id, intervention_id=""),
        )
        out.append(d)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    time.sleep(0.3)
    iid = store.get(job_id).intervention["id"]
    manager.signal_stop(iid)
    t.join(timeout=3)
    assert out == [HumanDecision.STOP]
    assert manager.stopped is True
    unregister_manager(job_id)


def test_timeout_handled_safely(tmp_path: Path) -> None:
    from app.jobs.store import get_job_store

    job_id = "55555555-5555-4555-8555-555555555555"
    store = get_job_store()
    if store.get(job_id) is None:
        store.create(JobRecord(id=job_id, status=JobStatus.RUNNING))
    manager = InterventionManager(job_id, timeout_seconds=0.4, artifact_dir=tmp_path)
    register_manager(manager)
    _i, decision = manager.request_intervention(
        DetectionResult(required=True, type=InterventionType.OTP, title="OTP"),
        package="com.example",
        activity="otp",
        checkpoint=ExplorationCheckpoint(job_id=job_id, intervention_id=""),
    )
    assert decision is HumanDecision.TIMEOUT
    assert store.get(job_id).status is JobStatus.TIMEOUT
    unregister_manager(job_id)


def test_emulator_state_preserved(tmp_path: Path) -> None:
    from app.jobs.store import get_job_store

    job_id = "66666666-6666-4666-8666-666666666666"
    store = get_job_store()
    if store.get(job_id) is None:
        store.create(JobRecord(id=job_id, status=JobStatus.RUNNING))
    manager = InterventionManager(job_id, timeout_seconds=5, artifact_dir=tmp_path)
    register_manager(manager)
    checkpoint = ExplorationCheckpoint(
        job_id=job_id,
        intervention_id="",
        current_state_id="shot-abc",
        parent_state_id="shot-root",
        current_activity="com.example/.Privacy",
        current_package="com.example",
        depth=2,
        visited_states=["shot-root", "shot-abc"],
        visited_actions={"shot-root": ["tap:1"]},
        navigation_graph={"current_state_id": "shot-abc"},
    )

    def worker() -> None:
        manager.request_intervention(
            DetectionResult(
                required=True,
                type=InterventionType.PRIVACY_CONSENT,
                title="Privacy",
            ),
            package="com.example",
            activity="com.example/.Privacy",
            checkpoint=checkpoint,
            fingerprint="deadbeef",
        )

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    time.sleep(0.3)
    record = store.get(job_id)
    assert record.exploration_checkpoint["current_state_id"] == "shot-abc"
    assert record.exploration_checkpoint["depth"] == 2
    iid = record.intervention["id"]
    saved = get_intervention_store().get_checkpoint(iid)
    assert saved is not None
    assert saved.visited_states == ["shot-root", "shot-abc"]
    assert saved.blocked_fingerprint == "deadbeef"
    manager.signal_continue(iid)
    t.join(timeout=3)
    unregister_manager(job_id)


def test_crawler_resumes_from_correct_state(tmp_path: Path) -> None:
    """Continue keeps the same checkpoint; explorer stays on current_state_id."""
    from app.jobs.store import get_job_store

    job_id = "77777777-7777-4777-8777-777777777777"
    store = get_job_store()
    if store.get(job_id) is None:
        store.create(JobRecord(id=job_id, status=JobStatus.RUNNING))
    manager = InterventionManager(job_id, timeout_seconds=5, artifact_dir=tmp_path)
    register_manager(manager)
    held: list[ExplorationCheckpoint | None] = []

    def worker() -> None:
        _i, _d = manager.request_intervention(
            DetectionResult(
                required=True,
                type=InterventionType.PERMISSION,
                title="Allow",
            ),
            package="com.example",
            activity="perm",
            checkpoint=ExplorationCheckpoint(
                job_id=job_id,
                intervention_id="",
                current_state_id="shot-paused",
                parent_state_id="shot-parent",
                depth=3,
            ),
        )
        held.append(manager.last_checkpoint)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    time.sleep(0.3)
    iid = store.get(job_id).intervention["id"]
    manager.signal_continue(iid)
    t.join(timeout=3)
    assert held and held[0] is not None
    assert held[0].current_state_id == "shot-paused"
    assert held[0].parent_state_id == "shot-parent"
    assert held[0].depth == 3
    unregister_manager(job_id)


def test_emulator_cannot_be_used_by_two_jobs() -> None:
    # Ensure clean slate.
    holder = current_emulator_holder()
    if holder:
        release_emulator(holder)

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


def test_public_payload_includes_intervention() -> None:
    record = JobRecord(
        id="88888888-8888-4888-8888-888888888888",
        status=JobStatus.WAITING_FOR_HUMAN,
        progress=42,
        intervention={
            "id": "hitl_abc",
            "type": "permission",
            "title": "Allow notifications",
            "message": "Please complete this action in the emulator.",
            "screenshot": "/api/v1/analyze-apk/x/intervention/hitl_abc/screenshot",
        },
    )
    payload = record.public_payload()
    assert payload["status"] == "waiting_for_human"
    assert payload["progress"] == 42
    assert payload["intervention"]["type"] == "permission"


def test_still_blocked_after_continue(detector: InterventionDetector) -> None:
    previous = DetectionResult(
        required=True,
        type=InterventionType.PERMISSION,
        title="Allow",
    )
    assert (
        detector.still_blocked(
            elements=[_el("Allow notifications"), _el("Allow"), _el("Don't allow")],
            package="com.android.permissioncontroller",
            activity="GrantPermissionsActivity",
            previous=previous,
        )
        is True
    )
    assert (
        detector.still_blocked(
            elements=[_el("Home"), _el("Alarms")],
            package="com.example.app",
            activity="MainActivity",
            previous=previous,
        )
        is False
    )
