"""Phase 12E — Goal-aware AI planner context, confidence, fallback tests."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.modules.ai_explorer.advisor import ExplorationAdvisor
from app.modules.ai_explorer.context import AIPlanningContext, build_planning_context
from app.modules.ai_explorer.graph import run_decision_pipeline
from app.modules.ai_explorer.prompts import SYSTEM_PROMPT, build_user_prompt
from app.modules.ai_explorer.schema import AIActionDecision
from app.modules.ai_explorer.validator import (
    ActionValidationError,
    parse_ai_decision,
    validate_and_map,
)
from app.modules.exploration.action_planner import PlannedAction
from app.modules.exploration.actions import ActionResult, TapAction
from app.modules.exploration.agent_state import AgentState
from app.modules.exploration.executor import ActionExecutor
from app.modules.exploration.observation_builder import build_observation
from app.modules.exploration.planner import ExplorationPlanner
from app.modules.exploration.supervisor import (
    ExplorationSupervisor,
    SupervisorContext,
    SupervisorDecisionKind,
)
from app.modules.exploration.ui_element import UIElement
from app.modules.exploration.verifier import ActionVerifier, VerifyOutcome


def _el(text: str = "Settings") -> UIElement:
    return UIElement(
        text=text,
        resource_id="btn",
        content_description="",
        class_name="android.widget.Button",
        package="com.example.app",
        bounds=(0, 0, 100, 80),
        clickable=True,
        enabled=True,
        scrollable=False,
        visible=True,
        selected=False,
        checked=False,
        focused=False,
        focusable=True,
    )


def _tap(key: str, *, label: str = "Settings", priority: int = 50) -> PlannedAction:
    return PlannedAction(
        key=key,
        action=TapAction(element=_el(label)),
        kind="tap",
        priority=priority,
        label=label,
    )


def test_planning_context_includes_goal_history_budget() -> None:
    agent = AgentState.create_initial(
        package_name="com.example.app",
        max_actions=100,
        seed_goals=True,
    )
    agent.sync_budgets(actions_used=10, states_discovered=3, current_depth=2)
    agent.record_action_success(
        action_kind="tap", action_key="tap:Home", state_id="s0", next_state_id="s1"
    )
    agent.record_action_failure(action_key="tap:Broken", state_id="s1", reason="failed")
    obs = build_observation(
        package_name="com.example.app",
        activity="Main",
        elements=[_el("Profile")],
        state_id="s1",
        screen_size=(1080, 2400),
    )
    agent.update_observation(obs)
    ctx = build_planning_context(agent_state=agent, observation=obs)
    payload = ctx.to_dict()
    assert payload["goal"]["goal_id"]
    assert payload["budget"]["remaining_actions"] == 90
    assert len(payload["recent_history"]) >= 1
    assert len(payload["failed_actions"]) >= 1
    assert payload["current_state_id"] == "s1"
    json.dumps(payload)


def test_prompt_includes_goal_and_candidates() -> None:
    ctx = AIPlanningContext(
        package_name="com.example.app",
        current_activity="Main",
        goal={
            "goal_id": "explore_application",
            "goal_type": "GENERAL_EXPLORATION",
            "description": "Explore screens",
            "status": "ACTIVE",
            "priority": 1,
        },
        budget={"remaining_actions": 50},
        navigation_summary={"visited_states": 4, "current_state": "s1"},
        recent_history=[{"action": "tap", "label": "Home", "success": True}],
        failed_actions=[{"action_key": "tap:x", "attempt_count": 2, "reason": "fail"}],
    )
    prompt = build_user_prompt(
        activity="Main",
        package_name="com.example.app",
        candidates=[{"key": "tap:A", "action": "tap", "label": "A"}],
        visited_summary=["tap:old"],
        planning_context=ctx.to_dict(),
    )
    assert "CURRENT_GOAL" in prompt
    assert "GENERAL_EXPLORATION" in prompt
    assert "RECENT_HISTORY" in prompt
    assert "FAILED_ACTIONS" in prompt
    assert "tap:A" in prompt
    assert "cannot execute" in SYSTEM_PROMPT.lower() or "cannot execute actions" in SYSTEM_PROMPT


def test_ai_chooses_valid_candidate() -> None:
    cands = [_tap("tap:A", label="A"), _tap("tap:B", label="B"), _tap("tap:C", label="C")]
    advisor = ExplorationAdvisor(enabled=True, min_confidence=0.5)
    with patch("app.modules.ai_explorer.advisor.should_invoke_ai", return_value=(True, "forced")):
        with patch(
            "app.modules.ai_explorer.advisor.chat_json",
            return_value={
                "action": "tap",
                "target": "tap:B",
                "confidence": 0.9,
                "reason": "Unexplored Profile path",
            },
        ):
            planned, meta = advisor.choose(cands, force=True)
    assert planned is not None
    assert planned.key == "tap:B"
    assert meta["ai_used"] is True
    assert meta["planner_source"] == "AI"


def test_ai_invalid_candidate_fallback() -> None:
    cands = [_tap("tap:A", label="A")]
    advisor = ExplorationAdvisor(enabled=True, min_confidence=0.5)
    with patch("app.modules.ai_explorer.advisor.should_invoke_ai", return_value=(True, "forced")):
        with patch(
            "app.modules.ai_explorer.advisor.chat_json",
            return_value={
                "action": "tap",
                "target": "tap:UNKNOWN",
                "confidence": 0.95,
                "reason": "bad",
            },
        ):
            planned, meta = advisor.choose(cands, force=True)
    assert planned is None
    assert meta["planner_source"] == "DETERMINISTIC_FALLBACK"


def test_ai_malformed_json_fallback() -> None:
    cands = [_tap("tap:A")]
    advisor = ExplorationAdvisor(enabled=True)
    with patch("app.modules.ai_explorer.advisor.should_invoke_ai", return_value=(True, "forced")):
        with patch(
            "app.modules.ai_explorer.advisor.chat_json",
            return_value="not-json{{{",
        ):
            planned, meta = advisor.choose(cands, force=True)
    assert planned is None
    assert "fallback" in meta


def test_llm_timeout_fallback() -> None:
    from app.modules.ai_explorer.llm import AIAdvisorError

    cands = [_tap("tap:A")]
    advisor = ExplorationAdvisor(enabled=True)
    with patch("app.modules.ai_explorer.advisor.should_invoke_ai", return_value=(True, "forced")):
        with patch(
            "app.modules.ai_explorer.advisor.chat_json",
            side_effect=AIAdvisorError("timeout"),
        ):
            planned, meta = advisor.choose(cands, force=True)
    assert planned is None
    assert meta["planner_source"] == "DETERMINISTIC_FALLBACK"


def test_ai_disabled_deterministic() -> None:
    cands = [_tap("tap:A"), _tap("tap:B")]
    advisor = ExplorationAdvisor(enabled=False)
    planned, meta = advisor.choose(cands, force=True)
    assert planned is None
    assert meta["ai_used"] is False


def test_low_confidence_fallback() -> None:
    cands = [_tap("tap:A"), _tap("tap:B")]
    advisor = ExplorationAdvisor(enabled=True, min_confidence=0.70)
    with patch("app.modules.ai_explorer.advisor.should_invoke_ai", return_value=(True, "forced")):
        with patch(
            "app.modules.ai_explorer.advisor.chat_json",
            return_value={
                "action": "tap",
                "target": "tap:B",
                "confidence": 0.2,
                "reason": "unsure",
            },
        ):
            planned, meta = advisor.choose(cands, force=True)
    assert planned is None
    assert meta["planner_source"] == "DETERMINISTIC_FALLBACK"


def test_confidence_optional_still_accepted() -> None:
    decision = parse_ai_decision(
        {"action": "tap", "target": "tap:A", "reason": "ok"}
    )
    assert decision.confidence is None
    cands = [_tap("tap:A")]
    planned = validate_and_map(
        {"action": "tap", "target": "tap:A", "confidence": 0.88, "reason": "good"},
        cands,
    )
    assert planned.meta.get("confidence") == 0.88
    assert planned.meta.get("planner_source") == "AI"


def test_pipeline_ai_failure_falls_back() -> None:
    cands = [_tap("tap:A", priority=90), _tap("tap:B", priority=10)]
    with patch("app.core.config.settings.ai_explorer_enabled", True):
        with patch(
            "app.modules.ai_explorer.graph.ExplorationAdvisor.choose",
            return_value=(None, {"ai_used": False, "fallback": "x", "planner_source": "DETERMINISTIC_FALLBACK"}),
        ):
            selected, meta = run_decision_pipeline(
                cands,
                force_ai=True,
                planning_context=build_planning_context(
                    agent_state=AgentState.create_initial(
                        package_name="com.example.app", seed_goals=True
                    )
                ),
            )
    assert selected is not None
    assert selected.key == "tap:A"
    assert meta.get("planner_source") == "DETERMINISTIC_FALLBACK"


def test_pipeline_disabled_uses_deterministic() -> None:
    cands = [_tap("tap:Z", priority=1), _tap("tap:Y", priority=99)]
    # candidates already ordered by planner; pipeline picks first unexplored
    with patch("app.core.config.settings.ai_explorer_enabled", False):
        selected, meta = run_decision_pipeline(cands, force_ai=False)
    assert selected is not None
    assert selected.key == "tap:Z"
    assert meta.get("ai_used") is False


def test_ai_cannot_invent_adb_action() -> None:
    with pytest.raises(ActionValidationError):
        parse_ai_decision({"action": "adb_shell", "target": None, "reason": "x"})


def test_agent_state_records_ai_meta() -> None:
    agent = AgentState.create_initial(package_name="com.example.app", seed_goals=False)
    agent.record_ai_decision(
        used=True,
        meta={"ai_key": "tap:A", "ai_reason": "good", "ai_confidence": 0.9, "policy": "forced"},
        planner_source="AI",
    )
    assert agent.ai_decision_count == 1
    assert agent.last_planner_source == "AI"
    agent.record_ai_decision(
        used=False,
        meta={"fallback": "deterministic_after_ai_failure"},
        planner_source="DETERMINISTIC_FALLBACK",
    )
    assert agent.ai_fallback_count == 1
    json.dumps(agent.to_dict())


def test_integration_ai_to_supervisor_chain() -> None:
    agent = AgentState.create_initial(
        package_name="com.example.app", max_actions=50, seed_goals=True
    )
    obs = build_observation(
        package_name="com.example.app",
        activity="Home",
        elements=[_el("Settings")],
        state_id="home",
        screen_size=(1080, 2400),
    )
    agent.update_observation(obs)
    cands = [_tap("tap:Settings", label="Settings"), _tap("tap:Profile", label="Profile")]

    ctx = build_planning_context(agent_state=agent, observation=obs)
    advisor = ExplorationAdvisor(enabled=True, min_confidence=0.5)
    with patch("app.modules.ai_explorer.advisor.should_invoke_ai", return_value=(True, "forced")):
        with patch(
            "app.modules.ai_explorer.advisor.chat_json",
            return_value={
                "action": "tap",
                "target": "tap:Settings",
                "confidence": 0.91,
                "reason": "Likely unexplored settings screen",
            },
        ):
            planned, meta = advisor.choose(
                cands, force=True, planning_context=ctx
            )
    assert planned is not None
    assert meta["ai_used"] is True
    agent.record_ai_decision(used=True, meta=meta)

    ui = MagicMock()
    ui.perform.return_value = ActionResult(kind="tap", ok=True)
    exec_result = ActionExecutor(ui).execute(
        planned, agent_state=agent, before_state_id="home"
    )
    after = build_observation(
        package_name="com.example.app",
        activity="Settings",
        elements=[_el("Account")],
        state_id="settings",
        screen_size=(1080, 2400),
    )
    agent.update_observation(after)
    verify = ActionVerifier().verify(
        planned=planned,
        executor_result=exec_result,
        before=obs,
        after=after,
    )
    assert verify.outcome is VerifyOutcome.STATE_CHANGED
    decision = ExplorationSupervisor().decide(
        SupervisorContext(
            agent_state=agent,
            verify=verify,
            executor=exec_result,
            planned=planned,
            has_parent=True,
            app_running=True,
        )
    )
    assert decision.decision is SupervisorDecisionKind.CONTINUE


def test_integration_ai_failure_deterministic_executor() -> None:
    agent = AgentState.create_initial(package_name="com.example.app", seed_goals=False)
    cands = [_tap("tap:A", priority=80), _tap("tap:B", priority=10)]
    planner = ExplorationPlanner()
    advisor = ExplorationAdvisor(enabled=True)
    with patch("app.modules.ai_explorer.advisor.should_invoke_ai", return_value=(True, "forced")):
        with patch(
            "app.modules.ai_explorer.advisor.chat_json",
            side_effect=RuntimeError("provider down"),
        ):
            ai_planned, meta = advisor.choose(cands, force=True)
    assert ai_planned is None
    plan = planner.select(cands, agent_state=agent)
    assert plan.planned_action is not None
    ui = MagicMock()
    ui.perform.return_value = ActionResult(kind="tap", ok=True)
    result = ActionExecutor(ui).execute(plan.planned_action, agent_state=agent)
    assert result.success is True
    assert meta.get("planner_source") == "DETERMINISTIC_FALLBACK"
