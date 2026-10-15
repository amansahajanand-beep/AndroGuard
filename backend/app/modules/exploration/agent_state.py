"""Phase 12B — Unified AgentState (read-only orchestration memory).

AgentState answers what the explorer knows / has done / has left — it does NOT
execute ADB, UI actions, or LLM calls. NavigationGraph remains the topology
source of truth; Observation (Phase 12A) remains the screen snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from app.modules.exploration.observation import Observation


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class AgentStatus(str, Enum):
    IDLE = "idle"
    EXPLORING = "exploring"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"


GoalStatus = Literal[
    "pending",
    "active",
    "completed",
    "failed",
    "found",
    "blocked",
    "exhausted",
]


@dataclass
class AgentGoal:
    """Exploration goal (Phase 12B/12E/12G — runtime only)."""

    id: str
    title: str
    status: GoalStatus = "active"
    reason: str | None = None
    goal_type: str = "GENERAL_EXPLORATION"
    priority: int = 1
    target_ad_type: str | None = None  # REWARDED / INTERSTITIAL / ... for AD_DISCOVERY

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "reason": self.reason,
            "goal_type": self.goal_type,
            "priority": self.priority,
            "target_ad_type": self.target_ad_type,
        }


@dataclass
class HistoryEntry:
    """One step in the exploration journey (compact, serializable)."""

    timestamp: str
    state_id: str | None = None
    action_kind: str | None = None
    action_key: str | None = None
    action_label: str | None = None
    result: str | None = None
    next_state_id: str | None = None
    success: bool = True
    failure_reason: str | None = None
    observation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "state_id": self.state_id,
            "action_kind": self.action_kind,
            "action_key": self.action_key,
            "action_label": self.action_label,
            "result": self.result,
            "next_state_id": self.next_state_id,
            "success": self.success,
            "failure_reason": self.failure_reason,
            "observation_id": self.observation_id,
        }


@dataclass
class FailedActionRecord:
    action_key: str
    action_kind: str | None = None
    state_id: str | None = None
    reason: str | None = None
    timestamp: str = field(default_factory=_utcnow_iso)
    attempt_count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_key": self.action_key,
            "action_kind": self.action_kind,
            "state_id": self.state_id,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "attempt_count": self.attempt_count,
        }


@dataclass
class RecoveryRecord:
    """Compact Supervisor recovery event (Phase 12D)."""

    timestamp: str
    decision: str
    reason: str | None = None
    action_id: str | None = None
    action_key: str | None = None
    state_id: str | None = None
    attempt: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "decision": self.decision,
            "reason": self.reason,
            "action_id": self.action_id,
            "action_key": self.action_key,
            "state_id": self.state_id,
            "attempt": self.attempt,
        }


@dataclass
class AgentState:
    """Authoritative runtime memory for the exploration agent (Phase 12B)."""

    status: AgentStatus = AgentStatus.IDLE
    package_name: str | None = None

    current_observation: Observation | None = None
    current_state_id: str | None = None
    current_activity: str | None = None
    current_package: str | None = None
    current_depth: int = 0

    # Reference only — NavigationGraph owns visited_states / visited_actions / edges.
    navigation_graph: Any | None = None

    history: list[HistoryEntry] = field(default_factory=list)
    active_goals: list[AgentGoal] = field(default_factory=list)
    completed_goals: list[AgentGoal] = field(default_factory=list)
    failed_goals: list[AgentGoal] = field(default_factory=list)

    discovered_ads: list[dict[str, Any]] = field(default_factory=list)
    failed_actions: list[FailedActionRecord] = field(default_factory=list)
    recovery_history: list[RecoveryRecord] = field(default_factory=list)

    blocked: bool = False
    blocked_reason: str | None = None
    hitl_required: bool = False
    hitl: dict[str, Any] = field(default_factory=lambda: {"required": False})

    # Budgets mirror ExplorationLimits / session counters (source of truth elsewhere).
    actions_used: int = 0
    max_actions: int = 200
    states_discovered: int = 0
    max_states: int = 25
    max_depth: int = 20

    stop_reason: str | None = None
    job_id: str | None = None

    # Phase 12E — compact AI planner telemetry (runtime only).
    last_ai_decision: dict[str, Any] | None = None
    ai_decision_count: int = 0
    ai_fallback_count: int = 0
    last_planner_source: str | None = None

    # Phase 12F — static APK intelligence (reference; built once per job).
    application_intelligence: Any | None = None
    # Phase 12G — unique runtime ad placement discoveries (bounded).
    discovered_ad_placements: list[Any] = field(default_factory=list)
    # Phase 12H — compact reliability telemetry (runtime / in-memory only).
    reliability: dict[str, int] = field(
        default_factory=lambda: {
            "actions_attempted": 0,
            "actions_succeeded": 0,
            "actions_failed": 0,
            "retries": 0,
            "backtracks": 0,
            "relaunches": 0,
            "hitl_pauses": 0,
            "ai_failures": 0,
            "goals_found": 0,
            "goals_exhausted": 0,
            "duplicate_discoveries_suppressed": 0,
            "observations": 0,
            "waits": 0,
            "skips": 0,
            "stops": 0,
            "gestures_attempted": 0,
            "gestures_new_content": 0,
            "gestures_no_change": 0,
            "gestures_boundary": 0,
        }
    )

    # Phase 12J — spatial region coverage memory (runtime only).
    region_memory: Any | None = None

    _max_history: int = 200
    _prev_state_id: str | None = field(default=None, repr=False)

    # ------------------------------------------------------------------ factory

    @classmethod
    def create_initial(
        cls,
        *,
        package_name: str | None,
        navigation_graph: Any | None = None,
        max_actions: int = 200,
        max_states: int = 25,
        max_depth: int = 20,
        job_id: str | None = None,
        seed_goals: bool = True,
        application_intelligence: Any | None = None,
    ) -> "AgentState":
        state = cls(
            status=AgentStatus.EXPLORING,
            package_name=package_name,
            current_package=package_name,
            navigation_graph=navigation_graph,
            max_actions=max_actions,
            max_states=max_states,
            max_depth=max_depth,
            job_id=job_id,
            application_intelligence=application_intelligence,
        )
        try:
            from app.modules.exploration.spatial.memory import RegionExplorationMemory

            state.region_memory = RegionExplorationMemory()
        except Exception:
            state.region_memory = None
        if seed_goals:
            state.add_goal(
                "discover_all_reachable_screens",
                "Discover reachable screens",
                goal_type="GENERAL_EXPLORATION",
                priority=90,
            )
            state.add_goal(
                "discover_ad_placements",
                "Discover ad placements when available",
                goal_type="AD_DISCOVERY",
                priority=65,
                target_ad_type="ANY",
            )
        return state

    # ------------------------------------------------------------------ derived

    @property
    def remaining_actions(self) -> int:
        return max(0, int(self.max_actions) - int(self.actions_used))

    @property
    def remaining_states(self) -> int:
        return max(0, int(self.max_states) - int(self.states_discovered))

    @property
    def remaining_depth(self) -> int:
        return max(0, int(self.max_depth) - int(self.current_depth))

    @property
    def visited_state_ids(self) -> list[str]:
        graph = self.navigation_graph
        if graph is None:
            return []
        return list(getattr(graph, "visited_states", {}) or {})

    @property
    def parent_state_id(self) -> str | None:
        graph = self.navigation_graph
        if graph is None:
            return None
        return getattr(graph, "parent_state_id", None)

    def navigation_summary(self) -> dict[str, Any]:
        """Compact NavigationGraph summary — does not dump ScreenStateRecord objects."""
        graph = self.navigation_graph
        if graph is None:
            return {
                "current_state_id": None,
                "parent_state_id": None,
                "state_count": 0,
                "edge_count": 0,
                "visited_states": [],
                "visited_actions": {},
                "depth": 0,
            }
        visited_actions_raw = getattr(graph, "visited_actions", {}) or {}
        visited_actions = {
            sid: sorted(keys) for sid, keys in visited_actions_raw.items()
        }
        return {
            "current_state_id": getattr(graph, "current_state_id", None),
            "parent_state_id": getattr(graph, "parent_state_id", None),
            "state_count": len(getattr(graph, "visited_states", {}) or {}),
            "edge_count": len(getattr(graph, "edges", []) or []),
            "visited_states": list(getattr(graph, "visited_states", {}) or {}),
            "visited_actions": visited_actions,
            "depth": int(self.current_depth),
            "max_depth_reached": (
                int(graph.max_depth()) if hasattr(graph, "max_depth") else self.current_depth
            ),
        }

    def discovered_screens(self) -> list[dict[str, Any]]:
        """Screens derived from NavigationGraph + latest observation ids when known."""
        graph = self.navigation_graph
        if graph is None:
            return []
        out: list[dict[str, Any]] = []
        labels = getattr(graph, "labels", {}) or {}
        for sid, record in (getattr(graph, "visited_states", {}) or {}).items():
            activity = None
            screenshot_path = None
            try:
                activity = record.visual.activity
                screenshot_path = getattr(record.screenshot, "local_path", None)
            except Exception:
                pass
            out.append(
                {
                    "state_id": sid,
                    "activity": activity,
                    "label": labels.get(sid),
                    "screenshot_path": screenshot_path,
                    "observation_id": (
                        self.current_observation.observation_id
                        if self.current_observation
                        and self.current_observation.state_id == sid
                        else None
                    ),
                }
            )
        return out

    # ------------------------------------------------------------------ updates

    def update_observation(self, observation: Observation | None) -> None:
        if observation is None:
            return
        self.bump_reliability("observations")
        prev = self.current_state_id
        self.current_observation = observation
        self.current_state_id = observation.state_id
        self.current_activity = observation.activity
        self.current_package = observation.package_name or self.package_name
        if observation.hitl_required:
            self.hitl_required = True
            self.hitl = dict(observation.hitl or {"required": True})
            # Record only — do not change HITL pause behavior.
        else:
            self.hitl_required = False
            self.hitl = dict(observation.hitl or {"required": False})

        # Merge ads without inventing — only store non-empty detections.
        for ad in observation.detected_ads or []:
            if isinstance(ad, dict) and ad.get("detected"):
                self.record_ad(ad)

        if self.navigation_graph is not None and observation.state_id:
            try:
                self.current_depth = int(self.navigation_graph.depth_of(observation.state_id))
            except Exception:
                pass
            self.states_discovered = len(
                getattr(self.navigation_graph, "visited_states", {}) or {}
            )

        if prev and observation.state_id and prev != observation.state_id:
            self.record_state_transition(prev, observation.state_id)

        self._prev_state_id = observation.state_id

    def sync_budgets(
        self,
        *,
        actions_used: int | None = None,
        states_discovered: int | None = None,
        current_depth: int | None = None,
    ) -> None:
        if actions_used is not None:
            self.actions_used = int(actions_used)
        if states_discovered is not None:
            self.states_discovered = int(states_discovered)
        if current_depth is not None:
            self.current_depth = int(current_depth)

    def record_action(
        self,
        *,
        action_kind: str | None,
        action_key: str | None,
        action_label: str | None = None,
        state_id: str | None = None,
        next_state_id: str | None = None,
        success: bool = True,
        failure_reason: str | None = None,
        observation_id: str | None = None,
        result: str | None = None,
    ) -> None:
        entry = HistoryEntry(
            timestamp=_utcnow_iso(),
            state_id=state_id or self.current_state_id,
            action_kind=action_kind,
            action_key=action_key,
            action_label=action_label,
            result=result or ("ok" if success else "failed"),
            next_state_id=next_state_id,
            success=success,
            failure_reason=failure_reason,
            observation_id=observation_id
            or (self.current_observation.observation_id if self.current_observation else None),
        )
        self.history.append(entry)
        if len(self.history) > self._max_history:
            del self.history[: len(self.history) - self._max_history]
        self.bump_reliability("actions_attempted")
        if success:
            self.bump_reliability("actions_succeeded")
        else:
            self.bump_reliability("actions_failed")
        if not success and action_key:
            self.record_action_failure(
                action_key=action_key,
                action_kind=action_kind,
                state_id=state_id or self.current_state_id,
                reason=failure_reason or "action_failed",
            )

    def record_action_success(
        self,
        *,
        action_kind: str | None,
        action_key: str | None,
        action_label: str | None = None,
        state_id: str | None = None,
        next_state_id: str | None = None,
    ) -> None:
        self.record_action(
            action_kind=action_kind,
            action_key=action_key,
            action_label=action_label,
            state_id=state_id,
            next_state_id=next_state_id,
            success=True,
        )

    def record_action_failure(
        self,
        *,
        action_key: str,
        action_kind: str | None = None,
        state_id: str | None = None,
        reason: str | None = None,
    ) -> None:
        for item in self.failed_actions:
            if item.action_key == action_key and item.state_id == state_id:
                item.attempt_count += 1
                item.reason = reason or item.reason
                item.timestamp = _utcnow_iso()
                return
        self.failed_actions.append(
            FailedActionRecord(
                action_key=action_key,
                action_kind=action_kind,
                state_id=state_id,
                reason=reason,
            )
        )
        if len(self.failed_actions) > 100:
            del self.failed_actions[: len(self.failed_actions) - 100]

    def record_state_transition(self, from_state_id: str, to_state_id: str) -> None:
        self.history.append(
            HistoryEntry(
                timestamp=_utcnow_iso(),
                state_id=from_state_id,
                action_kind="transition",
                result="state_change",
                next_state_id=to_state_id,
                success=True,
                observation_id=(
                    self.current_observation.observation_id
                    if self.current_observation
                    else None
                ),
            )
        )
        if len(self.history) > self._max_history:
            del self.history[: len(self.history) - self._max_history]

    def add_goal(
        self,
        goal_id: str,
        title: str,
        *,
        goal_type: str = "GENERAL_EXPLORATION",
        priority: int = 1,
        target_ad_type: str | None = None,
        status: GoalStatus = "active",
    ) -> AgentGoal:
        for goal in self.active_goals:
            if goal.id == goal_id:
                return goal
        goal = AgentGoal(
            id=goal_id,
            title=title,
            status=status,
            goal_type=goal_type,
            priority=priority,
            target_ad_type=target_ad_type,
        )
        self.active_goals.append(goal)
        return goal

    def active_goal(self) -> AgentGoal | None:
        """Highest-priority active goal (ad goals prefer lower priority number)."""
        active = [g for g in self.active_goals if g.status in {"active", "pending"}]
        if not active:
            return None
        return sorted(active, key=lambda g: (g.priority, g.id))[0]

    def complete_goal(self, goal_id: str, *, reason: str | None = None) -> None:
        remaining: list[AgentGoal] = []
        for goal in self.active_goals:
            if goal.id == goal_id:
                goal.status = "completed"
                goal.reason = reason
                self.completed_goals.append(goal)
            else:
                remaining.append(goal)
        self.active_goals = remaining

    def fail_goal(self, goal_id: str, *, reason: str | None = None) -> None:
        remaining: list[AgentGoal] = []
        for goal in self.active_goals:
            if goal.id == goal_id:
                goal.status = "failed"
                goal.reason = reason
                self.failed_goals.append(goal)
            else:
                remaining.append(goal)
        self.active_goals = remaining

    def record_ad(self, ad: dict[str, Any]) -> None:
        if not ad or not ad.get("detected"):
            return
        # Deduplicate loosely by type+position+image_path.
        key = (
            ad.get("type"),
            ad.get("position"),
            ad.get("image_path") or ad.get("screenshot_id"),
        )
        for existing in self.discovered_ads:
            ek = (
                existing.get("type"),
                existing.get("position"),
                existing.get("image_path") or existing.get("screenshot_id"),
            )
            if ek == key:
                return
        payload = dict(ad)
        payload.pop("raw", None)
        self.discovered_ads.append(payload)

    def set_blocked(self, reason: str | None, *, hitl: dict[str, Any] | None = None) -> None:
        self.blocked = True
        self.blocked_reason = reason
        self.hitl_required = True
        if hitl is not None:
            self.hitl = dict(hitl)
        if self.status == AgentStatus.EXPLORING:
            self.status = AgentStatus.BLOCKED

    def clear_blocked(self) -> None:
        self.blocked = False
        self.blocked_reason = None
        self.hitl_required = False
        self.hitl = {"required": False}
        if self.status == AgentStatus.BLOCKED:
            self.status = AgentStatus.EXPLORING

    def mark_completed(self, *, reason: str | None = None) -> None:
        self.status = AgentStatus.COMPLETED
        self.stop_reason = reason
        self.clear_blocked()
        # Phase 12G: budget / exhaustion → mark remaining ad goals exhausted.
        budgetish = {
            "max_exploration_actions",
            "max_exploration_time",
            "target_meaningful_states_found",
            "budget_actions_exhausted",
            "budget_states_exhausted",
            "completed",
        }
        if reason in budgetish or (reason or "").startswith("budget_"):
            for goal in self.active_goals:
                if goal.goal_type == "AD_DISCOVERY" and goal.status in {"active", "pending"}:
                    if goal.status != "found":
                        goal.status = "exhausted"
                        goal.reason = reason or "exploration_exhausted"
                        self.bump_reliability("goals_exhausted")

    def mark_failed(self, *, reason: str | None = None) -> None:
        self.status = AgentStatus.FAILED
        self.stop_reason = reason

    def bump_reliability(self, key: str, amount: int = 1) -> None:
        """Increment a Phase 12H reliability counter (bounded keys only)."""
        if not self.reliability:
            self.reliability = {}
        if key not in self.reliability:
            self.reliability[key] = 0
        self.reliability[key] = int(self.reliability[key]) + int(amount)

    def record_recovery(
        self,
        *,
        decision: str,
        reason: str | None = None,
        action_id: str | None = None,
        action_key: str | None = None,
        state_id: str | None = None,
        attempt: int = 0,
    ) -> None:
        self.recovery_history.append(
            RecoveryRecord(
                timestamp=_utcnow_iso(),
                decision=decision,
                reason=reason,
                action_id=action_id,
                action_key=action_key,
                state_id=state_id or self.current_state_id,
                attempt=attempt,
            )
        )
        if len(self.recovery_history) > 100:
            del self.recovery_history[: len(self.recovery_history) - 100]
        # Phase 12H telemetry
        d = (decision or "").upper()
        if d == "RETRY":
            self.bump_reliability("retries")
        elif d == "BACKTRACK":
            self.bump_reliability("backtracks")
        elif d == "RELAUNCH":
            self.bump_reliability("relaunches")
        elif d == "PAUSE_HITL":
            self.bump_reliability("hitl_pauses")
        elif d == "WAIT":
            self.bump_reliability("waits")
        elif d == "SKIP":
            self.bump_reliability("skips")
        elif d == "STOP":
            self.bump_reliability("stops")

    def record_ai_decision(
        self,
        *,
        used: bool,
        meta: dict[str, Any] | None = None,
        planner_source: str | None = None,
    ) -> None:
        payload = dict(meta or {})
        source = planner_source or payload.get("planner_source")
        self.last_planner_source = source
        if used:
            self.ai_decision_count += 1
            self.last_ai_decision = {
                "key": payload.get("ai_key"),
                "reason": (payload.get("ai_reason") or "")[:200],
                "confidence": payload.get("ai_confidence"),
                "policy": payload.get("policy"),
                "planner_source": source or "AI",
            }
        else:
            if payload.get("fallback") or (source or "").startswith("DETERMINISTIC"):
                self.ai_fallback_count += 1
            if payload.get("ai_error") or payload.get("fallback"):
                self.bump_reliability("ai_failures")
            if payload:
                self.last_ai_decision = {
                    "ai_used": False,
                    "fallback": payload.get("fallback"),
                    "error": payload.get("ai_error") or payload.get("validation_error"),
                    "policy": payload.get("policy"),
                    "planner_source": source or "DETERMINISTIC",
                }

    def to_dict(self) -> dict[str, Any]:
        """Compact JSON-serializable summary (no ScreenStateRecord / image bytes)."""
        obs = self.current_observation
        return {
            "status": self.status.value if isinstance(self.status, AgentStatus) else str(self.status),
            "package_name": self.package_name,
            "job_id": self.job_id,
            "stop_reason": self.stop_reason,
            "current_observation_id": obs.observation_id if obs else None,
            "current_observation": obs.to_dict() if obs else None,
            "current_state_id": self.current_state_id,
            "current_activity": self.current_activity,
            "current_package": self.current_package,
            "current_depth": self.current_depth,
            "navigation": self.navigation_summary(),
            "discovered_screens": self.discovered_screens(),
            "discovered_ads": list(self.discovered_ads),
            "history": [h.to_dict() for h in self.history[-50:]],
            "history_count": len(self.history),
            "active_goals": [g.to_dict() for g in self.active_goals],
            "completed_goals": [g.to_dict() for g in self.completed_goals],
            "failed_goals": [g.to_dict() for g in self.failed_goals],
            "failed_actions": [f.to_dict() for f in self.failed_actions],
            "recovery_history": [r.to_dict() for r in self.recovery_history[-30:]],
            "blocked": self.blocked,
            "blocked_reason": self.blocked_reason,
            "hitl_required": self.hitl_required,
            "hitl": dict(self.hitl),
            "last_ai_decision": self.last_ai_decision,
            "ai_decision_count": self.ai_decision_count,
            "ai_fallback_count": self.ai_fallback_count,
            "last_planner_source": self.last_planner_source,
            "application_intelligence": (
                self.application_intelligence.to_ai_summary()
                if self.application_intelligence is not None
                and hasattr(self.application_intelligence, "to_ai_summary")
                else None
            ),
            "active_goal": (self.active_goal().to_dict() if self.active_goal() else None),
            "discovered_ad_placements": [
                d.to_dict() if hasattr(d, "to_dict") else d
                for d in self.discovered_ad_placements[-20:]
            ],
            "reliability": dict(self.reliability or {}),
            "spatial_regions": (
                self.region_memory.to_ai_regions()
                if self.region_memory is not None
                and hasattr(self.region_memory, "to_ai_regions")
                else []
            ),
            "budget": {
                "actions_used": self.actions_used,
                "max_actions": self.max_actions,
                "remaining_actions": self.remaining_actions,
                "states_discovered": self.states_discovered,
                "max_states": self.max_states,
                "remaining_states": self.remaining_states,
                "current_depth": self.current_depth,
                "max_depth": self.max_depth,
                "remaining_depth": self.remaining_depth,
            },
        }
