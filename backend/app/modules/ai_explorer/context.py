"""Phase 12E — Compact AI planning context (Observation + AgentState summaries).

AI receives only serializable planning data. Never includes secrets, ADB handles,
or executable payloads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from app.modules.exploration.agent_state import AgentState
from app.modules.exploration.observation import Observation


@dataclass
class AIPlanningContext:
    """Bounded context for goal-aware AI candidate selection."""

    package_name: str | None = None
    current_state_id: str | None = None
    current_activity: str | None = None
    current_depth: int = 0

    goal: dict[str, Any] = field(
        default_factory=lambda: {
            "goal_id": "explore_application",
            "goal_type": "GENERAL_EXPLORATION",
            "description": "Explore as many unique application states as possible",
            "status": "ACTIVE",
            "priority": 1,
        }
    )
    active_goals: list[dict[str, Any]] = field(default_factory=list)

    visible_text: list[str] = field(default_factory=list)
    clickable_elements: list[dict[str, Any]] = field(default_factory=list)
    detected_ads: list[dict[str, Any]] = field(default_factory=list)
    webview_detected: bool = False

    recent_history: list[dict[str, Any]] = field(default_factory=list)
    failed_actions: list[dict[str, Any]] = field(default_factory=list)

    navigation_summary: dict[str, Any] = field(default_factory=dict)
    discovered_screens_count: int = 0
    discovered_ads_count: int = 0

    budget: dict[str, Any] = field(default_factory=dict)

    last_verification: dict[str, Any] | None = None
    last_supervisor_decision: dict[str, Any] | None = None

    # Phase 12F — compact static APK intelligence summary (optional).
    application_intelligence: dict[str, Any] | None = None

    # Phase 12J — compact spatial / gesture coverage for AI candidate selection.
    regions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "package_name": self.package_name,
            "current_state_id": self.current_state_id,
            "current_activity": self.current_activity,
            "current_depth": self.current_depth,
            "goal": dict(self.goal),
            "active_goals": list(self.active_goals),
            "visible_text": list(self.visible_text)[:40],
            "clickable_elements": list(self.clickable_elements)[:24],
            "detected_ads": list(self.detected_ads)[:10],
            "webview_detected": self.webview_detected,
            "recent_history": list(self.recent_history)[:10],
            "failed_actions": list(self.failed_actions)[:15],
            "navigation_summary": dict(self.navigation_summary),
            "discovered_screens_count": self.discovered_screens_count,
            "discovered_ads_count": self.discovered_ads_count,
            "budget": dict(self.budget),
            "last_verification": self.last_verification,
            "last_supervisor_decision": self.last_supervisor_decision,
            "application_intelligence": self.application_intelligence,
            "regions": list(self.regions)[:8],
        }


def build_planning_context(
    *,
    agent_state: AgentState | None = None,
    observation: Observation | None = None,
    package_name: str | None = None,
    activity: str | None = None,
    last_verification: Any | None = None,
    last_supervisor_decision: Any | None = None,
    history_window: int = 8,
) -> AIPlanningContext:
    """Build a compact planning context from runtime AgentState / Observation."""
    obs = observation
    if obs is None and agent_state is not None:
        obs = agent_state.current_observation

    goal = {
        "goal_id": "explore_application",
        "goal_type": "GENERAL_EXPLORATION",
        "description": "Explore as many unique application states as possible",
        "status": "ACTIVE",
        "priority": 1,
        "target_ad_type": None,
    }
    active_goals: list[dict[str, Any]] = []
    if agent_state and agent_state.active_goals:
        primary = None
        try:
            primary = agent_state.active_goal()
        except Exception:
            primary = None
        if primary is None:
            primary = agent_state.active_goals[0]
        goal = {
            "goal_id": primary.id,
            "goal_type": getattr(primary, "goal_type", None) or "GENERAL_EXPLORATION",
            "description": primary.title,
            "status": (primary.status or "active").upper(),
            "priority": int(getattr(primary, "priority", 1) or 1),
            "target_ad_type": getattr(primary, "target_ad_type", None),
        }
        active_goals = [g.to_dict() for g in agent_state.active_goals[:8]]
        # Phase 12G — enrich AD_DISCOVERY goal for AI planner.
        if goal.get("goal_type") == "AD_DISCOVERY":
            try:
                from app.modules.exploration.ad_goals import goal_context_for_ai

                ad_ctx = goal_context_for_ai(agent_state)
                if ad_ctx:
                    goal = {
                        **goal,
                        "target": ad_ctx.get("target"),
                        "target_ad_type": ad_ctx.get("target"),
                        "discoveries": ad_ctx.get("discoveries"),
                        "mode": ad_ctx.get("mode"),
                        "note": ad_ctx.get("note"),
                    }
            except Exception:
                pass

    visible_text: list[str] = []
    clickable: list[dict[str, Any]] = []
    ads: list[dict[str, Any]] = []
    webview = False
    if obs is not None:
        visible_text = list(obs.visible_text or [])[:40]
        for el in (obs.clickable_elements or [])[:24]:
            if isinstance(el, dict):
                clickable.append(
                    {
                        "text": str(el.get("text") or el.get("content_description") or "")[:40],
                        "resource_id": str(el.get("resource_id") or "")[:60],
                        "class_name": str(el.get("class_name") or "")[:40],
                    }
                )
        ads = [
            {
                "type": a.get("type"),
                "confidence": a.get("confidence"),
                "position": a.get("position"),
                "detected": a.get("detected"),
            }
            for a in (obs.detected_ads or [])[:10]
            if isinstance(a, dict)
        ]
        webview = bool(obs.webview_detected)

    recent: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    nav: dict[str, Any] = {}
    budget: dict[str, Any] = {}
    screens_count = 0
    ads_count = 0
    state_id = None
    depth = 0
    pkg = package_name
    act = activity

    if agent_state is not None:
        pkg = pkg or agent_state.package_name or agent_state.current_package
        act = act or agent_state.current_activity
        state_id = agent_state.current_state_id
        depth = int(agent_state.current_depth or 0)
        for entry in agent_state.history[-max(1, history_window) :]:
            recent.append(
                {
                    "action": entry.action_kind,
                    "label": (entry.action_label or "")[:40],
                    "state_id": entry.state_id,
                    "next_state_id": entry.next_state_id,
                    "success": entry.success,
                    "result": entry.result,
                    "failure_reason": entry.failure_reason,
                }
            )
        for item in agent_state.failed_actions[-15:]:
            failed.append(
                {
                    "action_key": item.action_key[:80],
                    "action_kind": item.action_kind,
                    "state_id": item.state_id,
                    "reason": (item.reason or "")[:80],
                    "attempt_count": item.attempt_count,
                }
            )
        nav_raw = agent_state.navigation_summary()
        visited = list(nav_raw.get("visited_states") or [])
        nav = {
            "visited_states": len(visited),
            "current_state": nav_raw.get("current_state_id") or state_id,
            "parent_state_id": nav_raw.get("parent_state_id"),
            "current_depth": depth,
            "edge_count": nav_raw.get("edge_count", 0),
            "recent_states": visited[-5:],
            "max_depth_reached": nav_raw.get("max_depth_reached"),
        }
        try:
            screens_count = len(agent_state.discovered_screens())
        except Exception:
            screens_count = len(visited)
        ads_count = len(agent_state.discovered_ads)
        budget = {
            "actions_used": agent_state.actions_used,
            "max_actions": agent_state.max_actions,
            "remaining_actions": agent_state.remaining_actions,
            "states_discovered": agent_state.states_discovered,
            "max_states": agent_state.max_states,
            "remaining_states": agent_state.remaining_states,
            "current_depth": agent_state.current_depth,
            "max_depth": agent_state.max_depth,
            "remaining_depth": agent_state.remaining_depth,
        }
    elif obs is not None:
        state_id = obs.state_id
        pkg = pkg or obs.package_name
        act = act or obs.activity

    last_verify = None
    if last_verification is not None:
        if hasattr(last_verification, "to_dict"):
            last_verify = last_verification.to_dict()
        elif isinstance(last_verification, dict):
            last_verify = dict(last_verification)

    last_sup = None
    if last_supervisor_decision is not None:
        if hasattr(last_supervisor_decision, "to_dict"):
            last_sup = last_supervisor_decision.to_dict()
        elif isinstance(last_supervisor_decision, dict):
            last_sup = dict(last_supervisor_decision)

    app_intel_summary: dict[str, Any] | None = None
    if agent_state is not None and agent_state.application_intelligence is not None:
        intel = agent_state.application_intelligence
        try:
            if hasattr(intel, "to_ai_summary"):
                app_intel_summary = intel.to_ai_summary()
            elif isinstance(intel, dict):
                app_intel_summary = dict(intel)
        except Exception:
            app_intel_summary = None

    regions: list[dict[str, Any]] = []
    if agent_state is not None and agent_state.region_memory is not None:
        try:
            regions = agent_state.region_memory.to_ai_regions(limit=8)
        except Exception:
            regions = []

    return AIPlanningContext(
        package_name=pkg,
        current_state_id=state_id,
        current_activity=act,
        current_depth=depth,
        goal=goal,
        active_goals=active_goals,
        visible_text=visible_text,
        clickable_elements=clickable,
        detected_ads=ads,
        webview_detected=webview,
        recent_history=recent,
        failed_actions=failed,
        navigation_summary=nav,
        discovered_screens_count=screens_count,
        discovered_ads_count=ads_count,
        budget=budget,
        last_verification=last_verify,
        last_supervisor_decision=last_sup,
        application_intelligence=app_intel_summary,
        regions=regions,
    )
