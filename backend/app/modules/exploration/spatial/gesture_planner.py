"""Phase 12J — Region-aware gesture candidate generation."""

from __future__ import annotations

from typing import Any, Sequence

from app.modules.exploration.action_planner import PlannedAction
from app.modules.exploration.actions import SwipeAction
from app.modules.exploration.log_tags import log_gesture
from app.modules.exploration.spatial.memory import RegionExplorationMemory
from app.modules.exploration.spatial.models import (
    ExplorationRegion,
    RegionType,
    ScrollOrientation,
    SwipeDirection,
)


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def gesture_points_for_region(
    region: ExplorationRegion,
    direction: SwipeDirection,
    *,
    edge_margin: float = 0.15,
    distance_ratio: float = 0.7,
    screen_size: tuple[int, int] | None = None,
) -> tuple[tuple[int, int], tuple[int, int]]:
    """Compute start/end points inside ``region`` with safe insets."""
    l, t, r, b = region.bounds
    w = max(1, r - l)
    h = max(1, b - t)
    margin = max(0.08, min(0.35, float(edge_margin)))
    dist = max(0.4, min(0.9, float(distance_ratio)))

    inset_x = max(8, int(w * margin))
    inset_y = max(8, int(h * margin))
    cx = l + w // 2
    cy = t + h // 2

    # Keep points on-screen when screen_size is known.
    def _fit(x: int, y: int) -> tuple[int, int]:
        if not screen_size:
            return (x, y)
        sw, sh = screen_size
        return (_clamp(x, 1, max(1, sw - 2)), _clamp(y, 1, max(1, sh - 2)))

    if direction == "up":
        y1 = b - inset_y
        y2 = t + inset_y
        # Shorten travel to distance_ratio of region height.
        travel = int((y1 - y2) * dist)
        y2 = y1 - max(inset_y, travel)
        return _fit(cx, y1), _fit(cx, y2)
    if direction == "down":
        y1 = t + inset_y
        y2 = b - inset_y
        travel = int((y2 - y1) * dist)
        y2 = y1 + max(inset_y, travel)
        return _fit(cx, y1), _fit(cx, y2)
    if direction == "left":
        x1 = r - inset_x
        x2 = l + inset_x
        travel = int((x1 - x2) * dist)
        x2 = x1 - max(inset_x, travel)
        return _fit(x1, cy), _fit(x2, cy)
    # right
    x1 = l + inset_x
    x2 = r - inset_x
    travel = int((x2 - x1) * dist)
    x2 = x1 + max(inset_x, travel)
    return _fit(x1, cy), _fit(x2, cy)


class GesturePlanner:
    """Turn ExplorationRegion[] into SwipeAction PlannedAction candidates."""

    def __init__(
        self,
        *,
        edge_margin: float = 0.15,
        distance_ratio: float = 0.7,
        max_per_region: int = 4,
        no_change_limit: int = 2,
        base_priority: int = 40,
    ) -> None:
        self.edge_margin = edge_margin
        self.distance_ratio = distance_ratio
        self.max_per_region = max_per_region
        self.no_change_limit = no_change_limit
        self.base_priority = base_priority

    def plan(
        self,
        regions: Sequence[ExplorationRegion],
        *,
        screen_size: tuple[int, int] | None = None,
        memory: RegionExplorationMemory | None = None,
        meaningful_taps: int = 0,
    ) -> list[PlannedAction]:
        mem = memory or RegionExplorationMemory()
        planned: list[PlannedAction] = []
        seen: set[str] = set()

        # Prefer nested / horizontal carousels (specific) before large vertical feeds.
        ordered = sorted(
            regions,
            key=lambda r: (
                0 if r.nested else 1,
                0 if r.region_type == RegionType.HORIZONTAL_CAROUSEL else 1,
                0 if r.orientation == ScrollOrientation.HORIZONTAL else 1,
                -r.confidence,
            ),
        )

        for region in ordered:
            live = mem.merge_region(region)
            dirs = list(live.supported_directions())
            # Prefer unexplored forward direction first (up/left), then reverse.
            preferred_order = {
                ScrollOrientation.VERTICAL: ("up", "down"),
                ScrollOrientation.HORIZONTAL: ("left", "right"),
                ScrollOrientation.BOTH: ("up", "left", "down", "right"),
                ScrollOrientation.UNKNOWN: ("up", "down"),
            }.get(live.orientation, ("up", "down"))
            dirs = [d for d in preferred_order if d in dirs] + [
                d for d in dirs if d not in preferred_order
            ]

            added_for_region = 0
            for direction in dirs:
                if added_for_region >= self.max_per_region:
                    break
                cov = live.directions[direction]
                if cov.boundary_reached:
                    continue
                if cov.no_change_count >= self.no_change_limit:
                    continue
                if mem.total_gestures_for(live.region_id) >= self.max_per_region * 2:
                    continue

                start, end = gesture_points_for_region(
                    live,
                    direction,  # type: ignore[arg-type]
                    edge_margin=self.edge_margin,
                    distance_ratio=self.distance_ratio,
                    screen_size=screen_size,
                )
                key = f"swipe:{direction}:{live.region_id}"
                if key in seen:
                    continue
                seen.add(key)

                priority = self._priority(
                    live,
                    direction,  # type: ignore[arg-type]
                    meaningful_taps=meaningful_taps,
                    coverage=cov,
                )
                label = f"swipe {direction} ({live.region_type.value})"
                meta: dict[str, Any] = {
                    "direction": direction,
                    "region_id": live.region_id,
                    "region_type": live.region_type.value,
                    "orientation": live.orientation.value,
                    "bounds": list(live.bounds),
                    "confidence": live.confidence,
                    "spatial": True,
                    "start": list(start),
                    "end": list(end),
                }
                planned.append(
                    PlannedAction(
                        key=key,
                        action=SwipeAction(
                            direction=direction,  # type: ignore[arg-type]
                            start=start,
                            end=end,
                        ),
                        kind=f"swipe_{direction}",
                        priority=priority,
                        label=label,
                        meta=meta,
                    )
                )
                log_gesture(
                    "planning swipe_%s region=%s priority=%s",
                    direction,
                    live.region_id,
                    priority,
                )
                added_for_region += 1

        planned.sort(key=lambda p: (-p.priority, p.key))
        return planned

    def _priority(
        self,
        region: ExplorationRegion,
        direction: SwipeDirection,
        *,
        meaningful_taps: int,
        coverage: Any,
    ) -> int:
        base = self.base_priority
        if meaningful_taps >= 2:
            base = max(24, base - 8)
        if region.region_type == RegionType.HORIZONTAL_CAROUSEL:
            base += 18
        elif region.orientation == ScrollOrientation.HORIZONTAL:
            base += 12
        elif region.region_type == RegionType.VERTICAL_SCROLL:
            base += 8
        if region.nested:
            base += 10
        if region.partially_visible_content and direction in {"left", "right"}:
            base += 14
        if region.confidence >= 0.9:
            base += 6
        # Unexplored forward directions beat reverse / already tried.
        if coverage.gesture_count == 0:
            base += 10
        if coverage.new_content_count > 0 and not coverage.boundary_reached:
            base += 6
        if coverage.no_change_count:
            base -= 12 * int(coverage.no_change_count)
        if direction in {"up", "left"}:
            base += 3
        if region.region_type == RegionType.SCREEN_FALLBACK:
            base = min(base, 28)
        return max(5, base)


def plan_gesture_actions(
    regions: Sequence[ExplorationRegion],
    *,
    screen_size: tuple[int, int] | None = None,
    memory: RegionExplorationMemory | None = None,
    meaningful_taps: int = 0,
    edge_margin: float = 0.15,
    distance_ratio: float = 0.7,
    max_per_region: int = 4,
    no_change_limit: int = 2,
) -> list[PlannedAction]:
    return GesturePlanner(
        edge_margin=edge_margin,
        distance_ratio=distance_ratio,
        max_per_region=max_per_region,
        no_change_limit=no_change_limit,
    ).plan(
        regions,
        screen_size=screen_size,
        memory=memory,
        meaningful_taps=meaningful_taps,
    )
