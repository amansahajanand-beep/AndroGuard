"""Phase 12C — Planner / Executor / Verifier unit + chain tests."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from app.modules.exploration.action_planner import PlannedAction, plan_actions
from app.modules.exploration.actions import (
    ActionResult,
    BackAction,
    SwipeAction,
    TapAction,
    WaitAction,
)
from app.modules.exploration.agent_state import AgentState
from app.modules.exploration.executor import ALLOWED_ACTION_KINDS, ActionExecutor
from app.modules.exploration.observation_builder import build_observation
from app.modules.exploration.planner import ExplorationPlanner
from app.modules.exploration.ui_element import UIElement
from app.modules.exploration.verifier import ActionVerifier, VerifyOutcome


def _el(**kwargs) -> UIElement:
    defaults = dict(
        text="",
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


def _obs(*, state_id: str, activity: str = "Main", text: str = "Home", hitl: bool = False):
    from app.modules.hitl.intervention_types import DetectionResult, InterventionType

    hitl_obj = None
    if hitl:
        hitl_obj = DetectionResult(
            required=True,
            type=InterventionType.LOGIN,
            title="Login",
            confidence=0.9,
        )
    return build_observation(
        package_name="com.example.app",
        activity=activity,
        elements=[_el(text=text)],
        screen_size=(1080, 2400),
        state_id=state_id,
        hitl=hitl_obj,
    )


def _tap_planned(label: str = "Settings", key: str | None = None) -> PlannedAction:
    el = _el(text=label)
    return PlannedAction(
        key=key or f"tap:{label}",
        action=TapAction(element=el),
        kind="tap",
        priority=10,
        label=label,
    )


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


def test_planner_returns_planned_action() -> None:
    planner = ExplorationPlanner()
    agent = AgentState.create_initial(
        package_name="com.example.app", max_actions=50, seed_goals=False
    )
    result = planner.select([_tap_planned()], agent_state=agent)
    assert result.stop is False
    assert result.planned_action is not None
    assert result.planned_action.kind == "tap"
    assert result.candidate_count == 1


def test_planner_no_candidates_stops() -> None:
    planner = ExplorationPlanner()
    result = planner.select([])
    assert result.stop is True
    assert result.planned_action is None
    assert result.stop_reason == "no_candidates"


def test_planner_skips_visited() -> None:
    planner = ExplorationPlanner()
    a = _tap_planned("A", key="tap:A")
    b = _tap_planned("B", key="tap:B")
    result = planner.select([a, b], visited_keys={"tap:A"})
    assert result.planned_action is not None
    assert result.planned_action.key == "tap:B"


def test_planner_skips_repeated_failures() -> None:
    planner = ExplorationPlanner(max_failure_attempts=2)
    agent = AgentState.create_initial(
        package_name="com.example.app", max_actions=50, seed_goals=False
    )
    agent.record_action_failure(action_key="tap:Bad", state_id="s1", reason="x")
    agent.record_action_failure(action_key="tap:Bad", state_id="s1", reason="x")
    bad = _tap_planned("Bad", key="tap:Bad")
    good = _tap_planned("Good", key="tap:Good")
    result = planner.select([bad, good], agent_state=agent)
    assert result.planned_action is not None
    assert result.planned_action.key == "tap:Good"


def test_planner_budget_exhausted_stops() -> None:
    planner = ExplorationPlanner()
    agent = AgentState.create_initial(
        package_name="com.example.app", max_actions=5, seed_goals=False
    )
    agent.sync_budgets(actions_used=5)
    result = planner.select([_tap_planned()], agent_state=agent)
    assert result.stop is True
    assert result.stop_reason == "budget_actions_exhausted"


def test_planner_does_not_execute_ui() -> None:
    planner = ExplorationPlanner()
    # No UIController attribute — selecting must not call perform.
    assert not hasattr(planner, "ui")
    result = planner.select([_tap_planned()])
    assert result.planned_action is not None


def test_planner_reuses_action_planner() -> None:
    planner = ExplorationPlanner()
    elements = [_el(text="Settings"), _el(text="Profile")]
    generated = planner.generate_candidates(elements, screen_size=(1080, 2400))
    direct = plan_actions(elements, screen_size=(1080, 2400))
    assert isinstance(generated, list)
    assert len(generated) == len(direct)
    assert all(isinstance(x, PlannedAction) for x in generated)


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


def test_executor_tap_via_ui_controller() -> None:
    ui = MagicMock()
    ui.perform.return_value = ActionResult(kind="tap", ok=True, duration_ms=12)
    executor = ActionExecutor(ui)
    agent = AgentState.create_initial(package_name="com.example.app", seed_goals=False)
    planned = _tap_planned()
    result = executor.execute(planned, agent_state=agent, before_state_id="home")
    assert result.success is True
    assert result.rejected is False
    ui.perform.assert_called_once_with(planned.action)
    assert len(agent.history) == 1
    assert agent.history[0].success is True


def test_executor_swipe() -> None:
    ui = MagicMock()
    ui.perform.return_value = ActionResult(kind="swipe", ok=True)
    executor = ActionExecutor(ui)
    planned = PlannedAction(
        key="swipe:up",
        action=SwipeAction(direction="up"),
        kind="swipe",
        label="swipe up",
    )
    result = executor.execute(planned)
    assert result.success is True
    ui.perform.assert_called_once()


def test_executor_back() -> None:
    ui = MagicMock()
    ui.perform.return_value = ActionResult(kind="back", ok=True)
    executor = ActionExecutor(ui)
    planned = PlannedAction(key="back", action=BackAction(), kind="back", label="back")
    assert executor.execute(planned).success is True


def test_executor_rejects_unknown_kind() -> None:
    ui = MagicMock()
    executor = ActionExecutor(ui)
    planned = PlannedAction(
        key="evil",
        action=BackAction(),
        kind="shell",
        label="shell",
    )
    result = executor.execute(planned)
    assert result.success is False
    assert result.rejected is True
    ui.perform.assert_not_called()


def test_executor_rejects_adb_like_kind() -> None:
    ui = MagicMock()
    executor = ActionExecutor(ui)
    planned = PlannedAction(
        key="adb",
        action=BackAction(),
        kind="adb_shell",
        label="adb",
    )
    result = executor.execute(planned)
    assert result.rejected is True
    ui.perform.assert_not_called()


def test_executor_ui_failure() -> None:
    ui = MagicMock()
    ui.perform.side_effect = RuntimeError("device offline")
    executor = ActionExecutor(ui)
    agent = AgentState.create_initial(package_name="com.example.app", seed_goals=False)
    result = executor.execute(_tap_planned(), agent_state=agent, before_state_id="s1")
    assert result.success is False
    assert result.error_type == "RuntimeError"
    assert len(agent.failed_actions) == 1


def test_executor_does_not_plan() -> None:
    executor = ActionExecutor(MagicMock())
    assert not hasattr(executor, "select")
    assert not hasattr(executor, "plan")


def test_allowed_kinds_are_ui_only() -> None:
    assert "tap" in ALLOWED_ACTION_KINDS
    assert "shell" not in ALLOWED_ACTION_KINDS
    assert "adb" not in ALLOWED_ACTION_KINDS


# ---------------------------------------------------------------------------
# Verifier
# ---------------------------------------------------------------------------


def test_verifier_state_changed() -> None:
    verifier = ActionVerifier()
    before = _obs(state_id="home")
    after = _obs(state_id="settings", activity="Settings", text="Profile")
    ui = MagicMock()
    ui.perform.return_value = ActionResult(kind="tap", ok=True)
    exec_result = ActionExecutor(ui).execute(_tap_planned())
    result = verifier.verify(
        planned=_tap_planned(),
        executor_result=exec_result,
        before=before,
        after=after,
    )
    assert result.outcome == VerifyOutcome.STATE_CHANGED
    assert result.ok is True


def test_verifier_activity_changed() -> None:
    verifier = ActionVerifier()
    before = _obs(state_id="same", activity="A")
    after = _obs(state_id="same", activity="B", text="Other")
    result = verifier.verify(
        planned=_tap_planned(),
        executor_result=None,
        before=before,
        after=after,
    )
    assert result.outcome == VerifyOutcome.STATE_CHANGED
    assert result.activity_changed is True


def test_verifier_ui_change_same_state_not_failure() -> None:
    verifier = ActionVerifier()
    before = _obs(state_id="s1", text="A")
    after = _obs(state_id="s1", text="B")
    result = verifier.verify(
        planned=_tap_planned(),
        executor_result=None,
        before=before,
        after=after,
    )
    assert result.outcome == VerifyOutcome.SUCCESS
    assert result.ui_changed is True


def test_verifier_no_change() -> None:
    verifier = ActionVerifier()
    before = _obs(state_id="s1", text="Same")
    after = _obs(state_id="s1", text="Same")
    result = verifier.verify(
        planned=_tap_planned(),
        executor_result=None,
        before=before,
        after=after,
    )
    assert result.outcome == VerifyOutcome.NO_CHANGE


def test_verifier_hitl_blocked() -> None:
    verifier = ActionVerifier()
    before = _obs(state_id="s1")
    after = _obs(state_id="s2", hitl=True)
    result = verifier.verify(
        planned=_tap_planned(),
        executor_result=None,
        before=before,
        after=after,
    )
    assert result.outcome == VerifyOutcome.BLOCKED
    assert result.hitl_appeared is True


def test_verifier_wait_same_state_success() -> None:
    verifier = ActionVerifier()
    before = _obs(state_id="s1")
    after = _obs(state_id="s1")
    planned = PlannedAction(
        key="wait",
        action=WaitAction(seconds=0.5),
        kind="wait",
        label="wait",
    )
    result = verifier.verify(
        planned=planned,
        executor_result=None,
        before=before,
        after=after,
    )
    assert result.outcome == VerifyOutcome.SUCCESS


def test_verifier_failed_executor() -> None:
    verifier = ActionVerifier()
    ui = MagicMock()
    ui.perform.side_effect = RuntimeError("boom")
    exec_result = ActionExecutor(ui).execute(_tap_planned())
    result = verifier.verify(
        planned=_tap_planned(),
        executor_result=exec_result,
        before=_obs(state_id="a"),
        after=_obs(state_id="a"),
    )
    assert result.outcome == VerifyOutcome.FAILED


def test_verifier_to_dict_json() -> None:
    verifier = ActionVerifier()
    result = verifier.verify(
        planned=_tap_planned(),
        executor_result=None,
        before=_obs(state_id="a"),
        after=_obs(state_id="b"),
    )
    json.dumps(result.to_dict())


# ---------------------------------------------------------------------------
# Integration chain
# ---------------------------------------------------------------------------


def test_full_chain_observation_to_agent_state() -> None:
    agent = AgentState.create_initial(
        package_name="com.example.app",
        max_actions=100,
        max_states=25,
        seed_goals=False,
    )
    before = _obs(state_id="home", activity="Home")
    agent.update_observation(before)

    planner = ExplorationPlanner()
    plan = planner.select([_tap_planned("Settings")], agent_state=agent)
    assert plan.planned_action is not None

    ui = MagicMock()
    ui.perform.return_value = ActionResult(kind="tap", ok=True, duration_ms=5)
    executor = ActionExecutor(ui)
    exec_result = executor.execute(
        plan.planned_action,
        agent_state=agent,
        before_state_id="home",
    )
    assert exec_result.success is True

    after = _obs(state_id="settings", activity="Settings", text="Profile")
    agent.update_observation(after)

    verify = ActionVerifier().verify(
        planned=plan.planned_action,
        executor_result=exec_result,
        before=before,
        after=after,
    )
    assert verify.outcome == VerifyOutcome.STATE_CHANGED
    assert agent.current_state_id == "settings"
    assert any(h.action_kind == "tap" for h in agent.history)
    payload = agent.to_dict()
    json.dumps(payload)
    json.dumps(plan.to_dict())
    json.dumps(exec_result.to_dict())
    json.dumps(verify.to_dict())
