"""Phase 10: AI / LangGraph decision layer for exploration.

The AI may only choose among predefined UI actions. It cannot execute shell,
ADB, Python, or access credentials. HITL always has priority and is handled
outside this package by the existing explorer.
"""

from app.modules.ai_explorer.advisor import ExplorationAdvisor
from app.modules.ai_explorer.graph import run_decision_pipeline
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
    "ActionValidationError",
    "ExplorationAdvisor",
    "parse_ai_decision",
    "run_decision_pipeline",
    "should_invoke_ai",
    "validate_and_map",
]
