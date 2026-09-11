"""AI exploration advisor: selects among deterministic candidates only."""

from __future__ import annotations

import logging
from typing import Any, Sequence

from app.core.config import settings
from app.modules.ai_explorer.llm import AIAdvisorError, chat_json
from app.modules.ai_explorer.policy import should_invoke_ai
from app.modules.ai_explorer.prompts import SYSTEM_PROMPT, build_user_prompt
from app.modules.ai_explorer.validator import (
    ActionValidationError,
    candidate_summaries,
    validate_and_map,
)
from app.modules.exploration.action_planner import PlannedAction

logger = logging.getLogger(__name__)


class ExplorationAdvisor:
    """Decide the next PlannedAction using AI only when policy says so.

    HITL must already have been handled by the caller. This class never talks
    to ADB / the shell / the filesystem.
    """

    def __init__(self, *, enabled: bool | None = None) -> None:
        self.enabled = (
            bool(settings.ai_explorer_enabled) if enabled is None else bool(enabled)
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
    ) -> tuple[PlannedAction | None, dict[str, Any]]:
        """Return (action, meta). On any AI failure, returns (None, meta) so
        the caller falls back to deterministic ordering.
        """
        meta: dict[str, Any] = {"ai_used": False, "ai_reason": None, "policy": None}
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
            return None, meta

        summaries = candidate_summaries(candidates)
        user_prompt = build_user_prompt(
            activity=activity,
            package_name=package_name,
            candidates=summaries,
            visited_summary=list(visited_keys or [])[:30],
            notes=policy_reason,
        )
        try:
            raw = chat_json(system=SYSTEM_PROMPT, user=user_prompt)
            planned = validate_and_map(raw, candidates)
            meta["ai_used"] = True
            meta["ai_reason"] = (planned.meta or {}).get("reason")
            meta["ai_key"] = planned.key
            return planned, meta
        except (AIAdvisorError, ActionValidationError) as exc:
            logger.info("AI advisor rejected/fallback: %s", exc)
            meta["ai_error"] = str(exc)
            return None, meta
        except Exception as exc:
            logger.warning("AI advisor unexpected failure: %s", type(exc).__name__)
            meta["ai_error"] = type(exc).__name__
            return None, meta
