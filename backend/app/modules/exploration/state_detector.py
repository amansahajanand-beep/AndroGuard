"""Screen-state detection: unique visual states vs ad-placement layout states.

Intuition
---------
A raw pixel dump changes constantly (clock, spinners, ads animating). We therefore
separate:

* **Visual state** — "is the user looking at the same screen conceptually?"
  Built from a perceptual image hash (status/nav chrome cropped) plus a stable
  UI hierarchy signature (class/resource-id/clickable/bounds — not volatile text).

* **Ad placement state** — "where could ads sit on this layout?"
  Independent fingerprint from AdView/WebView-like nodes and large bottom/top
  bands. Two game frames can share one ad-placement fingerprint even when visual
  content differs. Real ad-network detection is Phase later; this only scaffolds
  the layout signature.

Only **new visual states** are retained by default. Ad-placement fingerprints are
always attached so later stages can group screenshots by slot layout.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Sequence

from app.core.config import settings
from app.modules.exploration.image_hasher import ImageHashResult, ImageHasher
from app.modules.exploration.screenshot_manager import CapturedScreenshot
from app.modules.exploration.ui_element import UIElement

logger = logging.getLogger(__name__)

_AD_CLASS_HINTS = re.compile(
    r"(adview|ads\.|webview|AudienceNetwork|AdActivity|ads\.Ad)",
    re.IGNORECASE,
)
_AD_ID_HINTS = re.compile(r"(^|/)(ad|ads|banner|interstitial|nativead|rewarded)(_|$|/)", re.IGNORECASE)


@dataclass(frozen=True)
class VisualFingerprint:
    """Identity of the screen the user is conceptually on."""

    image_hash: str
    ahash: str
    dhash: str
    ui_structure_hash: str
    activity: str | None = None
    element_count: int = 0
    clickable_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AdLayoutFingerprint:
    """Phase 3 layout signature for potential ad slots (not visual game content).

    Kept separate from Phase 5 :class:`~app.modules.exploration.ad_discovery.AdPlacementFingerprint`,
    which describes a single business-facing placement variation.
    """

    layout_hash: str
    slot_count: int
    candidate_regions: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "layout_hash": self.layout_hash,
            "slot_count": self.slot_count,
            "candidate_regions": list(self.candidate_regions),
        }


@dataclass
class ScreenStateRecord:
    """A retained unique visual state (optionally with its ad-layout fingerprint)."""

    state_id: str
    visual: VisualFingerprint
    ad_placement: AdLayoutFingerprint
    screenshot: CapturedScreenshot
    label: str | None = None
    depth: int = 0
    is_entry_point: bool = False
    trigger_action: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state_id": self.state_id,
            "label": self.label,
            "depth": self.depth,
            "is_entry_point": self.is_entry_point,
            "trigger_action": self.trigger_action,
            "visual": self.visual.to_dict(),
            "ad_placement": self.ad_placement.to_dict(),
            "screenshot": self.screenshot.to_dict(),
            "extras": dict(self.extras),
        }


@dataclass(frozen=True)
class StateDecision:
    """Result of comparing one observation against known visual states."""

    is_new: bool
    state_id: str
    matched_state_id: str | None
    visual_similarity: float
    ui_structure_match: bool
    visual: VisualFingerprint
    ad_placement: AdLayoutFingerprint
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_new": self.is_new,
            "state_id": self.state_id,
            "matched_state_id": self.matched_state_id,
            "visual_similarity": self.visual_similarity,
            "ui_structure_match": self.ui_structure_match,
            "reason": self.reason,
            "visual": self.visual.to_dict(),
            "ad_placement": self.ad_placement.to_dict(),
        }


class StateDetector:
    """Compare observations and keep only meaningful unique visual states."""

    def __init__(
        self,
        *,
        hasher: ImageHasher | None = None,
        similarity_threshold: float | None = None,
    ) -> None:
        self.hasher = hasher or ImageHasher()
        self.similarity_threshold = (
            similarity_threshold
            if similarity_threshold is not None
            else settings.exploration_state_similarity_threshold
        )
        self._states: dict[str, ScreenStateRecord] = {}
        self._hash_cache: dict[str, ImageHashResult] = {}

    @property
    def states(self) -> list[ScreenStateRecord]:
        return list(self._states.values())

    def clear(self) -> None:
        self._states.clear()
        self._hash_cache.clear()

    def build_visual_fingerprint(
        self,
        screenshot: CapturedScreenshot,
        elements: Sequence[UIElement] | None = None,
        *,
        activity: str | None = None,
    ) -> VisualFingerprint:
        elements = list(elements or [])
        return VisualFingerprint(
            image_hash=screenshot.image_hash,
            ahash=screenshot.ahash,
            dhash=screenshot.dhash,
            ui_structure_hash=ui_structure_hash(elements),
            activity=activity or screenshot.activity,
            element_count=len(elements),
            clickable_count=sum(1 for item in elements if item.clickable and item.enabled),
        )

    def build_ad_placement_fingerprint(
        self,
        elements: Sequence[UIElement] | None = None,
        *,
        screen_width: int | None = None,
        screen_height: int | None = None,
    ) -> AdLayoutFingerprint:
        return ad_placement_fingerprint(
            elements or [],
            screen_width=screen_width,
            screen_height=screen_height,
        )

    def observe(
        self,
        screenshot: CapturedScreenshot,
        *,
        elements: Sequence[UIElement] | None = None,
        activity: str | None = None,
        trigger_action: str | None = None,
        retain: bool = True,
        label: str | None = None,
        depth: int = 0,
        is_entry_point: bool = False,
    ) -> StateDecision:
        """Fingerprint the observation, compare to known visual states, optionally retain."""
        visual = self.build_visual_fingerprint(screenshot, elements, activity=activity)
        ad_fp = self.build_ad_placement_fingerprint(
            elements,
            screen_width=screenshot.width,
            screen_height=screenshot.height,
        )
        current_hash = ImageHashResult(
            algorithm="ahash+dhash",
            ahash=screenshot.ahash,
            dhash=screenshot.dhash,
            combined=screenshot.image_hash,
            hash_size=self.hasher.hash_size,
            width=screenshot.width,
            height=screenshot.height,
        )

        best_id: str | None = None
        best_sim = -1.0
        best_ui_match = False

        for state_id, record in self._states.items():
            other = self._hash_cache.get(state_id)
            if other is None:
                other = ImageHashResult(
                    algorithm="ahash+dhash",
                    ahash=record.visual.ahash,
                    dhash=record.visual.dhash,
                    combined=record.visual.image_hash,
                    hash_size=self.hasher.hash_size,
                    width=record.screenshot.width,
                    height=record.screenshot.height,
                )
                self._hash_cache[state_id] = other
            sim = self.hasher.similarity(current_hash, other)
            ui_match = (
                bool(visual.ui_structure_hash)
                and visual.ui_structure_hash == record.visual.ui_structure_hash
            )
            # Prefer matches that also share UI structure when similarities are close.
            score = sim + (0.03 if ui_match else 0.0)
            if score > best_sim:
                best_sim = sim
                best_id = state_id
                best_ui_match = ui_match

        is_duplicate = best_id is not None and best_sim >= self.similarity_threshold
        if is_duplicate and best_id is not None:
            decision = StateDecision(
                is_new=False,
                state_id=best_id,
                matched_state_id=best_id,
                visual_similarity=best_sim,
                ui_structure_match=best_ui_match,
                visual=visual,
                ad_placement=ad_fp,
                reason=(
                    f"Duplicate visual state (similarity={best_sim:.3f} "
                    f">= {self.similarity_threshold:.3f})"
                    + ("; UI structure matched" if best_ui_match else "")
                ),
            )
            logger.info("State duplicate -> %s (%.3f)", best_id, best_sim)
            return decision

        new_id = screenshot.state_id or f"state-{uuid.uuid4().hex[:12]}"
        # Keep screenshot metadata aligned with the retained state id.
        screenshot.state_id = new_id
        if trigger_action and not screenshot.trigger_action:
            screenshot.trigger_action = trigger_action

        decision = StateDecision(
            is_new=True,
            state_id=new_id,
            matched_state_id=None,
            visual_similarity=best_sim if best_sim >= 0 else 0.0,
            ui_structure_match=False,
            visual=visual,
            ad_placement=ad_fp,
            reason="New visual state retained" if retain else "New visual state (not retained)",
        )

        if retain:
            record = ScreenStateRecord(
                state_id=new_id,
                visual=visual,
                ad_placement=ad_fp,
                screenshot=screenshot,
                label=label,
                depth=depth,
                is_entry_point=is_entry_point,
                trigger_action=trigger_action or screenshot.trigger_action,
            )
            self._states[new_id] = record
            self._hash_cache[new_id] = current_hash
            logger.info(
                "New visual state %s retained (ad_slots=%s, closest=%.3f)",
                new_id,
                ad_fp.slot_count,
                decision.visual_similarity,
            )
        return decision

    def compare_screenshots(
        self,
        left: CapturedScreenshot,
        right: CapturedScreenshot,
        *,
        left_elements: Sequence[UIElement] | None = None,
        right_elements: Sequence[UIElement] | None = None,
    ) -> dict[str, Any]:
        """Side-by-side comparison used by the ``--compare-screenshot`` CLI."""
        left_hash = ImageHashResult(
            algorithm="ahash+dhash",
            ahash=left.ahash,
            dhash=left.dhash,
            combined=left.image_hash,
            hash_size=self.hasher.hash_size,
            width=left.width,
            height=left.height,
        )
        right_hash = ImageHashResult(
            algorithm="ahash+dhash",
            ahash=right.ahash,
            dhash=right.dhash,
            combined=right.image_hash,
            hash_size=self.hasher.hash_size,
            width=right.width,
            height=right.height,
        )
        visual_sim = self.hasher.similarity(left_hash, right_hash)
        left_ui = ui_structure_hash(left_elements or [])
        right_ui = ui_structure_hash(right_elements or [])
        left_ad = ad_placement_fingerprint(
            left_elements or [], screen_width=left.width, screen_height=left.height
        )
        right_ad = ad_placement_fingerprint(
            right_elements or [], screen_width=right.width, screen_height=right.height
        )
        same_visual = visual_sim >= self.similarity_threshold
        same_ad_layout = left_ad.layout_hash == right_ad.layout_hash and bool(left_ad.layout_hash)
        return {
            "visual_similarity": visual_sim,
            "same_visual_state": same_visual,
            "ui_structure_match": left_ui == right_ui and bool(left_ui),
            "same_ad_placement_state": same_ad_layout,
            "threshold": self.similarity_threshold,
            "left": {
                "state_id": left.state_id,
                "image_hash": left.image_hash,
                "activity": left.activity,
                "ui_structure_hash": left_ui,
                "ad_placement": left_ad.to_dict(),
            },
            "right": {
                "state_id": right.state_id,
                "image_hash": right.image_hash,
                "activity": right.activity,
                "ui_structure_hash": right_ui,
                "ad_placement": right_ad.to_dict(),
            },
        }


# --- Fingerprint helpers -----------------------------------------------------


def ui_structure_hash(elements: Iterable[UIElement]) -> str:
    """Stable hierarchy signature that ignores volatile text / animations."""
    parts: list[str] = []
    for item in elements:
        if not item.visible:
            continue
        # Quantize bounds so 1–2px jitter does not change the signature.
        bounds = _quantize_bounds(item.bounds)
        parts.append(
            "|".join(
                [
                    item.class_name,
                    item.resource_id,
                    "1" if item.clickable else "0",
                    "1" if item.scrollable else "0",
                    "1" if item.enabled else "0",
                    bounds,
                ]
            )
        )
    parts.sort()
    if not parts:
        return ""
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:32]


def ad_placement_fingerprint(
    elements: Sequence[UIElement],
    *,
    screen_width: int | None = None,
    screen_height: int | None = None,
) -> AdLayoutFingerprint:
    """Derive an ad-slot layout fingerprint from hierarchy hints + geometry.

    This is **not** ad detection. It only records where ad-like containers sit so
    later stages can say "same banner band, different creative".
    """
    width = screen_width or 0
    height = screen_height or 0
    regions: list[dict[str, Any]] = []

    for item in elements:
        if not item.visible:
            continue
        hint = _ad_hint(item, screen_width=width, screen_height=height)
        if not hint:
            continue
        regions.append(
            {
                "reason": hint,
                "class_name": item.class_name,
                "resource_id": item.resource_id,
                "bounds": list(item.bounds),
                "clickable": item.clickable,
                "package": item.package,
            }
        )

    regions.sort(key=lambda r: (r["bounds"], r["class_name"], r["resource_id"]))
    if not regions:
        layout = ""
    else:
        material = "\n".join(
            f"{r['reason']}|{r['class_name']}|{r['resource_id']}|{_quantize_bounds(tuple(r['bounds']))}"
            for r in regions
        )
        layout = hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]

    return AdLayoutFingerprint(
        layout_hash=layout,
        slot_count=len(regions),
        candidate_regions=tuple(regions),
    )


def _ad_hint(item: UIElement, *, screen_width: int, screen_height: int) -> str | None:
    class_name = item.class_name or ""
    resource_id = item.resource_id or ""
    if _AD_CLASS_HINTS.search(class_name):
        return "class_hint"
    if resource_id and _AD_ID_HINTS.search(resource_id):
        return "resource_id_hint"
    # Large horizontal bands near top/bottom are common banner slots.
    if screen_width > 0 and screen_height > 0 and item.width > 0 and item.height > 0:
        width_ratio = item.width / screen_width
        height_ratio = item.height / screen_height
        near_top = item.top <= screen_height * 0.12
        near_bottom = item.bottom >= screen_height * 0.88
        if width_ratio >= 0.7 and 0.04 <= height_ratio <= 0.22 and (near_top or near_bottom):
            return "banner_band"
        if width_ratio >= 0.85 and height_ratio >= 0.55:
            return "fullscreen_band"
    return None


def _quantize_bounds(bounds: tuple[int, int, int, int] | list[int], step: int = 8) -> str:
    left, top, right, bottom = bounds
    return f"{left // step},{top // step},{right // step},{bottom // step}"
