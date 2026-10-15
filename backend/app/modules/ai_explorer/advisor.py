"""AI exploration advisor: goal-aware selection among deterministic candidates."""

from __future__ import annotations

import logging
from typing import Any, Sequence

from app.core.config import settings
from app.modules.ai_explorer.context import AIPlanningContext
from app.modules.ai_explorer.llm import AIAdvisorError, chat_json
from app.modules.ai_explorer.policy import should_invoke_ai
from app.modules.ai_explorer.prompts import SYSTEM_PROMPT, build_user_prompt
from app.modules.ai_explorer.schema import AIActionDecision
from app.modules.ai_explorer.validator import (
    ActionValidationError,
    candidate_summaries,
    map_decision_to_planned,
    parse_ai_decision,
)
from app.modules.exploration.action_planner import PlannedAction

logger = logging.getLogger(__name__)


def _log_ai(message: str, *args: object) -> None:
    logger.info("[AI-PLANNER] " + message, *args)


class ExplorationAdvisor:
    """Decide the next PlannedAction using AI only when policy says so.

    HITL must already have been handled by the caller. This class never talks
    to ADB / the shell / the filesystem / UIController.
    """

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        min_confidence: float | None = None,
    ) -> None:
        self.enabled = (
            bool(settings.ai_explorer_enabled) if enabled is None else bool(enabled)
        )
        self.min_confidence = (
            float(settings.ai_explorer_min_confidence)
            if min_confidence is None
            else float(min_confidence)
        )

    def choose(
        self,
        candidates: Sequence[PlannedAction],
        *,
        activity: str | None = None,
        package_name: str | None = None,
        visited_keys: Sequence[str] | None = None,
        stagnation_count: int = 0,
        force: bool = False,
        plan_notes: str | None = None,
        planning_context: AIPlanningContext | dict[str, Any] | None = None,
    ) -> tuple[PlannedAction | None, dict[str, Any]]:
        """Return (action, meta). On any AI failure, returns (None, meta) so
        the caller falls back to deterministic ordering.
        """
        meta: dict[str, Any] = {
            "ai_used": False,
            "ai_reason": None,
            "policy": None,
            "planner_source": None,
        }
        if not candidates and not force:
            return None, meta

        use_ai, policy_reason = should_invoke_ai(
            candidates,
            stagnation_count=stagnation_count,
            force=force,
            min_candidates=int(settings.ai_explorer_min_candidates or 3),
        )
        meta["policy"] = policy_reason
        if not self.enabled or not use_ai:
            meta["planner_source"] = "DETERMINISTIC"
            return None, meta

        ctx_dict: dict[str, Any] = {}
        if isinstance(planning_context, AIPlanningContext):
            ctx_dict = planning_context.to_dict()
        elif isinstance(planning_context, dict):
            ctx_dict = dict(planning_context)

        goal = (ctx_dict.get("goal") or {}).get("goal_type") or "GENERAL_EXPLORATION"
        _log_ai("Goal=%s candidates=%s", goal, len(candidates))

        summaries = candidate_summaries(candidates)
        user_prompt = build_user_prompt(
            activity=activity or ctx_dict.get("current_activity"),
            package_name=package_name or ctx_dict.get("package_name"),
            candidates=summaries,
            visited_summary=list(visited_keys or [])[:30],
            notes=policy_reason,
            plan_notes=plan_notes,
            planning_context=ctx_dict,
        )
        try:
            raw = chat_json(system=SYSTEM_PROMPT, user=user_prompt)
            decision = parse_ai_decision(raw)
            planned = self._accept_decision(decision, candidates, meta)
            return planned, meta
        except (AIAdvisorError, ActionValidationError) as exc:
            _log_ai("Invalid AI decision; deterministic fallback (%s)", exc)
            meta["ai_error"] = str(exc)
            meta["fallback"] = "deterministic_after_ai_failure"
            meta["planner_source"] = "DETERMINISTIC_FALLBACK"
            return None, meta
        except Exception as exc:
            _log_ai("LLM unavailable; deterministic fallback (%s)", type(exc).__name__)
            meta["ai_error"] = type(exc).__name__
            meta["fallback"] = "deterministic_after_ai_failure"
            meta["planner_source"] = "DETERMINISTIC_FALLBACK"
            return None, meta

    def _accept_decision(
        self,
        decision: AIActionDecision,
        candidates: Sequence[PlannedAction],
        meta: dict[str, Any],
    ) -> PlannedAction:
        if decision.confidence is not None and decision.confidence < self.min_confidence:
            raise ActionValidationError(
                f"low confidence {decision.confidence:.2f} < {self.min_confidence:.2f}"
            )
        planned = map_decision_to_planned(decision, candidates)
        meta["ai_used"] = True
        meta["ai_reason"] = decision.reason
        meta["ai_key"] = planned.key
        meta["ai_confidence"] = decision.confidence
        meta["planner_source"] = "AI"
        _log_ai(
            "Selected action=%s target=%s confidence=%s",
            decision.action,
            (decision.target or planned.key)[:80],
            decision.confidence if decision.confidence is not None else "n/a",
        )
        if decision.reason:
            _log_ai("Reason=%s", decision.reason[:160])
        return planned
