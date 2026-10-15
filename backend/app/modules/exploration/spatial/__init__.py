"""Phase 12J — Spatial understanding & human-like gesture exploration."""

from __future__ import annotations

from app.modules.exploration.spatial.gesture_planner import GesturePlanner, plan_gesture_actions
from app.modules.exploration.spatial.gesture_verifier import (
    GestureVerifyOutcome,
    GestureVerifyResult,
    verify_gesture,
)
from app.modules.exploration.spatial.memory import RegionExplorationMemory
from app.modules.exploration.spatial.models import (
    DirectionCoverage,
    ExplorationRegion,
    RegionType,
    ScrollOrientation,
)
from app.modules.exploration.spatial.spatial_analyzer import SpatialAnalyzer, analyze_regions

__all__ = [
    "DirectionCoverage",
    "ExplorationRegion",
    "GesturePlanner",
    "GestureVerifyOutcome",
    "GestureVerifyResult",
    "RegionExplorationMemory",
    "RegionType",
    "ScrollOrientation",
    "SpatialAnalyzer",
    "analyze_regions",
    "plan_gesture_actions",
    "verify_gesture",
]
