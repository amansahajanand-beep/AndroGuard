"""LangGraph decision layer for exploration actions (Phase 10).

This graph ONLY selects among deterministic candidate actions. It never
executes ADB/shell/Python and never touches credentials.

Nodes mirror the decision portion of the Phase 10 flowchart:

    GENERATE_ACTIONS → CHECK_VISITED → AI_DECISION? → VALIDATE_ACTION → DONE

HITL detection / execute / capture remain in the existing explorer (HITL
always runs before this graph is consulted).
"""

from __future__ import annotations

import logging
from typing import Any, Sequence, TypedDict

from app.core.config import settings
from app.modules.ai_explorer.advisor import ExplorationAdvisor
from app.modules.ai_explorer.policy import should_invoke_ai
from app.modules.ai_explorer.validator import ActionValidationError, validate_and_map
from app.modules.exploration.action_planner import PlannedAction

logger = logging.getLogger(__name__)


class DecisionState(TypedDict, total=False):
    candidates: list[PlannedAction]
    unexplored: list[PlannedAction]
    visited_keys: list[str]
    activity: str | None
    package_name: str | None
    stagnation_count: int
    force_ai: bool
    policy_reason: str
    use_ai: bool
    raw_ai: str | None
    selected: PlannedAction | None
    error: str | None
    meta: dict[str, Any]


def _check_visited(state: DecisionState) -> DecisionState:
    visited = set(state.get("visited_keys") or [])
    candidates = list(state.get("candidates") or [])
    unexplored = [item for item in candidates if item.key not in visited]
    out = dict(state)
    out["unexplored"] = unexplored
    out["meta"] = dict(state.get("meta") or {})
    out["meta"]["unexplored_count"] = len(unexplored)
    return out  # type: ignore[return-value]


def _policy(state: DecisionState) -> DecisionState:
    unexplored = list(state.get("unexplored") or [])
    use_ai, reason = should_invoke_ai(
        unexplored,
        stagnation_count=int(state.get("stagnation_count") or 0),
        force=bool(state.get("force_ai")),
        min_candidates=int(settings.ai_explorer_min_candidates or 3),
    )
    if not settings.ai_explorer_enabled:
        use_ai = False
        reason = "ai_disabled"
    out = dict(state)
    out["use_ai"] = use_ai
    out["policy_reason"] = reason
    meta = dict(out.get("meta") or {})
    meta["policy"] = reason
    meta["use_ai"] = use_ai
    out["meta"] = meta
    return out  # type: ignore[return-value]


def _ai_decision(state: DecisionState) -> DecisionState:
    out = dict(state)
    meta = dict(out.get("meta") or {})
    if not state.get("use_ai"):
        # Deterministic: first unexplored candidate.
        unexplored = list(state.get("unexplored") or [])
        out["selected"] = unexplored[0] if unexplored else None
        meta["ai_used"] = False
        out["meta"] = meta
        return out  # type: ignore[return-value]

    advisor = ExplorationAdvisor(enabled=True)
    planned, adv_meta = advisor.choose(
        list(state.get("unexplored") or []),
        activity=state.get("activity"),
        package_name=state.get("package_name"),
        visited_keys=state.get("visited_keys") or [],
        stagnation_count=int(state.get("stagnation_count") or 0),
        force=True,
    )
    meta.update(adv_meta)
    if planned is not None:
        out["selected"] = planned
        out["meta"] = meta
        return out  # type: ignore[return-value]

    # Fallback deterministic.
    unexplored = list(state.get("unexplored") or [])
    out["selected"] = unexplored[0] if unexplored else None
    meta["ai_used"] = False
    meta["fallback"] = "deterministic_after_ai_failure"
    out["meta"] = meta
    return out  # type: ignore[return-value]


def _validate(state: DecisionState) -> DecisionState:
    """Final safety gate — selected action must be allow-listed / candidate-bound."""
    out = dict(state)
    selected = state.get("selected")
    if selected is None:
        return out  # type: ignore[return-value]
    # Re-validate AI-sourced selections through the schema mapper when possible.
    if (selected.meta or {}).get("source") == "ai":
        try:
            decision_payload = {
                "action": selected.kind if selected.kind != "menu" else "open_menu",
                "target": selected.key if selected.kind == "tap" else selected.key,
                "reason": (selected.meta or {}).get("reason") or "",
            }
            # Normalize swipe kinds already match allow-list.
            if decision_payload["action"] == "menu":
                decision_payload["action"] = "open_menu"
            planned = validate_and_map(decision_payload, list(state.get("unexplored") or []))
            out["selected"] = planned
        except ActionValidationError as exc:
            logger.info("AI selection failed final validation: %s", exc)
            unexplored = list(state.get("unexplored") or [])
            out["selected"] = unexplored[0] if unexplored else None
            meta = dict(out.get("meta") or {})
            meta["validation_error"] = str(exc)
            meta["ai_used"] = False
            out["meta"] = meta
            out["error"] = str(exc)
    return out  # type: ignore[return-value]


def run_decision_pipeline(
    candidates: Sequence[PlannedAction],
    *,
    visited_keys: Sequence[str] | None = None,
    activity: str | None = None,
    package_name: str | None = None,
    stagnation_count: int = 0,
    force_ai: bool = False,
) -> tuple[PlannedAction | None, dict[str, Any]]:
    """Execute the decision graph (LangGraph when available, else sequential)."""
    initial: DecisionState = {
        "candidates": list(candidates),
        "visited_keys": list(visited_keys or []),
        "activity": activity,
        "package_name": package_name,
        "stagnation_count": stagnation_count,
        "force_ai": force_ai,
        "meta": {},
    }

    graph = _build_langgraph()
    if graph is not None:
        try:
            final = graph.invoke(initial)
            selected = final.get("selected")
            meta = dict(final.get("meta") or {})
            return selected, meta
        except Exception:
            logger.warning("LangGraph decision failed; using sequential pipeline", exc_info=True)

    state = _check_visited(initial)
    state = _policy(state)
    state = _ai_decision(state)
    state = _validate(state)
    return state.get("selected"), dict(state.get("meta") or {})


def _build_langgraph() -> Any | None:
    if not settings.ai_explorer_enabled:
        return None
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError:
        logger.debug("langgraph not installed — using sequential decision pipeline")
        return None

    graph = StateGraph(DecisionState)
    graph.add_node("check_visited", _check_visited)
    graph.add_node("policy", _policy)
    graph.add_node("ai_decision", _ai_decision)
    graph.add_node("validate_action", _validate)
    graph.add_edge(START, "check_visited")
    graph.add_edge("check_visited", "policy")
    graph.add_edge("policy", "ai_decision")
    graph.add_edge("ai_decision", "validate_action")
    graph.add_edge("validate_action", END)
    return graph.compile()
