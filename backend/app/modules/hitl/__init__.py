"""Phase 7: Human-in-the-Loop (HITL) for emulator exploration.

When the app or Android system requires a human decision (terms, privacy,
permissions, default-app, login, CAPTCHA, …), exploration pauses, the job
enters ``waiting_for_human``, and a human acts in the emulator. Continue /
Skip / Stop resume or end the *same* device session — no emulator restart,
no APK reinstall, no exploration restart from scratch.
"""

from app.modules.hitl.hitl_state import ExplorationCheckpoint
from app.modules.hitl.intervention_detector import InterventionDetector
from app.modules.hitl.intervention_manager import (
    InterventionManager,
    get_manager,
    register_manager,
    unregister_manager,
)
from app.modules.hitl.intervention_store import InterventionStore, get_intervention_store
from app.modules.hitl.intervention_types import (
    DetectionResult,
    HumanDecision,
    Intervention,
    InterventionStatus,
    InterventionType,
)

__all__ = [
    "DetectionResult",
    "ExplorationCheckpoint",
    "HumanDecision",
    "Intervention",
    "InterventionDetector",
    "InterventionManager",
    "InterventionStatus",
    "InterventionStore",
    "InterventionType",
    "get_intervention_store",
    "get_manager",
    "register_manager",
    "unregister_manager",
]
