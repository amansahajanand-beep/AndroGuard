"""Phase 12G — Goal-driven ad exploration (deterministic goals + evaluation).

Static ApplicationIntelligence creates hypotheses (goals).
Runtime AdPlacementDetector / Observation.detected_ads confirm discovery.
AI may only select ActionPlanner candidates — never invoke SDK methods.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Sequence

from app.core.config import settings
from app.modules.exploration.agent_state import AgentGoal, AgentState
from app.modules.exploration.observation import Observation

logger = logging.getLogger(__name__)

AdTarget = Literal[
    "ANY",
    "BANNER",
    "INTERSTITIAL",
    "REWARDED",
    "NATIVE",
    "APP_OPEN",
]

GoalEvalOutcome = Literal[
    "GOAL_NOT_MET",
    "GOAL_PROGRESS",
    "GOAL_FOUND",
    "GOAL_BLOCKED",
]

DiscoveryMode = Literal["first_match", "discover_all"]

_FORMAT_PRIORITY: dict[str, int] = {
    "REWARDED": 10,
    "INTERSTITIAL": 20,
    "APP_OPEN": 30,
    "NATIVE": 40,
    "BANNER": 50,
    "ANY": 60,
}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clamp(value: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, v))


def normalize_ad_type(raw: str | None) -> str:
    text = (raw or "").strip().upper().replace("-", "_").replace(" ", "_")
    aliases = {
        "REWARDED_VIDEO": "REWARDED",
        "REWARD": "REWARDED",
        "FULLSCREEN": "INTERSTITIAL",
        "APPOPEN": "APP_OPEN",
        "APP_OPEN_AD": "APP_OPEN",
    }
    text = aliases.get(text, text)
    if text in {"BANNER", "INTERSTITIAL", "REWARDED", "NATIVE", "APP_OPEN", "ANY", "UNKNOWN"}:
        return text
    return "UNKNOWN"


@dataclass
class AdPlacementDiscovery:
    """One unique runtime ad placement with optional trigger path."""

    placement_id: str
    ad_type: str
    state_id: str | None = None
    activity: str | None = None
    screenshot: str | None = None
    detection: dict[str, Any] = field(default_factory=dict)
    trigger_path: list[dict[str, Any]] = field(default_factory=list)
    first_seen: str = field(default_factory=_utcnow_iso)
    confidence: float = 0.0
    goal_id: str | None = None
    uniqueness_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "placement_id": self.placement_id,
            "ad_type": self.ad_type,
            "state_id": self.state_id,
            "activity": self.activity,
            "screenshot": self.screenshot,
            "detection": dict(self.detection),
            "trigger_path": list(self.trigger_path),
            "first_seen": self.first_seen,
            "confidence": _clamp(self.confidence),
            "goal_id": self.goal_id,
            "uniqueness_key": self.uniqueness_key,
        }


@dataclass
class GoalEvaluation:
    outcome: GoalEvalOutcome
    goal_id: str | None = None
    reason: str = ""
    matched_ad: dict[str, Any] | None = None
    discovery: AdPlacementDiscovery | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "goal_id": self.goal_id,
            "reason": self.reason,
            "matched_ad": self.matched_ad,
            "discovery": self.discovery.to_dict() if self.discovery else None,
        }


class AdGoalGenerator:
    """Deterministic goals from ApplicationIntelligence (no LLM)."""

    def generate(
        self,
        application_intelligence: Any | None,
        *,
        include_any: bool = False,
        explicit_targets: Sequence[str] | None = None,
    ) -> list[AgentGoal]:
        goals: list[AgentGoal] = []
        targets: list[tuple[str, float]] = []

        if explicit_targets:
            for t in explicit_targets:
                nt = normalize_ad_type(t)
                if nt and nt != "UNKNOWN":
                    targets.append((nt, 0.99))
        elif application_intelligence is not None:
            ads = getattr(application_intelligence, "ads", None)
            if isinstance(ads, dict):
                formats = ads.get("ad_formats") or []
            elif hasattr(application_intelligence, "to_dict"):
                formats = (application_intelligence.to_dict().get("ads") or {}).get(
                    "ad_formats"
                ) or []
            else:
                formats = []
            for item in formats:
                if not isinstance(item, dict):
                    continue
                fmt = normalize_ad_type(item.get("format"))
                if fmt in {"UNKNOWN", ""}:
                    continue
                conf = _clamp(float(item.get("confidence") or 0.5))
                targets.append((fmt, conf))

        # Deduplicate keeping highest confidence.
        best: dict[str, float] = {}
        for fmt, conf in targets:
            best[fmt] = max(conf, best.get(fmt, 0.0))

        if not best and include_any:
            best["ANY"] = 0.5

        for fmt, conf in sorted(
            best.items(),
            key=lambda kv: (_FORMAT_PRIORITY.get(kv[0], 100), -kv[1]),
        ):
            priority = _FORMAT_PRIORITY.get(fmt, 80)
            # Stronger static confidence → slightly higher priority (lower number).
            if conf >= 0.9:
                priority = max(1, priority - 5)
            goals.append(
                AgentGoal(
                    id=f"ad_{fmt.lower()}",
                    title=f"Find {fmt.lower().replace('_', ' ')} advertisement",
                    status="active",
                    goal_type="AD_DISCOVERY",
                    priority=priority,
                    target_ad_type=fmt,
                    reason=f"static_signal confidence={conf:.2f}",
                )
            )
            logger.info(
                "[AD-GOAL] generated target=%s priority=%s confidence=%.2f",
                fmt,
                priority,
                conf,
            )
        return goals


class GoalEvaluator:
    """Deterministic evaluation: runtime ads confirm goals (never static alone)."""

    def __init__(self, *, min_confidence: float | None = None) -> None:
        self.min_confidence = float(
            min_confidence
            if min_confidence is not None
            else getattr(settings, "ad_detection_min_confidence", 0.45) or 0.45
        )

    def evaluate(
        self,
        goal: AgentGoal | None,
        *,
        observation: Observation | None,
        agent_state: AgentState | None = None,
        discovery_mode: DiscoveryMode | None = None,
    ) -> GoalEvaluation:
        if goal is None:
            return GoalEvaluation(outcome="GOAL_NOT_MET", reason="no_goal")
        if goal.goal_type != "AD_DISCOVERY":
            return GoalEvaluation(
                outcome="GOAL_NOT_MET",
                goal_id=goal.id,
                reason="not_ad_goal",
            )
        if goal.status in {"found", "completed", "exhausted", "failed"}:
            return GoalEvaluation(
                outcome="GOAL_FOUND" if goal.status in {"found", "completed"} else "GOAL_NOT_MET",
                goal_id=goal.id,
                reason=f"already_{goal.status}",
            )

        if observation is not None and observation.hitl_required:
            return GoalEvaluation(
                outcome="GOAL_BLOCKED",
                goal_id=goal.id,
                reason="hitl_required",
            )

        target = normalize_ad_type(goal.target_ad_type or "ANY")
        runtime_ads = list((observation.detected_ads if observation else None) or [])
        matched = self._match_runtime_ad(runtime_ads, target)
        if matched is None:
            # Progress: recent successful transition while pursuing ad goal.
            progress = False
            if agent_state is not None:
                for entry in reversed(agent_state.history[-5:]):
                    if entry.action_kind == "transition" and entry.next_state_id:
                        progress = True
                        break
                    if (
                        entry.success
                        and entry.next_state_id
                        and entry.state_id
                        and entry.next_state_id != entry.state_id
                    ):
                        progress = True
                        break
            return GoalEvaluation(
                outcome="GOAL_PROGRESS" if progress else "GOAL_NOT_MET",
                goal_id=goal.id,
                reason="no_runtime_ad_match",
            )

        conf = _clamp(float(matched.get("confidence") or 0.0))
        if conf < self.min_confidence:
            return GoalEvaluation(
                outcome="GOAL_PROGRESS",
                goal_id=goal.id,
                reason=f"low_confidence:{conf:.2f}",
                matched_ad=matched,
            )

        path = self._trigger_path(agent_state)
        uniq = self._uniqueness_key(matched, observation)
        placement_id = f"plc_{uniq[:16]}" if uniq else f"plc_{_utcnow_iso()}"
        discovery = AdPlacementDiscovery(
            placement_id=placement_id,
            ad_type=normalize_ad_type(matched.get("type")),
            state_id=observation.state_id if observation else None,
            activity=observation.activity if observation else None,
            screenshot=(
                observation.screenshot_path or observation.screenshot_url
                if observation
                else None
            ),
            detection=dict(matched),
            trigger_path=path,
            confidence=conf,
            goal_id=goal.id,
            uniqueness_key=uniq,
        )
        mode = discovery_mode or _configured_discovery_mode()
        logger.info(
            "[AD-GOAL] FOUND target=%s type=%s confidence=%.2f mode=%s",
            target,
            discovery.ad_type,
            conf,
            mode,
        )
        return GoalEvaluation(
            outcome="GOAL_FOUND",
            goal_id=goal.id,
            reason="runtime_ad_confirmed",
            matched_ad=matched,
            discovery=discovery,
        )

    def _match_runtime_ad(
        self, ads: list[dict[str, Any]], target: str
    ) -> dict[str, Any] | None:
        best: dict[str, Any] | None = None
        best_conf = -1.0
        for ad in ads:
            if not isinstance(ad, dict) or not ad.get("detected"):
                continue
            ad_type = normalize_ad_type(ad.get("type"))
            if target != "ANY" and ad_type != target:
                continue
            conf = _clamp(float(ad.get("confidence") or 0.0))
            if conf > best_conf:
                best = ad
                best_conf = conf
        return best

    def _trigger_path(self, agent_state: AgentState | None) -> list[dict[str, Any]]:
        if agent_state is None:
            return []
        path: list[dict[str, Any]] = []
        for entry in agent_state.history[-20:]:
            if entry.action_kind in {None, "transition"}:
                continue
            path.append(
                {
                    "action": entry.action_kind,
                    "target": (entry.action_label or entry.action_key or "")[:80],
                    "state_id": entry.state_id,
                    "next_state_id": entry.next_state_id,
                    "success": entry.success,
                }
            )
        return path[-12:]

    def _uniqueness_key(
        self, ad: dict[str, Any], observation: Observation | None
    ) -> str:
        parts = [
            normalize_ad_type(ad.get("type")),
            str(ad.get("position") or ""),
            str((observation.state_id if observation else None) or ""),
            str((observation.activity if observation else None) or ""),
            str(ad.get("image_path") or (observation.screenshot_id if observation else "") or ""),
        ]
        bbox = ad.get("bounding_box") or ad.get("relative_bbox") or ""
        parts.append(str(bbox))
        digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
        return digest


def apply_goal_evaluation(
    agent_state: AgentState,
    evaluation: GoalEvaluation,
    *,
    discovery_mode: DiscoveryMode | None = None,
) -> None:
    """Update AgentState goals / discoveries from an evaluation result."""
    if evaluation.outcome == "GOAL_BLOCKED":
        goal = _find_goal(agent_state, evaluation.goal_id)
        if goal is not None and goal.status == "active":
            goal.status = "blocked"
            goal.reason = evaluation.reason
        return

    if evaluation.outcome != "GOAL_FOUND" or evaluation.discovery is None:
        return

    discovery = evaluation.discovery
    # Deduplicate placements.
    existing_keys = {
        d.uniqueness_key for d in agent_state.discovered_ad_placements if d.uniqueness_key
    }
    if discovery.uniqueness_key and discovery.uniqueness_key in existing_keys:
        agent_state.bump_reliability("duplicate_discoveries_suppressed")
        return
    agent_state.discovered_ad_placements.append(discovery)
    if len(agent_state.discovered_ad_placements) > 50:
        del agent_state.discovered_ad_placements[
            : len(agent_state.discovered_ad_placements) - 50
        ]

    mode = discovery_mode or _configured_discovery_mode()
    goal = _find_goal(agent_state, evaluation.goal_id)
    if goal is None:
        return
    if mode == "first_match":
        goal.status = "found"
        goal.reason = evaluation.reason
        agent_state.bump_reliability("goals_found")
        # Move to completed_goals list if still active.
        if goal in agent_state.active_goals:
            agent_state.active_goals = [g for g in agent_state.active_goals if g.id != goal.id]
            agent_state.completed_goals.append(goal)
        # Activate next pending AD_DISCOVERY goal if any.
        _activate_next_ad_goal(agent_state)
    else:
        # discover_all: record placement but keep goal active until exhausted.
        goal.reason = f"found_placement:{discovery.placement_id}"
        agent_state.bump_reliability("goals_found")


def seed_ad_goals_from_intelligence(
    agent_state: AgentState,
    application_intelligence: Any | None,
) -> list[AgentGoal]:
    """Replace/augment AD_DISCOVERY seed goals using static intelligence."""
    generated = AdGoalGenerator().generate(application_intelligence)
    if not generated:
        return []
    # Remove generic discover_ad_placements seed if present; keep specific targets.
    agent_state.active_goals = [
        g
        for g in agent_state.active_goals
        if not (g.goal_type == "AD_DISCOVERY" and g.id == "discover_ad_placements")
    ]
    existing_ids = {g.id for g in agent_state.active_goals}
    added: list[AgentGoal] = []
    for goal in generated:
        if goal.id in existing_ids:
            continue
        agent_state.active_goals.append(goal)
        added.append(goal)
    # Sort so highest-priority ad goals come first among actives.
    agent_state.active_goals.sort(key=lambda g: (g.priority, g.id))
    return added


def active_ad_goal(agent_state: AgentState | None) -> AgentGoal | None:
    if agent_state is None:
        return None
    ad_goals = [
        g
        for g in agent_state.active_goals
        if g.goal_type == "AD_DISCOVERY" and g.status in {"active", "pending"}
    ]
    if not ad_goals:
        return None
    return sorted(ad_goals, key=lambda g: (g.priority, g.id))[0]


def fingerprints_to_ad_results(
    fingerprints: Sequence[Any],
) -> list[dict[str, Any]]:
    """Convert AdPlacementFingerprint objects into Observation ad_results dicts."""
    out: list[dict[str, Any]] = []
    for fp in fingerprints or []:
        try:
            ad_type = normalize_ad_type(getattr(fp, "ad_type", None)).lower()
            if ad_type == "unknown":
                ad_type = "unknown"
            # Map APP_OPEN to unknown for Phase 6 AdTypeName if needed — keep string.
            if ad_type == "app_open":
                type_name = "unknown"
                evidence_extra = ["format:app_open"]
            else:
                type_name = ad_type if ad_type in {
                    "banner", "native", "interstitial", "rewarded", "unknown"
                } else "unknown"
                evidence_extra = []
            evidence = list(getattr(fp, "evidence", ()) or [])
            evidence.extend(evidence_extra)
            # UI-hierarchy heuristic confidence (not vision).
            conf = 0.78 if evidence else 0.65
            if any("reward" in str(e).lower() for e in evidence):
                conf = 0.82
            if any("interstitial" in str(e).lower() or "fullscreen" in str(e).lower() for e in evidence):
                conf = max(conf, 0.80)
            out.append(
                {
                    "detected": True,
                    "type": type_name if type_name != "unknown" or ad_type == "unknown" else ad_type,
                    "confidence": conf,
                    "position": getattr(fp, "position", "unknown"),
                    "provider": "ui_hierarchy_heuristic",
                    "image_path": getattr(fp, "screenshot_path", None),
                    "evidence": evidence[:12],
                    "relative_bbox": list(getattr(fp, "relative_bbox", ()) or []),
                    "uniqueness_key": getattr(fp, "uniqueness_key", None),
                    "visual_state_id": getattr(fp, "visual_state_id", None),
                    "page": getattr(fp, "page", None),
                }
            )
        except Exception:
            continue
    return out


def _find_goal(agent_state: AgentState, goal_id: str | None) -> AgentGoal | None:
    if not goal_id:
        return None
    for g in agent_state.active_goals + agent_state.completed_goals + agent_state.failed_goals:
        if g.id == goal_id:
            return g
    return None


def _activate_next_ad_goal(agent_state: AgentState) -> None:
    pending = [
        g
        for g in agent_state.active_goals
        if g.goal_type == "AD_DISCOVERY" and g.status == "pending"
    ]
    if not pending:
        return
    nxt = sorted(pending, key=lambda g: (g.priority, g.id))[0]
    nxt.status = "active"


def _configured_discovery_mode() -> DiscoveryMode:
    raw = str(
        getattr(settings, "exploration_ad_discovery_mode", None) or "discover_all"
    ).strip().lower()
    if raw in {"first_match", "first", "first-match"}:
        return "first_match"
    return "discover_all"


def goal_context_for_ai(agent_state: AgentState | None) -> dict[str, Any] | None:
    goal = active_ad_goal(agent_state)
    if goal is None:
        return None
    return {
        "type": goal.goal_type,
        "target": goal.target_ad_type or "ANY",
        "status": (goal.status or "active").upper(),
        "goal_id": goal.id,
        "title": goal.title,
        "priority": goal.priority,
        "discoveries": len(
            [
                d
                for d in (agent_state.discovered_ad_placements if agent_state else [])
                if d.goal_id == goal.id
            ]
        ),
        "mode": _configured_discovery_mode(),
        "note": "STATIC signals are hypotheses; runtime detection confirms FOUND",
    }
