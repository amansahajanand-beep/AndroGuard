"""Phase 12D — Exploration Supervisor unit + chain tests."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from app.modules.exploration.action_planner import PlannedAction
from app.modules.exploration.actions import ActionResult, TapAction, WaitAction
from app.modules.exploration.agent_state import AgentState
from app.modules.exploration.executor import ActionExecutor, ExecutorResult
from app.modules.exploration.observation_builder import build_observation
from app.modules.exploration.planner import ExplorationPlanner
from app.modules.exploration.supervisor import (
    ExplorationSupervisor,
    SupervisorContext,
    SupervisorDecisionKind,
)
from app.modules.exploration.ui_element import UIElement
from app.modules.exploration.verifier import ActionVerifier, VerifyOutcome, VerifyResult


def _el(**kwargs) -> UIElement:
    defaults = dict(
        text="Settings",
        resource_id="",
        content_description="",
        class_name="android.widget.Button",
        package="com.example.app",
        bounds=(40, 200, 400, 280),
        clickable=True,
        enabled=True,
        scrollable=False,
        visible=True,
        selected=False,
        checked=False,
        focused=False,
        focusable=True,
    )
    defaults.update(kwargs)
    return UIElement(**defaults)


def _planned(key: str = "tap:Settings", kind: str = "tap") -> PlannedAction:
    return PlannedAction(
        key=key,
        action=TapAction(element=_el()),
        kind=kind,
        priority=10,
        label="Settings",
    )


def _verify(
    outcome: VerifyOutcome,
    *,
    before: str | None = "home",
    after: str | None = "home",
    hitl: bool = False,
) -> VerifyResult:
    return VerifyResult(
        outcome=outcome,
        before_state_id=before,
        after_state_id=after,
        hitl_appeared=hitl,
        reason=outcome.value.lower(),
    )


def _exec(
    *,
    ok: bool = True,
    rejected: bool = False,
    error: str | None = None,
    key: str = "tap:Settings",
) -> ExecutorResult:
    return ExecutorResult(
        action_id="abc123",
        action_kind="tap",
        action_key=key,
        success=ok and not rejected,
        started_at="t0",
        completed_at="t1",
        duration_ms=10,
        error=error,
        error_type="rejected" if rejected else ("ui_failure" if not ok else None),
        before_state_id="home",
        rejected=rejected,
    )


def test_success_continue() -> None:
    sup = ExplorationSupervisor()
    d = sup.decide(
        SupervisorContext(
            verify=_verify(VerifyOutcome.SUCCESS, after="home"),
            executor=_exec(ok=True),
            planned=_planned(),
            has_parent=True,
            app_running=True,
        )
    )
    assert d.decision is SupervisorDecisionKind.CONTINUE


def test_state_changed_continue() -> None:
    sup = ExplorationSupervisor()
    d = sup.decide(
        SupervisorContext(
            verify=_verify(VerifyOutcome.STATE_CHANGED, after="settings"),
            executor=_exec(ok=True),
            planned=_planned(),
            has_parent=True,
            app_running=True,
        )
    )
    assert d.decision is SupervisorDecisionKind.CONTINUE


def test_failed_retry() -> None:
    sup = ExplorationSupervisor(max_retries_per_action=1)
    d = sup.decide(
        SupervisorContext(
            verify=_verify(VerifyOutcome.FAILED),
            executor=_exec(ok=False, error="temporary"),
            planned=_planned(),
            has_parent=True,
            app_running=True,
        )
    )
    assert d.decision is SupervisorDecisionKind.RETRY
    assert d.retry_count == 1


def test_retry_exhausted_skip() -> None:
    sup = ExplorationSupervisor(max_retries_per_action=1)
    ctx = SupervisorContext(
        verify=_verify(VerifyOutcome.FAILED),
        executor=_exec(ok=False, error="temporary"),
        planned=_planned(),
        has_parent=True,
        app_running=True,
    )
    assert sup.decide(ctx).decision is SupervisorDecisionKind.RETRY
    d2 = sup.decide(ctx)
    assert d2.decision is SupervisorDecisionKind.SKIP
    assert d2.reason == "retry_exhausted"


def test_rejected_skip() -> None:
    sup = ExplorationSupervisor()
    d = sup.decide(
        SupervisorContext(
            verify=_verify(VerifyOutcome.FAILED),
            executor=_exec(ok=False, rejected=True, error="forbidden_action_kind:shell"),
            planned=_planned(),
            app_running=True,
        )
    )
    assert d.decision is SupervisorDecisionKind.SKIP


def test_wait_on_first_no_change() -> None:
    sup = ExplorationSupervisor()
    d = sup.decide(
        SupervisorContext(
            verify=_verify(VerifyOutcome.NO_CHANGE),
            executor=_exec(ok=True),
            planned=_planned(),
            has_parent=True,
            app_running=True,
        )
    )
    assert d.decision is SupervisorDecisionKind.WAIT


def test_stagnation_backtrack() -> None:
    # Force stagnation without waiting path: max_no_change=1 after wait used
    sup = ExplorationSupervisor(max_consecutive_no_change=1)
    planned = _planned()
    # consume wait
    sup.decide(
        SupervisorContext(
            verify=_verify(VerifyOutcome.NO_CHANGE),
            executor=_exec(ok=True),
            planned=planned,
            has_parent=True,
            app_running=True,
            engine_stagnation_count=0,
        )
    )
    d = sup.decide(
        SupervisorContext(
            verify=_verify(VerifyOutcome.NO_CHANGE),
            executor=_exec(ok=True),
            planned=planned,
            has_parent=True,
            app_running=True,
            engine_stagnation_count=5,
        )
    )
    assert d.decision is SupervisorDecisionKind.BACKTRACK


def test_stagnation_no_parent_stop() -> None:
    sup = ExplorationSupervisor(max_consecutive_no_change=1)
    planned = _planned()
    sup.decide(
        SupervisorContext(
            verify=_verify(VerifyOutcome.NO_CHANGE),
            executor=_exec(ok=True),
            planned=planned,
            has_parent=False,
            app_running=True,
        )
    )
    d = sup.decide(
        SupervisorContext(
            verify=_verify(VerifyOutcome.NO_CHANGE),
            executor=_exec(ok=True),
            planned=planned,
            has_parent=False,
            app_running=True,
            engine_stagnation_count=3,
        )
    )
    assert d.decision is SupervisorDecisionKind.STOP
    assert d.reason == "stagnation_no_parent"


def test_hitl_pause() -> None:
    sup = ExplorationSupervisor()
    d = sup.decide(
        SupervisorContext(
            verify=_verify(VerifyOutcome.BLOCKED, hitl=True),
            executor=_exec(ok=True),
            planned=_planned(),
            app_running=True,
        )
    )
    assert d.decision is SupervisorDecisionKind.PAUSE_HITL


def test_relaunch_when_app_not_running() -> None:
    sup = ExplorationSupervisor(max_relaunches=2)
    d = sup.decide(
        SupervisorContext(
            verify=_verify(VerifyOutcome.SUCCESS),
            executor=_exec(ok=True),
            planned=_planned(),
            app_running=False,
            device_available=True,
        )
    )
    assert d.decision is SupervisorDecisionKind.RELAUNCH


def test_device_unavailable_stop() -> None:
    sup = ExplorationSupervisor()
    d = sup.decide(
        SupervisorContext(
            verify=_verify(VerifyOutcome.FAILED),
            executor=_exec(ok=False),
            planned=_planned(),
            device_available=False,
        )
    )
    assert d.decision is SupervisorDecisionKind.STOP
    assert d.reason == "device_unavailable"


def test_budget_exhausted_stop() -> None:
    agent = AgentState.create_initial(
        package_name="com.example.app", max_actions=3, seed_goals=False
    )
    agent.sync_budgets(actions_used=3)
    sup = ExplorationSupervisor()
    d = sup.decide(
        SupervisorContext(
            agent_state=agent,
            verify=_verify(VerifyOutcome.SUCCESS),
            executor=_exec(ok=True),
            planned=_planned(),
            app_running=True,
        )
    )
    assert d.decision is SupervisorDecisionKind.STOP
    assert d.reason == "budget_actions_exhausted"


def test_recovery_limit_stop() -> None:
    sup = ExplorationSupervisor(max_recovery_without_progress=2, max_retries_per_action=0)
    ctx = SupervisorContext(
        verify=_verify(VerifyOutcome.FAILED),
        executor=_exec(ok=False, error="x"),
        planned=_planned(key="tap:A"),
        has_parent=True,
        app_running=True,
    )
    # SKIP (retry=0) does not count; use WAIT/BACKTRACK path via NO_CHANGE
    planned = _planned(key="tap:B")
    wait_ctx = SupervisorContext(
        verify=_verify(VerifyOutcome.NO_CHANGE),
        executor=_exec(ok=True, key="tap:B"),
        planned=planned,
        has_parent=True,
        app_running=True,
    )
    assert sup.decide(wait_ctx).decision is SupervisorDecisionKind.WAIT
    # second recovery
    planned2 = _planned(key="tap:C")
    wait_ctx2 = SupervisorContext(
        verify=_verify(VerifyOutcome.NO_CHANGE),
        executor=_exec(ok=True, key="tap:C"),
        planned=planned2,
        has_parent=True,
        app_running=True,
    )
    assert sup.decide(wait_ctx2).decision is SupervisorDecisionKind.WAIT
    # third should hit recovery limit
    d = sup.decide(wait_ctx2)
    assert d.decision is SupervisorDecisionKind.STOP
    assert d.reason == "recovery_limit_reached"


def test_decision_always_bounded() -> None:
    sup = ExplorationSupervisor()
    for outcome in VerifyOutcome:
        d = sup.decide(
            SupervisorContext(
                verify=_verify(outcome),
                executor=_exec(ok=outcome != VerifyOutcome.FAILED),
                planned=_planned(),
                has_parent=True,
                app_running=True,
                device_available=True,
            )
        )
        assert isinstance(d.decision, SupervisorDecisionKind)
        json.dumps(d.to_dict())


def test_agent_state_records_recovery() -> None:
    agent = AgentState.create_initial(package_name="com.example.app", seed_goals=False)
    sup = ExplorationSupervisor()
    d = sup.decide(
        SupervisorContext(
            agent_state=agent,
            verify=_verify(VerifyOutcome.FAILED),
            executor=_exec(ok=False, error="boom"),
            planned=_planned(),
            app_running=True,
        )
    )
    assert d.decision is SupervisorDecisionKind.RETRY
    assert len(agent.recovery_history) == 1
    assert agent.recovery_history[0].decision == "RETRY"
    payload = agent.to_dict()
    assert "recovery_history" in payload
    json.dumps(payload)


def test_chain_fail_retry_then_success() -> None:
    agent = AgentState.create_initial(
        package_name="com.example.app", max_actions=50, seed_goals=False
    )
    planner = ExplorationPlanner()
    plan = planner.select([_planned()], agent_state=agent)
    assert plan.planned_action is not None

    ui = MagicMock()
    ui.perform.side_effect = [
        RuntimeError("busy"),
        ActionResult(kind="tap", ok=True, duration_ms=5),
    ]
    executor = ActionExecutor(ui)
    verifier = ActionVerifier()
    supervisor = ExplorationSupervisor(max_retries_per_action=1)

    before = build_observation(
        package_name="com.example.app",
        activity="Home",
        elements=[_el()],
        state_id="home",
        screen_size=(1080, 2400),
    )
    agent.update_observation(before)

    r1 = executor.execute(plan.planned_action, agent_state=agent, before_state_id="home")
    assert r1.success is False
    v1 = verifier.verify(
        planned=plan.planned_action,
        executor_result=r1,
        before=before,
        after=before,
    )
    assert v1.outcome is VerifyOutcome.FAILED
    d1 = supervisor.decide(
        SupervisorContext(
            agent_state=agent,
            verify=v1,
            executor=r1,
            planned=plan.planned_action,
            has_parent=True,
            app_running=True,
        )
    )
    assert d1.decision is SupervisorDecisionKind.RETRY

    r2 = executor.execute(plan.planned_action, agent_state=agent, before_state_id="home")
    assert r2.success is True
    after = build_observation(
        package_name="com.example.app",
        activity="Settings",
        elements=[_el(text="Profile")],
        state_id="settings",
        screen_size=(1080, 2400),
    )
    agent.update_observation(after)
    v2 = verifier.verify(
        planned=plan.planned_action,
        executor_result=r2,
        before=before,
        after=after,
    )
    assert v2.outcome is VerifyOutcome.STATE_CHANGED
    d2 = supervisor.decide(
        SupervisorContext(
            agent_state=agent,
            verify=v2,
            executor=r2,
            planned=plan.planned_action,
            has_parent=True,
            app_running=True,
        )
    )
    assert d2.decision is SupervisorDecisionKind.CONTINUE


def test_chain_stagnation_backtrack_decision() -> None:
    supervisor = ExplorationSupervisor(max_consecutive_no_change=1)
    planned = _planned(key="tap:X")
    # first NO_CHANGE → WAIT
    assert (
        supervisor.decide(
            SupervisorContext(
                verify=_verify(VerifyOutcome.NO_CHANGE),
                executor=_exec(ok=True, key="tap:X"),
                planned=planned,
                has_parent=True,
                app_running=True,
            )
        ).decision
        is SupervisorDecisionKind.WAIT
    )
    # second → BACKTRACK
    d = supervisor.decide(
        SupervisorContext(
            verify=_verify(VerifyOutcome.NO_CHANGE),
            executor=_exec(ok=True, key="tap:X"),
            planned=planned,
            has_parent=True,
            app_running=True,
            engine_stagnation_count=3,
        )
    )
    assert d.decision is SupervisorDecisionKind.BACKTRACK


def test_supervisor_does_not_call_ui() -> None:
    assert not hasattr(ExplorationSupervisor(), "ui")
    assert not hasattr(ExplorationSupervisor(), "perform")
