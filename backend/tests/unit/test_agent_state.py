"""Phase 12B — AgentState unit tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

from app.modules.exploration.agent_state import AgentState, AgentStatus
from app.modules.exploration.navigation_graph import NavigationGraph
from app.modules.exploration.observation_builder import build_observation
from app.modules.exploration.ui_element import UIElement


def _el(**kwargs) -> UIElement:
    defaults = dict(
        text="",
        resource_id="",
        content_description="",
        class_name="android.widget.TextView",
        package="com.example.app",
        bounds=(0, 0, 100, 80),
        clickable=False,
        enabled=True,
        scrollable=False,
        visible=True,
        selected=False,
        checked=False,
        focused=False,
        focusable=False,
    )
    defaults.update(kwargs)
    return UIElement(**defaults)


def _obs(*, state_id: str = "s1", activity: str = "Main", ads=None):
    return build_observation(
        package_name="com.example.app",
        activity=activity,
        elements=[_el(text="Home", clickable=True)],
        screen_size=(1080, 2400),
        state_id=state_id,
        screenshot_path="/tmp/shot.png",
        screenshot_id="shot-1",
        ad_results=ads,
    )


def test_initial_defaults() -> None:
    state = AgentState.create_initial(
        package_name="com.example.app",
        max_actions=100,
        max_states=10,
        max_depth=5,
        seed_goals=True,
    )
    assert state.status == AgentStatus.EXPLORING
    assert state.current_observation is None
    assert state.current_state_id is None
    assert state.actions_used == 0
    assert state.max_actions == 100
    assert state.remaining_actions == 100
    assert state.remaining_states == 10
    assert state.remaining_depth == 5
    assert state.blocked is False
    assert state.hitl_required is False
    assert state.discovered_ads == []
    assert state.failed_actions == []
    assert len(state.active_goals) == 2
    assert state.completed_goals == []
    assert state.failed_goals == []


def test_update_observation() -> None:
    state = AgentState.create_initial(package_name="com.example.app", seed_goals=False)
    obs = _obs(state_id="home", activity="com.example/.Home")
    state.update_observation(obs)
    assert state.current_observation is obs
    assert state.current_state_id == "home"
    assert state.current_activity == "com.example/.Home"
    assert state.current_package == "com.example.app"


def test_action_history_success_and_failure() -> None:
    state = AgentState.create_initial(package_name="com.example.app", seed_goals=False)
    state.record_action_success(
        action_kind="tap",
        action_key="tap:Settings",
        action_label="Settings",
        state_id="home",
        next_state_id="settings",
    )
    assert len(state.history) == 1
    assert state.history[0].success is True
    assert state.history[0].action_kind == "tap"

    state.record_action(
        action_kind="tap",
        action_key="tap:Broken",
        action_label="Broken",
        state_id="settings",
        success=False,
        failure_reason="perform_failed",
    )
    assert state.history[-1].success is False
    assert len(state.failed_actions) == 1
    assert state.failed_actions[0].action_key == "tap:Broken"
    assert state.failed_actions[0].attempt_count == 1

    state.record_action_failure(
        action_key="tap:Broken",
        state_id="settings",
        reason="still_broken",
    )
    assert len(state.failed_actions) == 1
    assert state.failed_actions[0].attempt_count == 2


def test_state_transition() -> None:
    state = AgentState.create_initial(package_name="com.example.app", seed_goals=False)
    state.update_observation(_obs(state_id="home"))
    state.update_observation(_obs(state_id="settings", activity="Settings"))
    transitions = [h for h in state.history if h.action_kind == "transition"]
    assert len(transitions) == 1
    assert transitions[0].state_id == "home"
    assert transitions[0].next_state_id == "settings"
    assert state.current_state_id == "settings"


def test_goals() -> None:
    state = AgentState.create_initial(package_name="com.example.app", seed_goals=False)
    state.add_goal("g1", "Find home")
    state.add_goal("g2", "Find ads")
    assert len(state.active_goals) == 2
    state.complete_goal("g1", reason="seen")
    assert len(state.active_goals) == 1
    assert len(state.completed_goals) == 1
    assert state.completed_goals[0].id == "g1"
    state.fail_goal("g2", reason="timeout")
    assert state.active_goals == []
    assert len(state.failed_goals) == 1


def test_blocked_and_clear() -> None:
    state = AgentState.create_initial(package_name="com.example.app", seed_goals=False)
    state.set_blocked("login_required", hitl={"required": True, "type": "login"})
    assert state.blocked is True
    assert state.blocked_reason == "login_required"
    assert state.hitl_required is True
    assert state.status == AgentStatus.BLOCKED
    state.clear_blocked()
    assert state.blocked is False
    assert state.blocked_reason is None
    assert state.hitl_required is False
    assert state.status == AgentStatus.EXPLORING


def test_budget_remaining() -> None:
    state = AgentState.create_initial(
        package_name="com.example.app",
        max_actions=50,
        max_states=20,
        max_depth=8,
        seed_goals=False,
    )
    state.sync_budgets(actions_used=12, states_discovered=5, current_depth=3)
    assert state.remaining_actions == 38
    assert state.remaining_states == 15
    assert state.remaining_depth == 5


def test_to_dict_json_serializable() -> None:
    graph = NavigationGraph()
    # Minimal fake visited state for discovered_screens.
    record = SimpleNamespace(
        visual=SimpleNamespace(activity="Main"),
        screenshot=SimpleNamespace(local_path="/tmp/a.png"),
    )
    graph.visited_states["s1"] = record  # type: ignore[assignment]
    graph.set_current("s1")

    state = AgentState.create_initial(
        package_name="com.example.app",
        navigation_graph=graph,
        max_actions=200,
        seed_goals=True,
    )
    state.update_observation(_obs(state_id="s1"))
    state.record_action_success(
        action_kind="tap", action_key="tap:x", state_id="s1", next_state_id="s2"
    )
    payload = state.to_dict()
    # Must be JSON-serializable (no sets / enums / dataclasses).
    dumped = json.dumps(payload)
    assert "exploring" in dumped or "completed" in dumped or "idle" in dumped
    assert payload["budget"]["remaining_actions"] == 200
    assert payload["navigation"]["state_count"] == 1
    assert isinstance(payload["discovered_screens"], list)
    assert payload["current_observation"]["state_id"] == "s1"


def test_navigation_graph_not_duplicated() -> None:
    graph = NavigationGraph()
    state = AgentState.create_initial(
        package_name="com.example.app",
        navigation_graph=graph,
        seed_goals=False,
    )
    assert state.navigation_graph is graph
    graph.visited_states["a"] = SimpleNamespace(  # type: ignore[assignment]
        visual=SimpleNamespace(activity="A"),
        screenshot=SimpleNamespace(local_path=None),
    )
    assert "a" in state.visited_state_ids
    summary = state.navigation_summary()
    assert summary["state_count"] == 1
    # AgentState must not own a second visited_states dict.
    assert not hasattr(state, "visited_states") or state.visited_state_ids == ["a"]


def test_empty_ads_remain_valid() -> None:
    state = AgentState.create_initial(package_name="com.example.app", seed_goals=False)
    state.update_observation(_obs(state_id="s1", ads=None))
    assert state.discovered_ads == []
    state.record_ad({"detected": False, "type": "banner"})
    assert state.discovered_ads == []


def test_mark_completed_and_failed() -> None:
    state = AgentState.create_initial(package_name="com.example.app", seed_goals=False)
    state.mark_completed(reason="budget_exhausted")
    assert state.status == AgentStatus.COMPLETED
    assert state.stop_reason == "budget_exhausted"

    state2 = AgentState.create_initial(package_name="com.example.app", seed_goals=False)
    state2.mark_failed(reason="device_offline")
    assert state2.status == AgentStatus.FAILED
