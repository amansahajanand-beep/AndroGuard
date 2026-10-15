"""Phase 12J — Exploration region models (spatial scroll units)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

SwipeDirection = Literal["up", "down", "left", "right"]


class RegionType(str, Enum):
    VERTICAL_SCROLL = "vertical_scroll"
    HORIZONTAL_SCROLL = "horizontal_scroll"
    HORIZONTAL_CAROUSEL = "horizontal_carousel"
    NESTED_SCROLL = "nested_scroll"
    UNKNOWN_SCROLL = "unknown_scroll"
    SCREEN_FALLBACK = "screen_fallback"


class ScrollOrientation(str, Enum):
    VERTICAL = "vertical"
    HORIZONTAL = "horizontal"
    BOTH = "both"
    UNKNOWN = "unknown"


@dataclass
class DirectionCoverage:
    """Per-direction exploration progress for one region."""

    explored: bool = False
    gesture_count: int = 0
    no_change_count: int = 0
    new_content_count: int = 0
    boundary_reached: bool = False
    last_state_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "explored": self.explored,
            "gesture_count": self.gesture_count,
            "no_change_count": self.no_change_count,
            "new_content_count": self.new_content_count,
            "boundary_reached": self.boundary_reached,
            "last_state_id": self.last_state_id,
        }


@dataclass
class ExplorationRegion:
    """A discoverable interactive / scrollable area on the current screen."""

    region_id: str
    region_type: RegionType
    bounds: tuple[int, int, int, int]
    orientation: ScrollOrientation
    scrollable: bool = True
    confidence: float = 0.5

    source: str = "hierarchy"
    element_class: str = ""
    resource_id: str = ""

    supports_up: bool = False
    supports_down: bool = False
    supports_left: bool = False
    supports_right: bool = False

    partially_visible_content: bool = False
    repeated_content: bool = False
    nested: bool = False
    parent_region_id: str | None = None

    directions: dict[str, DirectionCoverage] = field(default_factory=dict)
    last_observed_state_id: str | None = None
    last_gesture: str | None = None

    def __post_init__(self) -> None:
        for d in ("up", "down", "left", "right"):
            if d not in self.directions:
                self.directions[d] = DirectionCoverage()

    @property
    def left(self) -> int:
        return self.bounds[0]

    @property
    def top(self) -> int:
        return self.bounds[1]

    @property
    def right(self) -> int:
        return self.bounds[2]

    @property
    def bottom(self) -> int:
        return self.bounds[3]

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    @property
    def center(self) -> tuple[int, int]:
        return (self.left + self.width // 2, self.top + self.height // 2)

    def supported_directions(self) -> list[SwipeDirection]:
        out: list[SwipeDirection] = []
        if self.supports_up:
            out.append("up")
        if self.supports_down:
            out.append("down")
        if self.supports_left:
            out.append("left")
        if self.supports_right:
            out.append("right")
        return out

    def coverage_ratio(self) -> float:
        dirs = self.supported_directions()
        if not dirs:
            return 1.0
        done = sum(
            1
            for d in dirs
            if self.directions[d].explored or self.directions[d].boundary_reached
        )
        return done / float(len(dirs))

    def to_ai_summary(self) -> dict[str, Any]:
        explored = {
            d: bool(self.directions[d].explored or self.directions[d].boundary_reached)
            for d in self.supported_directions()
        }
        return {
            "id": self.region_id,
            "type": self.region_type.value,
            "orientation": self.orientation.value,
            "bounds": list(self.bounds),
            "explored": explored,
            "confidence": round(float(self.confidence), 2),
            "partially_visible": self.partially_visible_content,
            "coverage": round(self.coverage_ratio(), 2),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "region_id": self.region_id,
            "region_type": self.region_type.value,
            "bounds": list(self.bounds),
            "orientation": self.orientation.value,
            "scrollable": self.scrollable,
            "confidence": self.confidence,
            "source": self.source,
            "element_class": self.element_class,
            "resource_id": self.resource_id,
            "supports_up": self.supports_up,
            "supports_down": self.supports_down,
            "supports_left": self.supports_left,
            "supports_right": self.supports_right,
            "partially_visible_content": self.partially_visible_content,
            "repeated_content": self.repeated_content,
            "nested": self.nested,
            "parent_region_id": self.parent_region_id,
            "directions": {k: v.to_dict() for k, v in self.directions.items()},
            "last_observed_state_id": self.last_observed_state_id,
            "last_gesture": self.last_gesture,
            "coverage": self.coverage_ratio(),
        }
