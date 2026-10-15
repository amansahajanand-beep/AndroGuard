"""Phase 12G — Goal-driven ad exploration tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.modules.ai_explorer.advisor import ExplorationAdvisor
from app.modules.ai_explorer.context import build_planning_context
from app.modules.ai_explorer.prompts import SYSTEM_PROMPT, build_user_prompt
from app.modules.apk_intelligence import ApplicationIntelligence, build_application_intelligence
from app.modules.exploration.action_planner import PlannedAction
from app.modules.exploration.actions import ActionResult, TapAction
from app.modules.exploration.ad_goals import (
    AdGoalGenerator,
    GoalEvaluator,
    apply_goal_evaluation,
    fingerprints_to_ad_results,
    seed_ad_goals_from_intelligence,
)
from app.modules.exploration.agent_state import AgentGoal, AgentState
from app.modules.exploration.executor import ActionExecutor
from app.modules.exploration.observation_builder import build_observation
from app.modules.exploration.ui_element import UIElement


def _el(text: str = "Play", *, y0: int = 100, y1: int = 180) -> UIElement:
    return UIElement(
        text=text,
        resource_id="btn",
        content_description="",
        class_name="android.widget.Button",
        package="com.example.game",
        bounds=(40, y0, 400, y1),
        clickable=True,
        enabled=True,
        scrollable=False,
        visible=True,
        selected=False,
        checked=False,
        focused=False,
        focusable=True,
    )


def _tap(key: str, *, label: str = "Play", priority: int = 50) -> PlannedAction:
    return PlannedAction(
        key=key,
        action=TapAction(element=_el(label)),
        kind="tap",
        priority=priority,
        label=label,
    )


def _intel_with_formats(*formats: str, confidence: float = 0.92) -> ApplicationIntelligence:
    analysis = {
        "apk": {"package_name": "com.example.game", "version_name": "1.0"},
        "manifest": {"package": "com.example.game"},
        "permissions": [],
        "activities": [
            {
                "name": "com.example.game.MainActivity",
                "exported": True,
                "enabled": True,
                "intent_filters": [
                    {
                        "actions": ["android.intent.action.MAIN"],
                        "categories": ["android.intent.category.LAUNCHER"],
                        "data": [],
                    }
                ],
            }
        ],
        "services": [],
        "receivers": [],
        "providers": [],
        "code": {
            "classes": [{"name": f"com.google.android.gms.ads.{fmt}Ad"} for fmt in formats],
            "methods": [],
        },
        "third_party_sdk_usage": [{"name": "Google Mobile Ads", "evidence": []}],
    }
    # Force formats if builder misses (deterministic stub overlay).
    intel = build_application_intelligence(analysis)
    if formats and not (intel.ads.get("ad_formats") or []):
        intel.ads = {
            **(intel.ads or {}),
            "ad_formats": [
                {"format": f, "confidence": confidence, "kind": "LIKELY_FORMAT"}
                for f in formats
            ],
            "sdk_candidates": [{"name": "Google Mobile Ads", "confidence": 0.94}],
        }
    return intel


def test_goal_generation_rewarded_signal() -> None:
    intel = _intel_with_formats("REWARDED")
    goals = AdGoalGenerator().generate(intel)
    assert any(g.target_ad_type == "REWARDED" and g.goal_type == "AD_DISCOVERY" for g in goals)
    assert not any(g.target_ad_type == "BANNER" for g in goals)


def test_no_false_goal_without_signals() -> None:
    intel = ApplicationIntelligence(status="empty", application={"package_name": "x"})
    goals = AdGoalGenerator().generate(intel)
    assert goals == []
    any_goals = AdGoalGenerator().generate(intel, include_any=True)
    assert len(any_goals) == 1
    assert any_goals[0].target_ad_type == "ANY"


def test_goal_priority_high_confidence() -> None:
    intel = ApplicationIntelligence(
        status="ready",
        ads={
            "ad_formats": [
                {"format": "BANNER", "confidence": 0.5, "kind": "POSSIBLE_FORMAT"},
                {"format": "REWARDED", "confidence": 0.95, "kind": "LIKELY_FORMAT"},
            ]
        },
    )
    goals = AdGoalGenerator().generate(intel)
    by_type = {g.target_ad_type: g for g in goals}
    assert by_type["REWARDED"].priority < by_type["BANNER"].priority


def test_goal_evaluation_runtime_found() -> None:
    agent = AgentState.create_initial(package_name="com.example.game", seed_goals=False)
    goal = agent.add_goal(
        "ad_rewarded",
        "Find rewarded",
        goal_type="AD_DISCOVERY",
        priority=10,
        target_ad_type="REWARDED",
    )
    obs = build_observation(
        package_name="com.example.game",
        activity="GameActivity",
        state_id="state_17",
        ad_results=[
            {
                "detected": True,
                "type": "rewarded",
                "confidence": 0.94,
                "position": "fullscreen",
                "image_path": "/tmp/shot.png",
            }
        ],
    )
    agent.record_action_success(
        action_kind="tap",
        action_key="tap:Watch Ad",
        action_label="Watch Ad",
        state_id="state_16",
        next_state_id="state_17",
    )
    ev = GoalEvaluator(min_confidence=0.45).evaluate(
        goal, observation=obs, agent_state=agent, discovery_mode="first_match"
    )
    assert ev.outcome == "GOAL_FOUND"
    assert ev.discovery is not None
    assert ev.discovery.ad_type == "REWARDED"
    assert any(step.get("target") == "Watch Ad" for step in ev.discovery.trigger_path)
    apply_goal_evaluation(agent, ev, discovery_mode="first_match")
    assert goal.status == "found"
    assert len(agent.discovered_ad_placements) == 1


def test_static_evidence_alone_not_found() -> None:
    intel = _intel_with_formats("REWARDED")
    agent = AgentState.create_initial(
        package_name="com.example.game",
        seed_goals=False,
        application_intelligence=intel,
    )
    seed_ad_goals_from_intelligence(agent, intel)
    goal = next(g for g in agent.active_goals if g.target_ad_type == "REWARDED")
    obs = build_observation(
        package_name="com.example.game",
        activity="Home",
        state_id="s1",
        ad_results=[],
    )
    ev = GoalEvaluator().evaluate(goal, observation=obs, agent_state=agent)
    assert ev.outcome in {"GOAL_NOT_MET", "GOAL_PROGRESS"}
    assert goal.status == "active"


def test_wrong_ad_type_keeps_goal_active() -> None:
    agent = AgentState.create_initial(package_name="com.example.game", seed_goals=False)
    goal = agent.add_goal(
        "ad_rewarded",
        "Find rewarded",
        goal_type="AD_DISCOVERY",
        target_ad_type="REWARDED",
    )
    obs = build_observation(
        package_name="com.example.game",
        activity="Home",
        state_id="s1",
        ad_results=[
            {"detected": True, "type": "interstitial", "confidence": 0.9, "position": "fullscreen"}
        ],
    )
    ev = GoalEvaluator().evaluate(goal, observation=obs, agent_state=agent)
    assert ev.outcome in {"GOAL_NOT_MET", "GOAL_PROGRESS"}
    assert goal.status == "active"


def test_duplicate_placement_suppressed() -> None:
    agent = AgentState.create_initial(package_name="com.example.game", seed_goals=False)
    goal = agent.add_goal(
        "ad_rewarded",
        "Find rewarded",
        goal_type="AD_DISCOVERY",
        target_ad_type="REWARDED",
    )
    ads = [
        {
            "detected": True,
            "type": "rewarded",
            "confidence": 0.9,
            "position": "fullscreen",
            "image_path": "a.png",
        }
    ]
    obs = build_observation(
        package_name="com.example.game",
        activity="Game",
        state_id="s1",
        ad_results=ads,
    )
    ev1 = GoalEvaluator().evaluate(
        goal, observation=obs, agent_state=agent, discovery_mode="discover_all"
    )
    apply_goal_evaluation(agent, ev1, discovery_mode="discover_all")
    ev2 = GoalEvaluator().evaluate(
        goal, observation=obs, agent_state=agent, discovery_mode="discover_all"
    )
    apply_goal_evaluation(agent, ev2, discovery_mode="discover_all")
    assert len(agent.discovered_ad_placements) == 1
    assert goal.status == "active"  # discover_all keeps active


def test_different_state_separate_discovery() -> None:
    agent = AgentState.create_initial(package_name="com.example.game", seed_goals=False)
    goal = agent.add_goal(
        "ad_rewarded",
        "Find rewarded",
        goal_type="AD_DISCOVERY",
        target_ad_type="REWARDED",
    )
    for sid, act in (("s1", "Game"), ("s2", "Shop")):
        obs = build_observation(
            package_name="com.example.game",
            activity=act,
            state_id=sid,
            ad_results=[
                {
                    "detected": True,
                    "type": "rewarded",
                    "confidence": 0.9,
                    "position": "fullscreen",
                    "image_path": f"{sid}.png",
                }
            ],
        )
        ev = GoalEvaluator().evaluate(
            goal, observation=obs, agent_state=agent, discovery_mode="discover_all"
        )
        apply_goal_evaluation(agent, ev, discovery_mode="discover_all")
    assert len(agent.discovered_ad_placements) == 2


def test_first_match_completes_goal() -> None:
    agent = AgentState.create_initial(package_name="com.example.game", seed_goals=False)
    goal = agent.add_goal(
        "ad_rewarded",
        "Find rewarded",
        goal_type="AD_DISCOVERY",
        target_ad_type="REWARDED",
    )
    obs = build_observation(
        package_name="com.example.game",
        activity="Game",
        state_id="s1",
        ad_results=[{"detected": True, "type": "rewarded", "confidence": 0.9}],
    )
    ev = GoalEvaluator().evaluate(
        goal, observation=obs, agent_state=agent, discovery_mode="first_match"
    )
    apply_goal_evaluation(agent, ev, discovery_mode="first_match")
    assert goal.status == "found"
    assert goal not in agent.active_goals


def test_ai_context_includes_ad_goal() -> None:
    intel = _intel_with_formats("REWARDED", "INTERSTITIAL")
    agent = AgentState.create_initial(
        package_name="com.example.game",
        seed_goals=True,
        application_intelligence=intel,
    )
    seed_ad_goals_from_intelligence(agent, intel)
    obs = build_observation(
        package_name="com.example.game",
        activity="Home",
        elements=[_el("Get Coins")],
        state_id="s0",
        ad_results=[],
    )
    agent.update_observation(obs)
    ctx = build_planning_context(agent_state=agent, observation=obs)
    assert ctx.goal["goal_type"] == "AD_DISCOVERY"
    assert ctx.goal.get("target_ad_type") in {"REWARDED", "INTERSTITIAL"}
    assert ctx.application_intelligence is not None
    prompt = build_user_prompt(
        activity="Home",
        package_name="com.example.game",
        candidates=[{"key": "tap:Get Coins", "action": "tap", "label": "Get Coins"}],
        visited_summary=[],
        planning_context=ctx.to_dict(),
    )
    assert "AD_DISCOVERY" in prompt or "target_ad_type=" in prompt
    assert "Static" in SYSTEM_PROMPT or "HYPOTHES" in SYSTEM_PROMPT.upper()
    assert "showRewarded" in SYSTEM_PROMPT or "SDK" in SYSTEM_PROMPT


def test_candidate_safety_ai_cannot_invent() -> None:
    agent = AgentState.create_initial(package_name="com.example.game", seed_goals=False)
    agent.add_goal(
        "ad_rewarded",
        "Find rewarded",
        goal_type="AD_DISCOVERY",
        target_ad_type="REWARDED",
        priority=1,
    )
    cands = [_tap("tap:Play", label="Play", priority=10)]
    fake = {
        "action": "tap",
        "target": "tap:showRewarded",
        "text": None,
        "confidence": 0.99,
        "reason": "call SDK",
    }
    with patch("app.modules.ai_explorer.advisor.should_invoke_ai", return_value=(True, "forced")):
        with patch("app.modules.ai_explorer.advisor.chat_json", return_value=fake):
            advisor = ExplorationAdvisor(enabled=True)
            planned, meta = advisor.choose(
                cands,
                force=True,
                planning_context=build_planning_context(agent_state=agent),
            )
    # Invalid target → fallback / reject inventing
    assert planned is None
    assert meta.get("ai_used") is False


def test_ai_failure_deterministic_fallback() -> None:
    agent = AgentState.create_initial(package_name="com.example.game", seed_goals=False)
    agent.add_goal(
        "ad_rewarded",
        "Find rewarded",
        goal_type="AD_DISCOVERY",
        target_ad_type="REWARDED",
        priority=1,
    )
    cands = [_tap("tap:A", priority=90), _tap("tap:B", priority=10)]
    advisor = ExplorationAdvisor(enabled=False)
    planned, meta = advisor.choose(
        cands, planning_context=build_planning_context(agent_state=agent)
    )
    assert planned is None
    assert meta["ai_used"] is False
    # Deterministic planner path still executes via ActionExecutor.
    ui = MagicMock()
    ui.perform.return_value = ActionResult(kind="tap", ok=True)
    result = ActionExecutor(ui).execute(cands[0], agent_state=agent)
    assert result.success is True


def test_hitl_blocks_goal_as_blocked() -> None:
    agent = AgentState.create_initial(package_name="com.example.game", seed_goals=False)
    goal = agent.add_goal(
        "ad_rewarded",
        "Find rewarded",
        goal_type="AD_DISCOVERY",
        target_ad_type="REWARDED",
    )
    obs = build_observation(
        package_name="com.example.game",
        activity="Login",
        state_id="s1",
        hitl={"required": True, "type": "LOGIN", "message": "Sign in"},
    )
    ev = GoalEvaluator().evaluate(goal, observation=obs, agent_state=agent)
    assert ev.outcome == "GOAL_BLOCKED"
    apply_goal_evaluation(agent, ev)
    assert goal.status == "blocked"


def test_budget_exhausts_ad_goals() -> None:
    agent = AgentState.create_initial(package_name="com.example.game", seed_goals=False)
    goal = agent.add_goal(
        "ad_rewarded",
        "Find rewarded",
        goal_type="AD_DISCOVERY",
        target_ad_type="REWARDED",
    )
    agent.mark_completed(reason="max_exploration_actions")
    assert goal.status == "exhausted"


def test_missing_runtime_ads_no_false_completion() -> None:
    agent = AgentState.create_initial(package_name="com.example.game", seed_goals=False)
    goal = agent.add_goal(
        "ad_rewarded",
        "Find rewarded",
        goal_type="AD_DISCOVERY",
        target_ad_type="REWARDED",
    )
    obs = build_observation(
        package_name="com.example.game",
        activity="Home",
        state_id="s1",
        ad_results=None,
    )
    ev = GoalEvaluator().evaluate(goal, observation=obs, agent_state=agent)
    assert ev.outcome != "GOAL_FOUND"
    apply_goal_evaluation(agent, ev)
    assert goal.status == "active"
    assert agent.discovered_ad_placements == []


def test_fingerprints_to_ad_results() -> None:
    fp = MagicMock()
    fp.ad_type = "REWARDED"
    fp.position = "fullscreen"
    fp.screenshot_path = "/tmp/x.png"
    fp.evidence = ("class:RewardedAdView",)
    fp.relative_bbox = (0.1, 0.1, 0.9, 0.9)
    fp.uniqueness_key = "abc"
    fp.visual_state_id = "s1"
    fp.page = "Game"
    results = fingerprints_to_ad_results([fp])
    assert results and results[0]["detected"] is True
    assert results[0]["type"] in {"rewarded", "REWARDED"}


def test_integration_static_to_found_with_path() -> None:
    """End-to-end mocked: static → goal → AI → executor → runtime detect → FOUND."""
    intel = _intel_with_formats("REWARDED")
    agent = AgentState.create_initial(
        package_name="com.example.game",
        seed_goals=True,
        application_intelligence=intel,
        max_actions=50,
    )
    added = seed_ad_goals_from_intelligence(agent, intel)
    assert added
    goal = next(g for g in agent.active_goals if g.target_ad_type == "REWARDED")

    obs1 = build_observation(
        package_name="com.example.game",
        activity="Home",
        elements=[_el("Get 100 Coins")],
        state_id="s0",
        ad_results=[],
    )
    agent.update_observation(obs1)
    ctx = build_planning_context(agent_state=agent, observation=obs1)
    assert ctx.goal["goal_type"] == "AD_DISCOVERY"

    cands = [
        _tap("tap:GetCoins", label="Get 100 Coins", priority=20),
        _tap("tap:Settings", label="Settings", priority=80),
    ]
    fake = {
        "action": "tap",
        "target": "tap:GetCoins",
        "text": None,
        "confidence": 0.9,
        "reason": "likely reward path",
    }
    with patch("app.modules.ai_explorer.advisor.should_invoke_ai", return_value=(True, "forced")):
        with patch("app.modules.ai_explorer.advisor.chat_json", return_value=fake):
            advisor = ExplorationAdvisor(enabled=True)
            planned, meta = advisor.choose(cands, force=True, planning_context=ctx)
    assert planned is not None
    assert planned.key == "tap:GetCoins"
    assert meta.get("ai_used") is True

    ui = MagicMock()
    ui.perform.return_value = ActionResult(kind="tap", ok=True)
    exec_result = ActionExecutor(ui).execute(planned, agent_state=agent)
    assert exec_result.success is True
    agent.record_action_success(
        action_kind="tap",
        action_key=planned.key,
        action_label=planned.label,
        state_id="s0",
        next_state_id="s1",
    )

    obs2 = build_observation(
        package_name="com.example.game",
        activity="RewardScreen",
        elements=[_el("Watch Ad")],
        state_id="s1",
        ad_results=[
            {
                "detected": True,
                "type": "rewarded",
                "confidence": 0.93,
                "position": "fullscreen",
                "image_path": "/tmp/reward.png",
            }
        ],
    )
    agent.update_observation(obs2)
    ev = GoalEvaluator().evaluate(
        goal, observation=obs2, agent_state=agent, discovery_mode="first_match"
    )
    assert ev.outcome == "GOAL_FOUND"
    apply_goal_evaluation(agent, ev, discovery_mode="first_match")
    assert goal.status == "found"
    disc = agent.discovered_ad_placements[0]
    assert disc.ad_type == "REWARDED"
    assert disc.state_id == "s1"
    assert any("Get 100 Coins" in str(step.get("target")) for step in disc.trigger_path)


def test_integration_ai_failure_then_deterministic_find() -> None:
    intel = _intel_with_formats("INTERSTITIAL")
    agent = AgentState.create_initial(
        package_name="com.example.game",
        seed_goals=False,
        application_intelligence=intel,
    )
    seed_ad_goals_from_intelligence(agent, intel)
    goal = next(g for g in agent.active_goals if g.target_ad_type == "INTERSTITIAL")
    cands = [_tap("tap:Continue", label="Continue", priority=10)]
    advisor = ExplorationAdvisor(enabled=False)
    planned, meta = advisor.choose(cands)
    assert planned is None and meta["ai_used"] is False
    ui = MagicMock()
    ui.perform.return_value = ActionResult(kind="tap", ok=True)
    ActionExecutor(ui).execute(cands[0], agent_state=agent)
    agent.record_action_success(
        action_kind="tap",
        action_key="tap:Continue",
        action_label="Continue",
        state_id="s0",
        next_state_id="s1",
    )
    obs = build_observation(
        package_name="com.example.game",
        activity="GameOver",
        state_id="s1",
        ad_results=[
            {"detected": True, "type": "interstitial", "confidence": 0.88, "position": "fullscreen"}
        ],
    )
    ev = GoalEvaluator().evaluate(
        goal, observation=obs, agent_state=agent, discovery_mode="first_match"
    )
    apply_goal_evaluation(agent, ev, discovery_mode="first_match")
    assert goal.status == "found"
    assert agent.discovered_ad_placements[0].trigger_path


def test_seed_replaces_generic_any_goal() -> None:
    intel = _intel_with_formats("REWARDED")
    agent = AgentState.create_initial(package_name="com.example.game", seed_goals=True)
    assert any(g.id == "discover_ad_placements" for g in agent.active_goals)
    seed_ad_goals_from_intelligence(agent, intel)
    assert not any(g.id == "discover_ad_placements" for g in agent.active_goals)
    assert any(g.target_ad_type == "REWARDED" for g in agent.active_goals)
