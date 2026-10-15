"""Phase 10: AI / LangGraph decision layer for exploration.

The AI may only choose among predefined UI actions. It cannot execute shell,
ADB, Python, or access credentials. HITL always has priority and is handled
outside this package by the existing explorer.
"""

from app.modules.ai_explorer.advisor import ExplorationAdvisor
from app.modules.ai_explorer.assist import (
    is_ai_assistable,
    plan_ad_dismiss_actions,
    plan_ai_assist_actions,
    try_ai_assist,
    try_dismiss_ads,
)
from app.modules.ai_explorer.context import AIPlanningContext, build_planning_context
from app.modules.ai_explorer.graph import run_decision_pipeline
from app.modules.ai_explorer.plan_enricher import (
    build_exploration_blueprint,
    enrich_blueprint,
)
from app.modules.ai_explorer.policy import should_invoke_ai
from app.modules.ai_explorer.schema import ALLOWED_ACTIONS, AIActionDecision
from app.modules.ai_explorer.validator import (
    ActionValidationError,
    parse_ai_decision,
    validate_and_map,
)

__all__ = [
    "ALLOWED_ACTIONS",
    "AIActionDecision",
    "AIPlanningContext",
    "ActionValidationError",
    "ExplorationAdvisor",
    "build_exploration_blueprint",
    "build_planning_context",
    "enrich_blueprint",
    "is_ai_assistable",
    "parse_ai_decision",
    "plan_ad_dismiss_actions",
    "plan_ai_assist_actions",
    "run_decision_pipeline",
    "should_invoke_ai",
    "try_ai_assist",
    "try_dismiss_ads",
    "validate_and_map",
]
