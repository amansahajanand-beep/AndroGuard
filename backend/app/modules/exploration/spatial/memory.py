"""Phase 12J — Persistent coverage memory for scroll regions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.modules.exploration.spatial.models import (
    DirectionCoverage,
    ExplorationRegion,
    SwipeDirection,
)


@dataclass
class RegionExplorationMemory:
    """Tracks explored directions / boundaries across observations (in-memory)."""

    regions: dict[str, ExplorationRegion] = field(default_factory=dict)
    # Stable fingerprint -> region_id so re-detected regions reuse coverage.
    fingerprints: dict[str, str] = field(default_factory=dict)

    def _fingerprint(self, region: ExplorationRegion) -> str:
        l, t, r, b = region.bounds
        return (
            f"{region.orientation.value}:"
            f"{region.region_type.value}:"
            f"{l // 48}:{t // 48}:{r // 48}:{b // 48}:"
            f"{(region.resource_id or '')[-40:]}"
        )

    def merge_region(self, region: ExplorationRegion) -> ExplorationRegion:
        fp = self._fingerprint(region)
        existing_id = self.fingerprints.get(fp)
        if existing_id and existing_id in self.regions:
            old = self.regions[existing_id]
            # Preserve coverage; refresh geometry / confidence from live detect.
            region.directions = old.directions
            region.last_gesture = old.last_gesture
            region.region_id = old.region_id
            self.regions[old.region_id] = region
            return region
        # Also match by exact id if planner reused it.
        if region.region_id in self.regions:
            old = self.regions[region.region_id]
            region.directions = old.directions
            region.last_gesture = old.last_gesture
            self.regions[region.region_id] = region
            self.fingerprints[fp] = region.region_id
            return region
        self.regions[region.region_id] = region
        self.fingerprints[fp] = region.region_id
        return region

    def total_gestures_for(self, region_id: str) -> int:
        reg = self.regions.get(region_id)
        if not reg:
            return 0
        return sum(d.gesture_count for d in reg.directions.values())

    def record_gesture(
        self,
        region_id: str,
        direction: SwipeDirection | str,
        *,
        outcome: str,
        state_id: str | None = None,
        no_change_limit: int = 2,
    ) -> None:
        reg = self.regions.get(region_id)
        if reg is None:
            return
        direction = str(direction)
        if direction not in reg.directions:
            reg.directions[direction] = DirectionCoverage()
        cov = reg.directions[direction]
        cov.gesture_count += 1
        cov.last_state_id = state_id
        reg.last_gesture = direction
        reg.last_observed_state_id = state_id
        outcome_u = (outcome or "").upper()
        if outcome_u in {"SUCCESS", "STATE_CHANGED", "NEW_CONTENT"}:
            cov.new_content_count += 1
            cov.no_change_count = 0
            cov.explored = True
        elif outcome_u == "BOUNDARY":
            cov.boundary_reached = True
            cov.explored = True
            cov.no_change_count += 1
        elif outcome_u in {"NO_CHANGE", "FAILED"}:
            cov.no_change_count += 1
            if cov.no_change_count >= no_change_limit:
                cov.boundary_reached = True
                cov.explored = True
        # UNKNOWN: count gesture but do not mark explored.

    def to_ai_regions(self, *, limit: int = 8) -> list[dict[str, Any]]:
        items = sorted(
            self.regions.values(),
            key=lambda r: (-r.confidence, r.region_id),
        )
        return [r.to_ai_summary() for r in items[:limit]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "regions": {k: v.to_dict() for k, v in self.regions.items()},
            "fingerprints": dict(self.fingerprints),
        }
