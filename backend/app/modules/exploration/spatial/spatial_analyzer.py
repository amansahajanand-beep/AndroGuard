"""Phase 12J — Detect scroll / carousel regions from the UI hierarchy."""

from __future__ import annotations

import re
from typing import Sequence

from app.modules.exploration.log_tags import log_gesture
from app.modules.exploration.spatial.models import (
    ExplorationRegion,
    RegionType,
    ScrollOrientation,
)
from app.modules.exploration.ui_element import UIElement

_VERTICAL_CLASS_RX = re.compile(
    r"ScrollView|ListView|RecyclerView|NestedScrollView|LazyColumn|"
    r"VerticalScrollView|ExpandableListView",
    re.I,
)
_HORIZONTAL_CLASS_RX = re.compile(
    r"HorizontalScrollView|ViewPager|ViewPager2|LazyRow|"
    r"RecyclerView.*HORIZONTAL|Pager",
    re.I,
)
_HORIZONTAL_ID_RX = re.compile(
    r"viewpager|view_pager|carousel|slider|banner_pager|horizontal|"
    r"tab_strip|gallery|recyclerview.*horiz",
    re.I,
)
_VERTICAL_ID_RX = re.compile(
    r"scroll|list|recycler|feed|content|nested_scroll|lazy.?column",
    re.I,
)


def _area(bounds: tuple[int, int, int, int]) -> int:
    return max(0, bounds[2] - bounds[0]) * max(0, bounds[3] - bounds[1])


def _quantize_bounds(bounds: tuple[int, int, int, int], step: int = 24) -> str:
    l, t, r, b = bounds
    return f"{l // step}_{t // step}_{r // step}_{b // step}"


def _contains(
    outer: tuple[int, int, int, int], inner: tuple[int, int, int, int]
) -> bool:
    return (
        inner[0] >= outer[0]
        and inner[1] >= outer[1]
        and inner[2] <= outer[2]
        and inner[3] <= outer[3]
    )


def _visible_children(
    parent: UIElement, elements: Sequence[UIElement]
) -> list[UIElement]:
    kids: list[UIElement] = []
    for el in elements:
        if el is parent:
            continue
        if not el.visible or el.width <= 0 or el.height <= 0:
            continue
        if _contains(parent.bounds, el.bounds) and el.bounds != parent.bounds:
            # Direct-ish child: not deeply nested tiny node only.
            if el.width * el.height >= 40 * 40:
                kids.append(el)
    return kids


def _similar_size(a: UIElement, b: UIElement, *, tol: float = 0.35) -> bool:
    if a.width <= 0 or b.width <= 0 or a.height <= 0 or b.height <= 0:
        return False
    wr = abs(a.width - b.width) / max(a.width, b.width)
    hr = abs(a.height - b.height) / max(a.height, b.height)
    return wr <= tol and hr <= tol


def _detect_repeated_horizontal_row(
    elements: Sequence[UIElement],
    *,
    screen_size: tuple[int, int] | None,
) -> list[tuple[tuple[int, int, int, int], list[UIElement], bool]]:
    """Find horizontal sequences of similar siblings (carousel-like)."""
    width = (screen_size[0] if screen_size else 0) or 0
    height = (screen_size[1] if screen_size else 0) or 0
    candidates = [
        el
        for el in elements
        if el.visible
        and el.enabled
        and el.width >= 48
        and el.height >= 48
        and (el.clickable or el.focusable or bool(el.text) or bool(el.content_description))
        and (height <= 0 or el.bottom < height * 0.92)
        and (height <= 0 or el.top > height * 0.05)
    ]
    # Group by approximate vertical band.
    bands: dict[int, list[UIElement]] = {}
    for el in candidates:
        band = el.top // max(40, el.height // 2 or 40)
        bands.setdefault(band, []).append(el)

    rows: list[tuple[tuple[int, int, int, int], list[UIElement], bool]] = []
    for items in bands.values():
        if len(items) < 3:
            continue
        items = sorted(items, key=lambda e: e.left)
        # Need left-to-right progression and similar sizes.
        similar = [items[0]]
        for nxt in items[1:]:
            if nxt.left >= similar[-1].left and _similar_size(similar[-1], nxt):
                similar.append(nxt)
        if len(similar) < 3:
            continue
        # Horizontal span should be meaningful.
        span = similar[-1].right - similar[0].left
        if width > 0 and span < width * 0.35:
            continue
        top = min(e.top for e in similar)
        bottom = max(e.bottom for e in similar)
        left = min(e.left for e in similar)
        right = max(e.right for e in similar)
        # Expand slightly to gesture mid-band.
        pad_y = max(8, (bottom - top) // 8)
        bounds = (left, max(0, top - pad_y), right, bottom + pad_y)
        partial = False
        if width > 0:
            # Clipped at left/right edge → more content likely.
            if similar[0].left <= width * 0.02 or similar[-1].right >= width * 0.98:
                partial = True
            # Last card truncated relative to peers.
            if similar[-1].width < similar[0].width * 0.75:
                partial = True
            if similar[-1].right >= width - 8:
                partial = True
        rows.append((bounds, similar, partial))
    return rows


class SpatialAnalyzer:
    """Identify vertical / horizontal / carousel / nested scroll regions."""

    def __init__(
        self,
        *,
        min_region_area: int = 80 * 80,
        max_regions: int = 8,
    ) -> None:
        self.min_region_area = min_region_area
        self.max_regions = max_regions

    def analyze(
        self,
        elements: Sequence[UIElement],
        *,
        screen_size: tuple[int, int] | None = None,
        state_id: str | None = None,
    ) -> list[ExplorationRegion]:
        regions: list[ExplorationRegion] = []
        seen_keys: set[str] = set()

        for el in elements:
            if not el.visible or not el.enabled:
                continue
            if _area(el.bounds) < self.min_region_area:
                continue
            cls = el.class_name or ""
            rid = el.resource_id or ""
            blob = f"{cls} {rid}"

            is_h_class = bool(_HORIZONTAL_CLASS_RX.search(cls) or _HORIZONTAL_ID_RX.search(rid))
            is_v_class = bool(_VERTICAL_CLASS_RX.search(cls) or _VERTICAL_ID_RX.search(rid))
            scrollable = bool(el.scrollable)

            if not (scrollable or is_h_class or is_v_class):
                continue

            orientation = ScrollOrientation.UNKNOWN
            region_type = RegionType.UNKNOWN_SCROLL
            confidence = 0.55
            supports_up = supports_down = supports_left = supports_right = False

            if is_h_class or (scrollable and is_h_class):
                orientation = ScrollOrientation.HORIZONTAL
                region_type = (
                    RegionType.HORIZONTAL_CAROUSEL
                    if "pager" in blob.lower() or "carousel" in blob.lower()
                    else RegionType.HORIZONTAL_SCROLL
                )
                supports_left = supports_right = True
                confidence = 0.95 if is_h_class else 0.8
            elif is_v_class or (scrollable and not is_h_class):
                orientation = ScrollOrientation.VERTICAL
                region_type = RegionType.VERTICAL_SCROLL
                supports_up = supports_down = True
                confidence = 0.92 if is_v_class else (0.85 if scrollable else 0.6)
            elif scrollable:
                # Ambiguous scrollable — prefer vertical (common feeds).
                orientation = ScrollOrientation.VERTICAL
                region_type = RegionType.VERTICAL_SCROLL
                supports_up = supports_down = True
                confidence = 0.7

            # Aspect hint for ambiguous scrollables.
            if scrollable and el.width > el.height * 1.6 and not is_v_class:
                orientation = ScrollOrientation.HORIZONTAL
                region_type = RegionType.HORIZONTAL_SCROLL
                supports_up = supports_down = False
                supports_left = supports_right = True
                confidence = max(confidence, 0.75)

            key = f"{region_type.value}:{_quantize_bounds(el.bounds)}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            rid_short = (el.resource_id or "").split("/")[-1][:24] or "node"
            region_id = f"region_{len(regions)+1}_{rid_short}"
            regions.append(
                ExplorationRegion(
                    region_id=region_id,
                    region_type=region_type,
                    bounds=el.bounds,
                    orientation=orientation,
                    scrollable=scrollable or is_h_class or is_v_class,
                    confidence=confidence,
                    source="scrollable_node" if scrollable else "class_hint",
                    element_class=cls,
                    resource_id=rid,
                    supports_up=supports_up,
                    supports_down=supports_down,
                    supports_left=supports_left,
                    supports_right=supports_right,
                    last_observed_state_id=state_id,
                )
            )

        # Inferred horizontal carousels from repeated siblings / partial cards.
        for bounds, kids, partial in _detect_repeated_horizontal_row(
            elements, screen_size=screen_size
        ):
            key = f"carousel:{_quantize_bounds(bounds)}"
            if key in seen_keys:
                # Upgrade existing region if overlapping.
                continue
            # Skip if already covered by a high-confidence horizontal region.
            covered = False
            for reg in regions:
                if reg.orientation == ScrollOrientation.HORIZONTAL and _contains(
                    reg.bounds, bounds
                ):
                    if partial:
                        reg.partially_visible_content = True
                        reg.repeated_content = True
                        if reg.region_type == RegionType.HORIZONTAL_SCROLL:
                            reg.region_type = RegionType.HORIZONTAL_CAROUSEL
                    covered = True
                    break
            if covered:
                continue
            seen_keys.add(key)
            region_id = f"region_{len(regions)+1}_carousel"
            regions.append(
                ExplorationRegion(
                    region_id=region_id,
                    region_type=RegionType.HORIZONTAL_CAROUSEL,
                    bounds=bounds,
                    orientation=ScrollOrientation.HORIZONTAL,
                    scrollable=True,
                    confidence=0.78 if partial else 0.68,
                    source="inferred_carousel",
                    element_class="inferred.HorizontalCarousel",
                    resource_id="",
                    supports_left=True,
                    supports_right=True,
                    partially_visible_content=partial,
                    repeated_content=True,
                    last_observed_state_id=state_id,
                )
            )

        # Mark nested: smaller region fully inside a larger one.
        regions.sort(key=lambda r: _area(r.bounds), reverse=True)
        for i, child in enumerate(regions):
            for parent in regions[:i]:
                if parent.region_id == child.region_id:
                    continue
                if _area(child.bounds) >= _area(parent.bounds) * 0.95:
                    continue
                if _contains(parent.bounds, child.bounds):
                    child.nested = True
                    child.parent_region_id = parent.region_id
                    if child.orientation != parent.orientation:
                        child.region_type = RegionType.NESTED_SCROLL
                        child.confidence = max(child.confidence, 0.8)
                    break

        # Prefer nested / higher-confidence first for planning, keep multiple.
        regions.sort(
            key=lambda r: (
                0 if r.nested else 1,
                -r.confidence,
                -_area(r.bounds),
            )
        )
        if len(regions) > self.max_regions:
            regions = regions[: self.max_regions]

        # Conservative screen fallback when nothing detected.
        if not regions and screen_size:
            w, h = screen_size
            if w > 0 and h > 0:
                regions.append(
                    ExplorationRegion(
                        region_id="region_1_screen",
                        region_type=RegionType.SCREEN_FALLBACK,
                        bounds=(0, 0, w, h),
                        orientation=ScrollOrientation.VERTICAL,
                        scrollable=True,
                        confidence=0.35,
                        source="screen_fallback",
                        supports_up=True,
                        supports_down=True,
                        # Horizontal screen swipe only if wide aspect suggests paging.
                        supports_left=False,
                        supports_right=False,
                        last_observed_state_id=state_id,
                    )
                )

        for reg in regions:
            log_gesture(
                "detected region %s type=%s orientation=%s confidence=%.2f "
                "partial=%s nested=%s",
                reg.region_id,
                reg.region_type.value,
                reg.orientation.value,
                reg.confidence,
                reg.partially_visible_content,
                reg.nested,
            )
        return regions


def analyze_regions(
    elements: Sequence[UIElement],
    *,
    screen_size: tuple[int, int] | None = None,
    state_id: str | None = None,
) -> list[ExplorationRegion]:
    return SpatialAnalyzer().analyze(
        elements, screen_size=screen_size, state_id=state_id
    )
