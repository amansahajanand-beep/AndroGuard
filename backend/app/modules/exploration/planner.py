"""Phase 12C — Deterministic Planner (decision only; no UI / ADB / LLM).

Wraps the existing :func:`plan_actions` / :class:`PlannedAction` pipeline.
Does not execute actions or mutate NavigationGraph.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from app.modules.exploration.action_planner import PlannedAction, plan_actions
from app.modules.exploration.agent_state import AgentState
from app.modules.exploration.log_tags import log_planner
from app.modules.exploration.prior_knowledge import ExplorationPrior
from app.modules.exploration.ui_element import UIElement

# Soft skip when the same action_key@state has failed this many times.
_DEFAULT_MAX_FAILURE_ATTEMPTS = 2


@dataclass
class PlanResult:
    """Outcome of one Planner decision."""

    planned_action: PlannedAction | None = None
    reason: str = ""
    candidate_count: int = 0
    stop: bool = False
    stop_reason: str | None = None
    source: str = "deterministic"  # deterministic | ai | recovery

    def to_dict(self) -> dict[str, Any]:
        return {
            "planned_action": (
                self.planned_action.to_dict() if self.planned_action else None
            ),
            "reason": self.reason,
            "candidate_count": self.candidate_count,
            "stop": self.stop,
            "stop_reason": self.stop_reason,
            "source": self.source,
        }


class ExplorationPlanner:
    """Select the next safe UI :class:`PlannedAction` from AgentState + candidates.

    Reuses :func:`plan_actions` for candidate generation. Never calls ADB/UI/LLM.
    """

    def __init__(self, *, max_failure_attempts: int = _DEFAULT_MAX_FAILURE_ATTEMPTS) -> None:
        self.max_failure_attempts = max(1, int(max_failure_attempts))

    def generate_candidates(
        self,
        elements: Sequence[UIElement],
        *,
        prior: ExplorationPrior | None = None,
        screen_size: tuple[int, int] | None = None,
        splash_wait_seconds: float = 1.5,
        wait_attempt: int = 0,
        activity: str | None = None,
        prefer_ad_triggers: bool = False,
    ) -> list[PlannedAction]:
        """Delegate to existing ActionPlanner (:func:`plan_actions`)."""
        return plan_actions(
            elements,
            prior=prior,
            screen_size=screen_size,
            splash_wait_seconds=splash_wait_seconds,
            wait_attempt=wait_attempt,
            activity=activity,
            prefer_ad_triggers=prefer_ad_triggers,
        )

    def select(
        self,
        candidates: Sequence[PlannedAction],
        *,
        agent_state: AgentState | None = None,
        visited_keys: set[str] | None = None,
        banned_keys: set[str] | None = None,
        source: str = "deterministic",
        reason: str | None = None,
    ) -> PlanResult:
        """Choose one validated action, or stop when none remain / budget exhausted."""
        visited_keys = visited_keys or set()
        banned_keys = banned_keys or set()
        raw_count = len(candidates)

        if agent_state is not None:
            if agent_state.remaining_actions <= 0:
                log_planner("stop reason=budget_actions_exhausted")
                return PlanResult(
                    stop=True,
                    stop_reason="budget_actions_exhausted",
                    candidate_count=raw_count,
                    reason="no remaining actions in budget",
                    source=source,
                )
            if agent_state.remaining_states <= 0:
                log_planner("stop reason=budget_states_exhausted")
                return PlanResult(
                    stop=True,
                    stop_reason="budget_states_exhausted",
                    candidate_count=raw_count,
                    reason="no remaining states in budget",
                    source=source,
                )

        failed_keys = self._repeated_failure_keys(agent_state)
        filtered: list[PlannedAction] = []
        for item in candidates:
            if item.key in visited_keys:
                continue
            if item.key in banned_keys:
                continue
            if item.key in failed_keys:
                continue
            filtered.append(item)

        if not filtered:
            log_planner(
                "stop reason=no_candidates raw=%s after_filter=0",
                raw_count,
            )
            return PlanResult(
                stop=True,
                stop_reason="no_candidates",
                candidate_count=raw_count,
                reason="no unexplored / non-failed candidates",
                source=source,
            )

        chosen = filtered[0]
        why = reason or f"first_unexplored priority={chosen.priority}"
        log_planner(
            "selected action=%s target=%s key=%s candidates=%s",
            chosen.kind,
            (chosen.label or "-")[:40],
            chosen.key[:80],
            len(filtered),
        )
        return PlanResult(
            planned_action=chosen,
            reason=why,
            candidate_count=len(filtered),
            stop=False,
            source=source,
        )

    def wrap_selected(
        self,
        planned: PlannedAction | None,
        *,
        candidate_count: int = 0,
        source: str = "ai",
        reason: str = "",
    ) -> PlanResult:
        """Adapt an externally chosen action (e.g. Phase 10 AI) into a PlanResult."""
        if planned is None:
            return PlanResult(
                stop=True,
                stop_reason="external_none",
                candidate_count=candidate_count,
                reason=reason or "external selection returned none",
                source=source,
            )
        if planned.kind == "stop":
            return PlanResult(
                planned_action=planned,
                stop=True,
                stop_reason=str((planned.meta or {}).get("reason") or "ai_stop"),
                candidate_count=candidate_count,
                reason=reason or "stop requested",
                source=source,
            )
        log_planner(
            "selected action=%s target=%s source=%s",
            planned.kind,
            (planned.label or "-")[:40],
            source,
        )
        return PlanResult(
            planned_action=planned,
            reason=reason or f"selected via {source}",
            candidate_count=candidate_count,
            source=source,
        )

    def _repeated_failure_keys(self, agent_state: AgentState | None) -> set[str]:
        if agent_state is None:
            return set()
        out: set[str] = set()
        for item in agent_state.failed_actions:
            if int(item.attempt_count) >= self.max_failure_attempts:
                out.add(item.action_key)
        return out
