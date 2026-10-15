"""Phase 12H — Exploration reliability & resilience tests."""

from __future__ import annotations

import json
import random
from unittest.mock import MagicMock, patch

from app.modules.ai_explorer.advisor import ExplorationAdvisor
from app.modules.ai_explorer.context import build_planning_context
from app.modules.ai_explorer.validator import map_decision_to_planned, parse_ai_decision
from app.modules.apk_intelligence import ApplicationIntelligence
from app.modules.exploration.action_planner import PlannedAction
from app.modules.exploration.actions import ActionResult, BackAction, TapAction, WaitAction
from app.modules.exploration.ad_goals import (
    AdGoalGenerator,
    GoalEvaluator,
    apply_goal_evaluation,
    seed_ad_goals_from_intelligence,
)
from app.modules.exploration.agent_state import AgentState
from app.modules.exploration.executor import ALLOWED_ACTION_KINDS, ActionExecutor, ExecutorResult
from app.modules.exploration.navigation_graph import NavigationGraph, NavEdge
from app.modules.exploration.observation_builder import build_observation
from app.modules.exploration.supervisor import (
    ExplorationSupervisor,
    SupervisorContext,
    SupervisorDecisionKind,
)
from app.modules.exploration.ui_element import UIElement
from app.modules.exploration.verifier import ActionVerifier, VerifyOutcome
from tests.unit.reliability_fakes import (
    DelayedObservationProvider,
    ExplorationSimulator,
    FailingAIProvider,
    FailingUIController,
    SimulatedScreen,
    make_element,
    mock_ui_success,
)


def _planned(key: str = "tap:A", kind: str = "tap", label: str = "A") -> PlannedAction:
    if kind == "wait":
        action = WaitAction(seconds=0.1)
    elif kind == "back":
        action = BackAction()
    else:
        action = TapAction(element=make_element(label))
    return PlannedAction(key=key, action=action, kind=kind, priority=10, label=label)


def _exec(
    *,
    ok: bool = True,
    rejected: bool = False,
    error: str | None = None,
    key: str = "tap:A",
) -> ExecutorResult:
    return ExecutorResult(
        action_id="id1",
        action_kind="tap",
        action_key=key,
        success=ok and not rejected,
        started_at="t0",
        completed_at="t1",
        duration_ms=5,
        error=error,
        error_type="rejected" if rejected else ("ui_failure" if not ok else None),
        before_state_id="s0",
        rejected=rejected,
    )


# ---------------------------------------------------------------------------
# 12H-1 Observation reliability
# ---------------------------------------------------------------------------


def test_normal_observation_complete() -> None:
    obs = build_observation(
        package_name="com.example.app",
        activity="MainActivity",
        elements=[make_element("Play")],
        screen_size=(1080, 2400),
        state_id="s0",
        screenshot_path="/tmp/shot.png",
    )
    assert obs.package_name == "com.example.app"
    assert obs.activity == "MainActivity"
    assert obs.screenshot_path
    assert obs.clickable_elements
    json.dumps(obs.to_dict())


def test_partial_observation_no_crash() -> None:
    obs = build_observation(
        package_name=None,
        activity=None,
        elements=None,
        screen_size=None,
        state_id=None,
        screenshot_path=None,
        ad_results=None,
        hitl=None,
    )
    assert obs.ui_elements == []
    assert obs.detected_ads == []
    assert obs.hitl_required is False
    payload = obs.to_dict()
    assert "observation_id" in payload


def test_stale_observation_not_instant_failure() -> None:
    before = build_observation(
        package_name="com.example.app",
        activity="Home",
        elements=[make_element("Play")],
        state_id="s0",
    )
    after = build_observation(
        package_name="com.example.app",
        activity="Home",
        elements=[make_element("Play")],
        state_id="s0",
    )
    result = ActionVerifier().verify(
        planned=_planned(kind="tap"),
        executor_result=_exec(ok=True),
        before=before,
        after=after,
    )
    assert result.outcome is VerifyOutcome.NO_CHANGE
    # Supervisor should WAIT once, not STOP immediately.
    agent = AgentState.create_initial(
        package_name="com.example.app", seed_goals=False, max_actions=50
    )
    agent.sync_budgets(actions_used=1, states_discovered=1, current_depth=1)
    sup = ExplorationSupervisor()
    d = sup.decide(
        SupervisorContext(
            agent_state=agent,
            verify=result,
            executor=_exec(ok=True),
            planned=_planned(),
            has_parent=True,
            app_running=True,
        )
    )
    assert d.decision is SupervisorDecisionKind.WAIT


# ---------------------------------------------------------------------------
# 12H-2 Action reliability
# ---------------------------------------------------------------------------


def test_action_success_via_executor() -> None:
    ui = FailingUIController()
    agent = AgentState.create_initial(package_name="com.example.app", seed_goals=False)
    result = ActionExecutor(ui).execute(_planned(), agent_state=agent)
    assert result.success is True
    assert result.rejected is False
    assert ui.calls


def test_action_failure_recorded() -> None:
    ui = FailingUIController(fail_kinds={"tap"})
    agent = AgentState.create_initial(package_name="com.example.app", seed_goals=False)
    result = ActionExecutor(ui).execute(_planned(), agent_state=agent)
    assert result.success is False
    agent.record_action(
        action_kind="tap",
        action_key=result.action_key,
        success=False,
        failure_reason=result.error,
    )
    assert agent.failed_actions
    assert agent.reliability["actions_failed"] >= 1


def test_rejected_action_no_ui_execution() -> None:
    ui = FailingUIController()
    planned = PlannedAction(
        key="shell:x",
        action=TapAction(element=make_element("X")),
        kind="shell",
        priority=10,
        label="shell",
    )
    result = ActionExecutor(ui).execute(planned)
    assert result.rejected is True
    assert result.success is False
    assert ui.calls == []


def test_retry_bounded_then_skip() -> None:
    agent = AgentState.create_initial(package_name="com.example.app", seed_goals=False)
    agent.sync_budgets(actions_used=1, states_discovered=1, current_depth=1)
    sup = ExplorationSupervisor(max_retries_per_action=1)
    planned = _planned(key="tap:Flaky")
    failed = ActionVerifier().verify(
        planned=planned,
        executor_result=_exec(ok=False, error="tap_miss", key="tap:Flaky"),
        before=None,
        after=None,
    )
    d1 = sup.decide(
        SupervisorContext(
            agent_state=agent,
            verify=failed,
            executor=_exec(ok=False, error="tap_miss", key="tap:Flaky"),
            planned=planned,
            has_parent=True,
            app_running=True,
        )
    )
    assert d1.decision is SupervisorDecisionKind.RETRY
    d2 = sup.decide(
        SupervisorContext(
            agent_state=agent,
            verify=failed,
            executor=_exec(ok=False, error="tap_miss", key="tap:Flaky"),
            planned=planned,
            has_parent=True,
            app_running=True,
        )
    )
    assert d2.decision is SupervisorDecisionKind.SKIP
    assert d2.reason == "retry_exhausted"
    assert agent.reliability["retries"] >= 1


# ---------------------------------------------------------------------------
# 12H-3 Verifier outcomes
# ---------------------------------------------------------------------------


def test_verifier_state_changed() -> None:
    before = build_observation(state_id="s0", activity="A", elements=[make_element("X")])
    after = build_observation(state_id="s1", activity="B", elements=[make_element("Y")])
    r = ActionVerifier().verify(
        planned=_planned(), executor_result=_exec(ok=True), before=before, after=after
    )
    assert r.outcome is VerifyOutcome.STATE_CHANGED


def test_verifier_wait_success_without_change() -> None:
    before = build_observation(state_id="s0", activity="A", elements=[make_element("X")])
    after = build_observation(state_id="s0", activity="A", elements=[make_element("X")])
    r = ActionVerifier().verify(
        planned=_planned(kind="wait", key="wait:1"),
        executor_result=_exec(ok=True, key="wait:1"),
        before=before,
        after=after,
    )
    assert r.outcome is VerifyOutcome.SUCCESS


def test_verifier_executor_failure() -> None:
    r = ActionVerifier().verify(
        planned=_planned(),
        executor_result=_exec(ok=False, error="boom"),
        before=None,
        after=None,
    )
    assert r.outcome is VerifyOutcome.FAILED


def test_verifier_blocked_hitl() -> None:
    after = build_observation(
        state_id="s0",
        hitl={"required": True, "type": "LOGIN", "message": "Sign in"},
    )
    r = ActionVerifier().verify(
        planned=_planned(), executor_result=_exec(ok=True), before=None, after=after
    )
    assert r.outcome is VerifyOutcome.BLOCKED


def test_verifier_unknown_missing_after() -> None:
    r = ActionVerifier().verify(
        planned=_planned(), executor_result=_exec(ok=True), before=None, after=None
    )
    assert r.outcome is VerifyOutcome.UNKNOWN


def test_verifier_delayed_ads_appeared() -> None:
    before = build_observation(
        state_id="s0",
        activity="Home",
        elements=[make_element("Play")],
        ad_results=[],
    )
    after = build_observation(
        state_id="s0",
        activity="Home",
        elements=[make_element("Play")],
        ad_results=[
            {"detected": True, "type": "banner", "confidence": 0.8, "position": "bottom"}
        ],
    )
    r = ActionVerifier().verify(
        planned=_planned(kind="wait", key="wait:ad"),
        executor_result=_exec(ok=True, key="wait:ad"),
        before=before,
        after=after,
    )
    r2 = ActionVerifier().verify(
        planned=_planned(kind="tap"),
        executor_result=_exec(ok=True),
        before=before,
        after=after,
    )
    assert r.outcome is VerifyOutcome.SUCCESS
    assert r2.outcome is VerifyOutcome.SUCCESS
    assert r2.reason == "runtime_ads_appeared"


# ---------------------------------------------------------------------------
# 12H-4 Supervisor / recovery
# ---------------------------------------------------------------------------


def test_stagnation_backtrack_then_stop_without_parent() -> None:
    agent = AgentState.create_initial(
        package_name="com.example.app", seed_goals=False, max_actions=50
    )
    agent.sync_budgets(actions_used=1, states_discovered=1, current_depth=1)
    no_change = ActionVerifier().verify(
        planned=_planned(),
        executor_result=_exec(ok=True),
        before=build_observation(state_id="s0", activity="A", elements=[make_element("X")]),
        after=build_observation(state_id="s0", activity="A", elements=[make_element("X")]),
    )
    assert no_change.outcome is VerifyOutcome.NO_CHANGE
    sup = ExplorationSupervisor(max_consecutive_no_change=2)
    d1 = sup.decide(
        SupervisorContext(
            agent_state=agent,
            verify=no_change,
            executor=_exec(ok=True),
            planned=_planned(),
            has_parent=True,
            app_running=True,
            engine_stagnation_count=0,
        )
    )
    assert d1.decision is SupervisorDecisionKind.WAIT
    d2 = sup.decide(
        SupervisorContext(
            agent_state=agent,
            verify=no_change,
            executor=_exec(ok=True),
            planned=_planned(),
            has_parent=True,
            app_running=True,
            engine_stagnation_count=2,
        )
    )
    assert d2.decision is SupervisorDecisionKind.BACKTRACK

    # No parent → STOP
    sup2 = ExplorationSupervisor(max_consecutive_no_change=1)
    planned2 = _planned(key="tap:B")
    # First consumes WAIT
    d_wait = sup2.decide(
        SupervisorContext(
            agent_state=agent,
            verify=no_change,
            executor=_exec(ok=True, key="tap:B"),
            planned=planned2,
            has_parent=False,
            app_running=True,
        )
    )
    assert d_wait.decision is SupervisorDecisionKind.WAIT
    d_stop = sup2.decide(
        SupervisorContext(
            agent_state=agent,
            verify=no_change,
            executor=_exec(ok=True, key="tap:B"),
            planned=planned2,
            has_parent=False,
            app_running=True,
            engine_stagnation_count=5,
        )
    )
    assert d_stop.decision is SupervisorDecisionKind.STOP
    assert "stagnation" in d_stop.reason


def test_crash_relaunch_then_stop_on_loop() -> None:
    agent = AgentState.create_initial(
        package_name="com.example.app", seed_goals=False, max_actions=50
    )
    agent.sync_budgets(actions_used=1, states_discovered=1, current_depth=0)
    sup = ExplorationSupervisor(max_relaunches=2)
    for _ in range(2):
        d = sup.decide(
            SupervisorContext(
                agent_state=agent,
                verify=None,
                executor=_exec(ok=False, error="app_dead"),
                planned=_planned(),
                has_parent=False,
                app_running=False,
            )
        )
        assert d.decision is SupervisorDecisionKind.RELAUNCH
    d_stop = sup.decide(
        SupervisorContext(
            agent_state=agent,
            verify=None,
            executor=_exec(ok=False, error="app_dead"),
            planned=_planned(),
            has_parent=False,
            app_running=False,
        )
    )
    assert d_stop.decision is SupervisorDecisionKind.STOP
    assert d_stop.reason == "relaunch_limit_reached"
    assert agent.reliability["relaunches"] >= 2


def test_recovery_budget_stops_oscillation() -> None:
    agent = AgentState.create_initial(
        package_name="com.example.app", seed_goals=False, max_actions=100
    )
    agent.sync_budgets(actions_used=1, states_discovered=1, current_depth=1)
    sup = ExplorationSupervisor(
        max_recovery_without_progress=2,
        max_consecutive_no_change=99,
    )
    before = build_observation(state_id="s0", activity="A", elements=[make_element("X")])
    after = build_observation(state_id="s0", activity="A", elements=[make_element("X")])
    no_change = ActionVerifier().verify(
        planned=_planned(), executor_result=_exec(ok=True), before=before, after=after
    )
    decisions = []
    last = None
    for key in ("tap:A", "tap:B", "tap:C"):
        last = sup.decide(
            SupervisorContext(
                agent_state=agent,
                verify=no_change,
                executor=_exec(ok=True, key=key),
                planned=_planned(key=key),
                has_parent=True,
                app_running=True,
            )
        )
        decisions.append(last.decision)
    assert last is not None
    assert last.decision is SupervisorDecisionKind.STOP
    assert last.reason == "recovery_limit_reached"
    assert SupervisorDecisionKind.STOP in decisions


# ---------------------------------------------------------------------------
# 12H-5 Navigation
# ---------------------------------------------------------------------------


def test_navigation_graph_consistency_and_revisit() -> None:
    graph = NavigationGraph()
    graph.visited_states["home"] = MagicMock()
    graph.visited_states["details"] = MagicMock()
    graph.current_state_id = "home"
    graph.edges.append(
        NavEdge(
            from_state_id="home",
            to_state_id="details",
            action_kind="tap",
            action_key="tap:Details",
            succeeded=True,
        )
    )
    graph.edges.append(
        NavEdge(
            from_state_id="details",
            to_state_id="home",
            action_kind="back",
            action_key="back",
            succeeded=True,
        )
    )
    graph.edges.append(
        NavEdge(
            from_state_id="home",
            to_state_id="details",
            action_kind="tap",
            action_key="tap:Details2",
            succeeded=True,
        )
    )
    assert len(graph.visited_states) == 2
    assert len(graph.edges) == 3
    agent = AgentState.create_initial(
        package_name="com.example.app",
        seed_goals=False,
        navigation_graph=graph,
    )
    agent.current_state_id = "details"
    summary = agent.navigation_summary()
    assert summary["state_count"] == 2
    assert summary["edge_count"] == 3


# ---------------------------------------------------------------------------
# 12H-6 / 12H-7 Ad discovery reliability
# ---------------------------------------------------------------------------


def test_static_only_never_found() -> None:
    intel = ApplicationIntelligence(
        status="ready",
        ads={
            "ad_formats": [
                {"format": "REWARDED", "confidence": 0.95, "kind": "LIKELY_FORMAT"}
            ],
            "sdk_candidates": [{"name": "Google Mobile Ads"}],
        },
    )
    agent = AgentState.create_initial(
        package_name="com.example.app",
        seed_goals=False,
        application_intelligence=intel,
    )
    seed_ad_goals_from_intelligence(agent, intel)
    goal = next(g for g in agent.active_goals if g.target_ad_type == "REWARDED")
    obs = build_observation(state_id="s0", activity="Home", ad_results=[])
    ev = GoalEvaluator().evaluate(goal, observation=obs, agent_state=agent)
    assert ev.outcome != "GOAL_FOUND"
    assert goal.status == "active"


def test_runtime_banner_found_any_goal() -> None:
    agent = AgentState.create_initial(package_name="com.example.app", seed_goals=False)
    goal = agent.add_goal(
        "ad_any", "Find any ad", goal_type="AD_DISCOVERY", target_ad_type="ANY", priority=1
    )
    obs = build_observation(
        state_id="s1",
        activity="Home",
        screenshot_path="/tmp/banner.png",
        ad_results=[
            {"detected": True, "type": "banner", "confidence": 0.9, "position": "bottom"}
        ],
    )
    agent.record_action_success(
        action_kind="tap",
        action_key="tap:Home",
        action_label="Home",
        state_id="s0",
        next_state_id="s1",
    )
    ev = GoalEvaluator().evaluate(
        goal, observation=obs, agent_state=agent, discovery_mode="first_match"
    )
    apply_goal_evaluation(agent, ev, discovery_mode="first_match")
    assert ev.outcome == "GOAL_FOUND"
    assert agent.discovered_ad_placements[0].screenshot == "/tmp/banner.png"
    assert agent.discovered_ad_placements[0].state_id == "s1"


def test_wrong_format_not_found() -> None:
    agent = AgentState.create_initial(package_name="com.example.app", seed_goals=False)
    goal = agent.add_goal(
        "ad_r", "Rewarded", goal_type="AD_DISCOVERY", target_ad_type="REWARDED"
    )
    obs = build_observation(
        state_id="s1",
        ad_results=[
            {"detected": True, "type": "banner", "confidence": 0.95, "position": "bottom"}
        ],
    )
    ev = GoalEvaluator().evaluate(goal, observation=obs, agent_state=agent)
    assert ev.outcome != "GOAL_FOUND"


def test_delayed_ad_sequence() -> None:
    provider = DelayedObservationProvider(
        [
            {
                "package_name": "com.example.app",
                "activity": "Home",
                "state_id": "s0",
                "elements": [make_element("Play")],
                "ad_results": [],
            },
            {
                "package_name": "com.example.app",
                "activity": "Home",
                "state_id": "s0",
                "elements": [make_element("Play")],
                "ad_results": [],
            },
            {
                "package_name": "com.example.app",
                "activity": "Home",
                "state_id": "s0",
                "elements": [make_element("Play")],
                "ad_results": [
                    {
                        "detected": True,
                        "type": "banner",
                        "confidence": 0.85,
                        "position": "bottom",
                        "image_path": "/tmp/late.png",
                    }
                ],
            },
        ]
    )
    agent = AgentState.create_initial(package_name="com.example.app", seed_goals=False)
    goal = agent.add_goal(
        "ad_b", "Banner", goal_type="AD_DISCOVERY", target_ad_type="BANNER"
    )
    verifier = ActionVerifier()
    before = provider.next()
    mid = provider.next()
    r1 = verifier.verify(
        planned=_planned(kind="wait", key="wait:1"),
        executor_result=_exec(ok=True, key="wait:1"),
        before=before,
        after=mid,
    )
    assert r1.outcome is VerifyOutcome.SUCCESS
    after = provider.next()
    r2 = verifier.verify(
        planned=_planned(kind="tap"),
        executor_result=_exec(ok=True),
        before=mid,
        after=after,
    )
    assert r2.outcome is VerifyOutcome.SUCCESS
    assert r2.reason == "runtime_ads_appeared"
    ev = GoalEvaluator().evaluate(
        goal, observation=after, agent_state=agent, discovery_mode="first_match"
    )
    apply_goal_evaluation(agent, ev, discovery_mode="first_match")
    assert goal.status == "found"
    assert agent.discovered_ad_placements[0].state_id == "s0"


def test_multiple_placements_discover_all() -> None:
    agent = AgentState.create_initial(package_name="com.example.app", seed_goals=False)
    goal = agent.add_goal(
        "ad_b", "Banner", goal_type="AD_DISCOVERY", target_ad_type="BANNER"
    )
    for sid, act in (("home", "Home"), ("details", "Details"), ("article", "Article")):
        obs = build_observation(
            state_id=sid,
            activity=act,
            screenshot_path=f"/tmp/{sid}.png",
            ad_results=[
                {
                    "detected": True,
                    "type": "banner",
                    "confidence": 0.9,
                    "position": "bottom",
                    "image_path": f"/tmp/{sid}.png",
                }
            ],
        )
        ev = GoalEvaluator().evaluate(
            goal, observation=obs, agent_state=agent, discovery_mode="discover_all"
        )
        apply_goal_evaluation(agent, ev, discovery_mode="discover_all")
    assert len(agent.discovered_ad_placements) == 3
    assert goal.status == "active"


def test_duplicate_ad_suppressed() -> None:
    agent = AgentState.create_initial(package_name="com.example.app", seed_goals=False)
    goal = agent.add_goal(
        "ad_b", "Banner", goal_type="AD_DISCOVERY", target_ad_type="BANNER"
    )
    ads = [
        {
            "detected": True,
            "type": "banner",
            "confidence": 0.9,
            "position": "bottom",
            "image_path": "same.png",
        }
    ]
    obs = build_observation(state_id="s0", activity="Home", ad_results=ads)
    for _ in range(4):
        ev = GoalEvaluator().evaluate(
            goal, observation=obs, agent_state=agent, discovery_mode="discover_all"
        )
        apply_goal_evaluation(agent, ev, discovery_mode="discover_all")
    assert len(agent.discovered_ad_placements) == 1
    assert agent.reliability["duplicate_discoveries_suppressed"] >= 1


def test_first_match_completes_and_stops_pursuing() -> None:
    agent = AgentState.create_initial(package_name="com.example.app", seed_goals=False)
    goal = agent.add_goal(
        "ad_r", "Rewarded", goal_type="AD_DISCOVERY", target_ad_type="REWARDED", priority=1
    )
    obs = build_observation(
        state_id="s1",
        ad_results=[{"detected": True, "type": "rewarded", "confidence": 0.9}],
    )
    ev = GoalEvaluator().evaluate(
        goal, observation=obs, agent_state=agent, discovery_mode="first_match"
    )
    apply_goal_evaluation(agent, ev, discovery_mode="first_match")
    assert goal.status == "found"
    ev2 = GoalEvaluator().evaluate(
        goal, observation=obs, agent_state=agent, discovery_mode="first_match"
    )
    assert ev2.outcome == "GOAL_FOUND"
    assert ev2.reason.startswith("already_")


def test_multiple_goal_transitions() -> None:
    intel = ApplicationIntelligence(
        status="ready",
        ads={
            "ad_formats": [
                {"format": "REWARDED", "confidence": 0.95},
                {"format": "INTERSTITIAL", "confidence": 0.9},
                {"format": "BANNER", "confidence": 0.8},
            ]
        },
    )
    goals = AdGoalGenerator().generate(intel)
    assert [g.target_ad_type for g in goals] == ["REWARDED", "INTERSTITIAL", "BANNER"]
    agent = AgentState.create_initial(package_name="com.example.app", seed_goals=False)
    for g in goals:
        g.status = "pending" if g.target_ad_type != "REWARDED" else "active"
        agent.active_goals.append(g)
    obs_r = build_observation(
        state_id="s1",
        ad_results=[{"detected": True, "type": "rewarded", "confidence": 0.95}],
    )
    g_r = next(g for g in agent.active_goals if g.target_ad_type == "REWARDED")
    apply_goal_evaluation(
        agent,
        GoalEvaluator().evaluate(
            g_r, observation=obs_r, agent_state=agent, discovery_mode="first_match"
        ),
        discovery_mode="first_match",
    )
    assert g_r.status == "found"
    g_i = next(g for g in agent.active_goals if g.target_ad_type == "INTERSTITIAL")
    assert g_i.status == "active"
    obs_i = build_observation(
        state_id="s2",
        ad_results=[{"detected": True, "type": "interstitial", "confidence": 0.9}],
    )
    apply_goal_evaluation(
        agent,
        GoalEvaluator().evaluate(
            g_i, observation=obs_i, agent_state=agent, discovery_mode="first_match"
        ),
        discovery_mode="first_match",
    )
    g_b = next(g for g in agent.active_goals if g.target_ad_type == "BANNER")
    assert g_b.status == "active"
    agent.mark_completed(reason="max_exploration_actions")
    assert g_b.status == "exhausted"
    assert len(agent.discovered_ad_placements) == 2


def test_webview_alone_not_ad() -> None:
    agent = AgentState.create_initial(package_name="com.example.app", seed_goals=False)
    goal = agent.add_goal(
        "ad_any", "Any", goal_type="AD_DISCOVERY", target_ad_type="ANY"
    )
    el = UIElement(
        text="content",
        resource_id="",
        content_description="",
        class_name="android.webkit.WebView",
        package="com.example.app",
        bounds=(0, 0, 1080, 2400),
        clickable=False,
        enabled=True,
        scrollable=True,
        visible=True,
        selected=False,
        checked=False,
        focused=False,
        focusable=False,
    )
    obs = build_observation(
        state_id="s0",
        elements=[el],
        ad_results=[],
    )
    assert obs.webview_detected is True
    ev = GoalEvaluator().evaluate(goal, observation=obs, agent_state=agent)
    assert ev.outcome != "GOAL_FOUND"


# ---------------------------------------------------------------------------
# 12H-9 HITL
# ---------------------------------------------------------------------------


def test_hitl_pauses_supervisor_and_blocks_goal() -> None:
    agent = AgentState.create_initial(package_name="com.example.app", seed_goals=False)
    agent.sync_budgets(actions_used=1, states_discovered=1, current_depth=0)
    goal = agent.add_goal(
        "ad_r", "Rewarded", goal_type="AD_DISCOVERY", target_ad_type="REWARDED"
    )
    obs = build_observation(
        state_id="s0",
        hitl={"required": True, "type": "CAPTCHA", "message": "Verify"},
    )
    agent.update_observation(obs)
    verify = ActionVerifier().verify(
        planned=_planned(), executor_result=_exec(ok=True), before=None, after=obs
    )
    assert verify.outcome is VerifyOutcome.BLOCKED
    d = ExplorationSupervisor().decide(
        SupervisorContext(
            agent_state=agent,
            verify=verify,
            executor=_exec(ok=True),
            planned=_planned(),
            has_parent=True,
            app_running=True,
        )
    )
    assert d.decision is SupervisorDecisionKind.PAUSE_HITL
    ev = GoalEvaluator().evaluate(goal, observation=obs, agent_state=agent)
    apply_goal_evaluation(agent, ev)
    assert ev.outcome == "GOAL_BLOCKED"
    assert goal.status == "blocked"
    fresh = build_observation(state_id="s1", activity="Home", elements=[make_element("OK")])
    agent.clear_blocked()
    agent.update_observation(fresh)
    assert agent.hitl_required is False
    assert agent.current_state_id == "s1"


# ---------------------------------------------------------------------------
# 12H-11 Budgets
# ---------------------------------------------------------------------------


def test_budget_actions_stop() -> None:
    agent = AgentState.create_initial(
        package_name="com.example.app", seed_goals=False, max_actions=2
    )
    agent.sync_budgets(actions_used=2, states_discovered=0, current_depth=0)
    d = ExplorationSupervisor().decide(
        SupervisorContext(
            agent_state=agent,
            verify=None,
            executor=_exec(ok=True),
            planned=_planned(),
            app_running=True,
        )
    )
    assert d.decision is SupervisorDecisionKind.STOP
    assert d.reason == "budget_actions_exhausted"


def test_budget_states_stop() -> None:
    agent = AgentState.create_initial(
        package_name="com.example.app", seed_goals=False, max_states=1
    )
    agent.sync_budgets(actions_used=0, states_discovered=1, current_depth=0)
    d = ExplorationSupervisor().decide(
        SupervisorContext(
            agent_state=agent,
            verify=None,
            executor=_exec(ok=True),
            planned=_planned(),
            app_running=True,
        )
    )
    assert d.decision is SupervisorDecisionKind.STOP
    assert d.reason == "budget_states_exhausted"


# ---------------------------------------------------------------------------
# 12H-12 AI resilience + candidate bound
# ---------------------------------------------------------------------------


def test_ai_timeout_fallback() -> None:
    cands = [_planned(key="tap:A", label="A")]
    with patch("app.modules.ai_explorer.advisor.should_invoke_ai", return_value=(True, "forced")):
        with patch(
            "app.modules.ai_explorer.advisor.chat_json",
            side_effect=FailingAIProvider("timeout"),
        ):
            planned, meta = ExplorationAdvisor(enabled=True).choose(cands, force=True)
    assert planned is None
    assert meta["ai_used"] is False
    assert meta.get("fallback")


def test_ai_invalid_json_fallback() -> None:
    cands = [_planned(key="tap:A", label="A")]
    with patch("app.modules.ai_explorer.advisor.should_invoke_ai", return_value=(True, "forced")):
        with patch(
            "app.modules.ai_explorer.advisor.chat_json",
            side_effect=FailingAIProvider("invalid_json"),
        ):
            planned, meta = ExplorationAdvisor(enabled=True).choose(cands, force=True)
    assert planned is None
    assert meta["ai_used"] is False


def test_ai_low_confidence_fallback() -> None:
    cands = [_planned(key="tap:A", label="A")]
    with patch("app.modules.ai_explorer.advisor.should_invoke_ai", return_value=(True, "forced")):
        with patch(
            "app.modules.ai_explorer.advisor.chat_json",
            side_effect=FailingAIProvider("low_confidence"),
        ):
            planned, meta = ExplorationAdvisor(enabled=True, min_confidence=0.5).choose(
                cands, force=True
            )
    assert planned is None
    assert meta["ai_used"] is False


def test_ai_invalid_candidate_and_shell_rejected() -> None:
    cands = [_planned(key="tap:A", label="A")]
    for mode in ("invalid_candidate", "shell"):
        with patch(
            "app.modules.ai_explorer.advisor.should_invoke_ai", return_value=(True, "forced")
        ):
            with patch(
                "app.modules.ai_explorer.advisor.chat_json",
                side_effect=FailingAIProvider(mode),
            ):
                planned, meta = ExplorationAdvisor(enabled=True).choose(cands, force=True)
        assert planned is None
        assert meta["ai_used"] is False


def test_ai_cannot_select_forbidden_kinds() -> None:
    assert "shell" not in ALLOWED_ACTION_KINDS
    assert "adb" not in ALLOWED_ACTION_KINDS
    cands = [_planned(key="tap:A", label="A")]
    decision = parse_ai_decision(
        {
            "action": "tap",
            "target": "tap:A",
            "confidence": 0.9,
            "reason": "ok",
        }
    )
    mapped = map_decision_to_planned(decision, cands)
    assert mapped.key == "tap:A"


# ---------------------------------------------------------------------------
# 12H-13 Evidence consistency
# ---------------------------------------------------------------------------


def test_evidence_path_matches_observation_state() -> None:
    agent = AgentState.create_initial(package_name="com.example.app", seed_goals=False)
    goal = agent.add_goal(
        "ad_r", "Rewarded", goal_type="AD_DISCOVERY", target_ad_type="REWARDED"
    )
    agent.record_action_success(
        action_kind="tap",
        action_key="tap:Play",
        action_label="Play",
        state_id="home",
        next_state_id="reward",
    )
    agent.record_action_success(
        action_kind="tap",
        action_key="tap:Watch",
        action_label="Watch Ad",
        state_id="reward",
        next_state_id="ad",
    )
    obs = build_observation(
        state_id="ad",
        activity="RewardActivity",
        screenshot_path="/tmp/rewarded.png",
        ad_results=[
            {
                "detected": True,
                "type": "rewarded",
                "confidence": 0.94,
                "position": "fullscreen",
                "image_path": "/tmp/rewarded.png",
            }
        ],
    )
    ev = GoalEvaluator().evaluate(
        goal, observation=obs, agent_state=agent, discovery_mode="first_match"
    )
    apply_goal_evaluation(agent, ev, discovery_mode="first_match")
    disc = agent.discovered_ad_placements[0]
    assert disc.state_id == "ad"
    assert disc.activity == "RewardActivity"
    assert disc.screenshot == "/tmp/rewarded.png"
    labels = [s.get("target") for s in disc.trigger_path]
    assert "Play" in labels
    assert "Watch Ad" in labels


# ---------------------------------------------------------------------------
# Invariants + soak
# ---------------------------------------------------------------------------


def test_invariant_static_never_found_and_hitl_blocks() -> None:
    goals = AdGoalGenerator().generate(
        ApplicationIntelligence(
            ads={"ad_formats": [{"format": "REWARDED", "confidence": 0.99}]}
        )
    )
    assert goals and goals[0].status == "active"
    assert "shell" not in ALLOWED_ACTION_KINDS


def test_invariant_history_bounded_under_duplicate_obs() -> None:
    agent = AgentState.create_initial(package_name="com.example.app", seed_goals=False)
    agent._max_history = 20
    obs = build_observation(state_id="s0", activity="Home", elements=[make_element("X")])
    for i in range(100):
        agent.update_observation(obs)
        agent.record_action_success(
            action_kind="wait",
            action_key=f"wait:{i % 3}",
            state_id="s0",
            next_state_id="s0",
        )
    assert len(agent.history) <= 20
    assert agent.reliability["observations"] == 100


def test_soak_seeded_failure_combinations() -> None:
    """Deterministic seeded soak: mixed success/fail/HITL/ads/AI — must terminate."""
    rng = random.Random(12345)
    screens = {
        "home": SimulatedScreen("home", "Home", labels=["Play", "Shop", "Settings"]),
        "play": SimulatedScreen("play", "Play", labels=["Watch Ad", "Back"]),
        "ad": SimulatedScreen(
            "ad",
            "AdActivity",
            labels=["Close"],
            ads=[
                {
                    "detected": True,
                    "type": "rewarded",
                    "confidence": 0.9,
                    "position": "fullscreen",
                    "image_path": "ad.png",
                }
            ],
        ),
        "login": SimulatedScreen(
            "login",
            "Login",
            labels=["Sign in"],
            hitl={"required": True, "type": "LOGIN", "message": "Login"},
        ),
        "crash": SimulatedScreen("crash", "Dead", labels=[], crash=True),
    }
    transitions = {
        ("home", "Play"): "play",
        ("home", "Shop"): "home",
        ("play", "Watch Ad"): "ad",
        ("play", "Back"): "home",
        ("ad", "Close"): "home",
        ("home", "Settings"): "login",
    }
    sim = ExplorationSimulator(screens, transitions=transitions, seed=12345)
    agent = AgentState.create_initial(
        package_name="com.example.app",
        seed_goals=False,
        max_actions=200,
        max_states=50,
    )
    goal = agent.add_goal(
        "ad_r", "Rewarded", goal_type="AD_DISCOVERY", target_ad_type="REWARDED"
    )
    # Fresh supervisor each crash cycle would reset relaunch — keep one instance
    # but also allow goal_found / budget to terminate.
    sup = ExplorationSupervisor(
        max_retries_per_action=1,
        max_consecutive_no_change=3,
        max_recovery_without_progress=20,
        max_relaunches=5,
    )
    verifier = ActionVerifier()
    ui = FailingUIController(fail_n=0)
    executor = ActionExecutor(ui)
    stop_reason = None
    iterations = 250
    prev_obs = sim.observe()
    agent.update_observation(prev_obs)

    for step in range(iterations):
        agent.sync_budgets(
            actions_used=step,
            states_discovered=len({o.state_id for o in sim.observations if o.state_id}),
            current_depth=min(step, 10),
        )
        if agent.remaining_actions <= 0:
            stop_reason = "budget_actions_exhausted"
            break

        if rng.random() < 0.1:
            agent.record_ai_decision(
                used=False,
                meta={
                    "fallback": "deterministic_after_ai_failure",
                    "ai_error": "TimeoutError",
                },
                planner_source="DETERMINISTIC_FALLBACK",
            )

        screen = screens[sim.current]
        if screen.hitl:
            obs = sim.observe()
            agent.update_observation(obs)
            vr = verifier.verify(
                planned=_planned(),
                executor_result=_exec(ok=True),
                before=prev_obs,
                after=obs,
            )
            d = sup.decide(
                SupervisorContext(
                    agent_state=agent,
                    verify=vr,
                    executor=_exec(ok=True),
                    planned=_planned(),
                    has_parent=True,
                    app_running=sim.app_running,
                )
            )
            assert d.decision is SupervisorDecisionKind.PAUSE_HITL
            screens["login"].hitl = None
            sim.current = "home"
            sim.app_running = True
            prev_obs = sim.observe()
            agent.clear_blocked()
            agent.update_observation(prev_obs)
            continue

        if not sim.app_running or screen.crash:
            d = sup.decide(
                SupervisorContext(
                    agent_state=agent,
                    verify=None,
                    executor=_exec(ok=False, error="crash"),
                    planned=_planned(),
                    has_parent=False,
                    app_running=False,
                )
            )
            if d.decision is SupervisorDecisionKind.STOP:
                stop_reason = d.reason
                break
            sim.current = "home"
            sim.app_running = True
            screens["crash"].crash = False
            prev_obs = sim.observe()
            agent.update_observation(prev_obs)
            continue

        labels = screen.labels or ["noop"]
        label = rng.choice(labels)
        planned = _planned(key=f"tap:{label}", label=label)
        if rng.random() < 0.15:
            ui_fail = FailingUIController(fail_kinds={"tap"})
            er = ActionExecutor(ui_fail).execute(planned, agent_state=agent)
        else:
            er = executor.execute(planned, agent_state=agent)
            sim.apply_action(label)

        after = sim.observe()
        agent.update_observation(after)
        if er.success:
            agent.record_action_success(
                action_kind="tap",
                action_key=planned.key,
                action_label=label,
                state_id=prev_obs.state_id,
                next_state_id=after.state_id,
            )
        else:
            agent.record_action(
                action_kind="tap",
                action_key=planned.key,
                action_label=label,
                state_id=prev_obs.state_id,
                success=False,
                failure_reason=er.error,
            )

        vr = verifier.verify(
            planned=planned, executor_result=er, before=prev_obs, after=after
        )
        d = sup.decide(
            SupervisorContext(
                agent_state=agent,
                verify=vr,
                executor=er,
                planned=planned,
                has_parent=True,
                app_running=sim.app_running,
                engine_stagnation_count=0,
            )
        )
        if d.decision is SupervisorDecisionKind.STOP:
            stop_reason = d.reason
            break

        ev = GoalEvaluator().evaluate(
            goal, observation=after, agent_state=agent, discovery_mode="first_match"
        )
        apply_goal_evaluation(agent, ev, discovery_mode="first_match")
        if goal.status == "found":
            stop_reason = "goal_found"
            break

        prev_obs = after
        if rng.random() < 0.05:
            sim.current = "crash"
            screens["crash"].crash = True

    assert stop_reason is not None
    assert len(agent.history) <= agent._max_history
    assert len(sim.observations) <= iterations + 5
    json.dumps(agent.to_dict())


def test_network_failure_no_false_ad_and_bounded() -> None:
    agent = AgentState.create_initial(
        package_name="com.example.app", seed_goals=False, max_actions=5
    )
    goal = agent.add_goal(
        "ad_r", "Rewarded", goal_type="AD_DISCOVERY", target_ad_type="REWARDED"
    )
    obs = build_observation(
        state_id="s0",
        activity="Home",
        elements=[make_element("Loading…")],
        ad_results=[],
    )
    for i in range(5):
        agent.sync_budgets(actions_used=i, states_discovered=1, current_depth=1)
        agent.update_observation(obs)
        ev = GoalEvaluator().evaluate(goal, observation=obs, agent_state=agent)
        assert ev.outcome != "GOAL_FOUND"
    agent.sync_budgets(actions_used=5, states_discovered=1, current_depth=1)
    d = ExplorationSupervisor().decide(
        SupervisorContext(agent_state=agent, app_running=True, planned=_planned())
    )
    assert d.decision is SupervisorDecisionKind.STOP
    assert goal.status == "active"
    agent.mark_completed(reason=d.reason)
    assert goal.status == "exhausted"


def test_planning_context_survives_ai_failure() -> None:
    agent = AgentState.create_initial(package_name="com.example.app", seed_goals=True)
    obs = build_observation(state_id="s0", activity="Home", elements=[make_element("A")])
    agent.update_observation(obs)
    ctx = build_planning_context(agent_state=agent, observation=obs)
    assert ctx.goal
    ui = mock_ui_success()
    result = ActionExecutor(ui).execute(_planned(), agent_state=agent)
    assert result.success is True
