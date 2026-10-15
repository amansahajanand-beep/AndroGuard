"""Phase 5: advertisement placement discovery (deterministic, no LLM).

A single app page can host many ad *layout* variations (banner top vs bottom,
native in-feed, interstitial, rewarded). Visual content of the page or the
creative itself must not invent a new placement — uniqueness is:

    page + ad_type + relative position + relative size + trigger action

Relative coordinates are used so different device densities stay comparable.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

from app.core.config import settings
from app.modules.exploration.ui_element import UIElement

logger = logging.getLogger(__name__)

AdTypeName = str  # banner | interstitial | native | rewarded | app_open | unknown
AdPositionName = str  # top | bottom | middle | fullscreen | unknown

_AD_CLASS_HINTS = re.compile(
    r"(adview|ads\.|AudienceNetwork|AdActivity|ads\.Ad|Rewarded|"
    r"Interstitial|NativeAd|PublisherAdView|AdFrame|"
    r"com\.google\.android\.gms\.ads|com\.unity3d\.services\.ads|"
    r"com\.facebook\.ads|com\.applovin|com\.ironsource|com\.vungle|"
    r"com\.mbridge|com\.bytedance\.sdk\.openadsdk)",
    re.IGNORECASE,
)
# Generic WebView only counts with an ad-ish id/text — bare WebView is app chrome.
_WEBVIEW_CLASS = re.compile(r"webview", re.IGNORECASE)
_AD_ID_HINTS = re.compile(
    r"(^|[/_.])(ad|ads|banner|interstitial|nativead|rewarded|appopen|app_open)([_/.-]|$)",
    re.IGNORECASE,
)
_REWARD_HINTS = re.compile(r"reward|video.?ad|watch.?ad|earn.?coin", re.IGNORECASE)
_INTERSTITIAL_HINTS = re.compile(r"interstitial|fullscreen.?ad|full.?screen.?ad", re.IGNORECASE)
_NATIVE_HINTS = re.compile(r"native.?ad|feed.?ad|content.?ad", re.IGNORECASE)
_BANNER_HINTS = re.compile(r"banner|adview|ad_frame|ad_container", re.IGNORECASE)
# Gate / setup screens — never treat their chrome as ad placements.
_GATE_ACTIVITY = re.compile(
    r"(default.?app|onboarding|splash|permission|consent|gdpr|welcome|"
    r"intro|tutorial|login|signup|sign.?in|set.?default)",
    re.IGNORECASE,
)
_GENERIC_CONTAINER = re.compile(
    r"(FrameLayout|LinearLayout|RelativeLayout|ConstraintLayout|ViewGroup|"
    r"ScrollView|RecyclerView|ViewPager|DecorView|ContentFrame)",
    re.IGNORECASE,
)

# Labels that often open rewarded / interstitial flows.
AD_TRIGGER_LABELS = re.compile(
    r"(watch|reward|video|play|continue|start|free\s*coin|earn|claim|"
    r"unlock|spin|bonus|ad\b|show\s*ad)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AdPlacementFingerprint:
    """One meaningful advertisement placement variation.

    ``relative_bbox`` is ``[left, top, width, height]`` in ``[0, 1]`` of the
    screen (example bottom banner: ``[0.0, 0.82, 1.0, 0.18]``).
    """

    page: str
    ad_detected: bool
    ad_type: AdTypeName
    position: AdPositionName
    relative_bbox: tuple[float, float, float, float]
    uniqueness_key: str = ""
    trigger_action: str | None = None
    visual_state_id: str | None = None
    screenshot_path: str | None = None
    evidence: tuple[str, ...] = ()
    run_index: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["relative_bbox"] = list(self.relative_bbox)
        payload["evidence"] = list(self.evidence)
        return payload


@dataclass
class AdPlacementRecord:
    """Retained unique placement plus discovery metadata."""

    fingerprint: AdPlacementFingerprint
    first_seen_run: int = 0
    seen_count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint.to_dict(),
            "first_seen_run": self.first_seen_run,
            "seen_count": self.seen_count,
        }


@dataclass
class AdDiscoveryLimits:
    target_ad_variations_per_page: int = 5
    max_ad_variations_per_page: int = 10
    max_exploration_runs: int = 5
    bbox_quantize: float = 0.05

    @classmethod
    def from_settings(cls) -> "AdDiscoveryLimits":
        return cls(
            target_ad_variations_per_page=settings.exploration_target_ad_variations_per_page,
            max_ad_variations_per_page=settings.exploration_max_ad_variations_per_page,
            max_exploration_runs=settings.exploration_max_runs,
            bbox_quantize=settings.exploration_ad_bbox_quantize,
        )


class AdPlacementCatalog:
    """Deduplicated store of ad-placement variations across one or more runs."""

    def __init__(self, limits: AdDiscoveryLimits | None = None) -> None:
        self.limits = limits or AdDiscoveryLimits.from_settings()
        self._by_key: dict[str, AdPlacementRecord] = {}
        self._by_page: dict[str, list[str]] = {}

    @property
    def placements(self) -> list[AdPlacementRecord]:
        return list(self._by_key.values())

    def count_for_page(self, page: str) -> int:
        return len(self._by_page.get(_normalize_page(page), []))

    def strong_count_for_page(self, page: str) -> int:
        """Count placements with SDK/class/id evidence (used for target early-stop)."""
        page_key = _normalize_page(page)
        keys = self._by_page.get(page_key, [])
        return sum(
            1
            for key in keys
            if is_strong_ad_evidence(self._by_key[key].fingerprint.evidence)
        )

    def pages(self) -> list[str]:
        return sorted(self._by_page.keys())

    def has_reached_target(self, page: str) -> bool:
        return self.strong_count_for_page(page) >= self.limits.target_ad_variations_per_page

    def has_reached_max(self, page: str) -> bool:
        return self.count_for_page(page) >= self.limits.max_ad_variations_per_page

    def observe(self, fingerprint: AdPlacementFingerprint) -> tuple[bool, AdPlacementRecord]:
        """Insert if unique and under the per-page max. Returns (is_new, record)."""
        if not fingerprint.ad_detected:
            key = fingerprint.uniqueness_key or uniqueness_key_for(fingerprint)
            empty = AdPlacementRecord(fingerprint=fingerprint)
            return False, empty

        page = _normalize_page(fingerprint.page)
        key = fingerprint.uniqueness_key or uniqueness_key_for(fingerprint)
        if key in self._by_key:
            record = self._by_key[key]
            record.seen_count += 1
            logger.info(
                "[AD] duplicate placement key=%s page=%s type=%s pos=%s (seen=%s)",
                key[:16],
                page,
                fingerprint.ad_type,
                fingerprint.position,
                record.seen_count,
            )
            return False, record

        if self.has_reached_max(page):
            logger.info(
                "[AD] page=%s at MAX_AD_VARIATIONS_PER_PAGE=%s — skipping new %s/%s",
                page,
                self.limits.max_ad_variations_per_page,
                fingerprint.ad_type,
                fingerprint.position,
            )
            return False, AdPlacementRecord(fingerprint=fingerprint, seen_count=0)

        fp = AdPlacementFingerprint(
            page=page,
            ad_detected=fingerprint.ad_detected,
            ad_type=fingerprint.ad_type,
            position=fingerprint.position,
            relative_bbox=fingerprint.relative_bbox,
            uniqueness_key=key,
            trigger_action=fingerprint.trigger_action,
            visual_state_id=fingerprint.visual_state_id,
            screenshot_path=fingerprint.screenshot_path,
            evidence=fingerprint.evidence,
            run_index=fingerprint.run_index,
        )
        record = AdPlacementRecord(fingerprint=fp, first_seen_run=fp.run_index, seen_count=1)
        self._by_key[key] = record
        self._by_page.setdefault(page, []).append(key)
        logger.info(
            "[AD] NEW placement page=%s type=%s pos=%s bbox=%s trigger=%s key=%s",
            page,
            fp.ad_type,
            fp.position,
            fp.relative_bbox,
            fp.trigger_action,
            key[:16],
        )
        return True, record

    def merge(self, other: "AdPlacementCatalog") -> int:
        """Merge another catalog; returns number of newly added unique placements."""
        added = 0
        for record in other.placements:
            is_new, _ = self.observe(record.fingerprint)
            if is_new:
                added += 1
        return added

    def to_dict(self) -> dict[str, Any]:
        by_page = {
            page: [self._by_key[k].to_dict() for k in keys]
            for page, keys in self._by_page.items()
        }
        return {
            "total_unique": len(self._by_key),
            "pages": by_page,
            "limits": {
                "target_ad_variations_per_page": self.limits.target_ad_variations_per_page,
                "max_ad_variations_per_page": self.limits.max_ad_variations_per_page,
                "max_exploration_runs": self.limits.max_exploration_runs,
            },
            "placements": [r.to_dict() for r in self.placements],
        }


class AdPlacementDetector:
    """Heuristic detector: UI hierarchy + geometry → placement fingerprints."""

    def __init__(self, *, bbox_quantize: float | None = None) -> None:
        self.bbox_quantize = (
            bbox_quantize
            if bbox_quantize is not None
            else settings.exploration_ad_bbox_quantize
        )

    def detect(
        self,
        elements: Sequence[UIElement],
        *,
        screen_width: int,
        screen_height: int,
        page: str,
        trigger_action: str | None = None,
        visual_state_id: str | None = None,
        screenshot_path: str | None = None,
        activity: str | None = None,
        run_index: int = 0,
    ) -> list[AdPlacementFingerprint]:
        """Return zero or more placement fingerprints for the current frame."""
        if screen_width <= 0 or screen_height <= 0:
            return []

        found: list[AdPlacementFingerprint] = []
        seen_keys: set[str] = set()

        for item in elements:
            if not item.visible or item.width <= 0 or item.height <= 0:
                continue
            classified = self._classify(
                item,
                screen_width=screen_width,
                screen_height=screen_height,
                activity=activity,
            )
            if classified is None:
                continue
            ad_type, position, relative_bbox, evidence = classified
            fp = AdPlacementFingerprint(
                page=_normalize_page(page),
                ad_detected=True,
                ad_type=ad_type,
                position=position,
                relative_bbox=relative_bbox,
                trigger_action=_action_bucket(trigger_action),
                visual_state_id=visual_state_id,
                screenshot_path=screenshot_path,
                evidence=tuple(evidence),
                run_index=run_index,
            )
            key = uniqueness_key_for(fp, quantize=self.bbox_quantize)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            found.append(
                AdPlacementFingerprint(
                    page=fp.page,
                    ad_detected=True,
                    ad_type=fp.ad_type,
                    position=fp.position,
                    relative_bbox=fp.relative_bbox,
                    uniqueness_key=key,
                    trigger_action=fp.trigger_action,
                    visual_state_id=fp.visual_state_id,
                    screenshot_path=fp.screenshot_path,
                    evidence=fp.evidence,
                    run_index=fp.run_index,
                )
            )
        return found

    def _classify(
        self,
        item: UIElement,
        *,
        screen_width: int,
        screen_height: int,
        activity: str | None,
    ) -> tuple[AdTypeName, AdPositionName, tuple[float, float, float, float], list[str]] | None:
        # Setup / default-app / splash screens are not ad surfaces.
        if activity and _GATE_ACTIVITY.search(activity):
            return None

        evidence: list[str] = []
        class_name = item.class_name or ""
        resource_id = item.resource_id or ""
        text_blob = f"{item.text} {item.content_description} {resource_id} {class_name}"

        left = item.left / screen_width
        top = item.top / screen_height
        width = item.width / screen_width
        height = item.height / screen_height
        relative_bbox = (
            _clamp01(left),
            _clamp01(top),
            _clamp01(width),
            _clamp01(height),
        )
        coverage = width * height

        class_hint = bool(_AD_CLASS_HINTS.search(class_name))
        id_hint = bool(resource_id and _AD_ID_HINTS.search(resource_id))
        text_hint = bool(
            _REWARD_HINTS.search(text_blob)
            or _INTERSTITIAL_HINTS.search(text_blob)
            or _NATIVE_HINTS.search(text_blob)
            or _BANNER_HINTS.search(text_blob)
        )
        webview = bool(_WEBVIEW_CLASS.search(class_name))
        # WebView alone is weak; require ad id/text together with it.
        hinted = class_hint or id_hint or (webview and (id_hint or text_hint))
        if class_hint:
            evidence.append(f"class:{class_name}")
        if id_hint:
            evidence.append(f"id:{resource_id}")
        if webview and (id_hint or text_hint):
            evidence.append(f"class:{class_name}")

        # Geometry only *supports* classification after a real ad hint.
        # Bare full-screen FrameLayouts / footer bands on app chrome must not count.
        geo_banner = width >= 0.7 and 0.04 <= height <= 0.22 and (top <= 0.12 or (top + height) >= 0.88)
        geo_full = width >= 0.85 and height >= 0.55
        geo_native = 0.35 <= width <= 0.98 and 0.12 <= height <= 0.45 and 0.15 <= top <= 0.75

        if not hinted:
            return None
        if _GENERIC_CONTAINER.search(class_name) and not (id_hint or text_hint or class_hint):
            return None

        if _REWARD_HINTS.search(text_blob) or (activity and _REWARD_HINTS.search(activity)):
            ad_type: AdTypeName = "rewarded"
            evidence.append("hint:rewarded")
        elif _INTERSTITIAL_HINTS.search(text_blob) or (
            hinted and (geo_full or coverage >= 0.55)
        ):
            ad_type = "interstitial"
            if geo_full or coverage >= 0.55:
                evidence.append("hint:fullscreen")
        elif _NATIVE_HINTS.search(text_blob) or (hinted and geo_native and not geo_banner):
            ad_type = "native"
        elif _BANNER_HINTS.search(text_blob) or (hinted and geo_banner):
            ad_type = "banner"
        elif hinted:
            ad_type = "unknown"
        else:
            return None

        if coverage >= 0.55 or geo_full:
            position: AdPositionName = "fullscreen"
        elif top <= 0.15 and height <= 0.30:
            position = "top"
        elif top >= 0.70 or (top + height) >= 0.88:
            position = "bottom"
        elif 0.20 <= top <= 0.70:
            position = "middle"
        else:
            position = "unknown"

        return ad_type, position, relative_bbox, evidence


def is_strong_ad_evidence(evidence: Sequence[str] | tuple[str, ...]) -> bool:
    """True when placement is backed by SDK class / ad resource id (not geometry alone)."""
    for item in evidence:
        if item.startswith("class:") or item.startswith("id:"):
            return True
    return False


def uniqueness_key_for(
    fp: AdPlacementFingerprint,
    *,
    quantize: float | None = None,
) -> str:
    """Stable key: page + type + position + quantized size/pos + action bucket."""
    step = quantize if quantize is not None else settings.exploration_ad_bbox_quantize
    left, top, width, height = fp.relative_bbox
    q = (
        f"{_q(left, step)},{_q(top, step)},{_q(width, step)},{_q(height, step)}"
    )
    material = "|".join(
        [
            _normalize_page(fp.page),
            fp.ad_type,
            fp.position,
            q,
            _action_bucket(fp.trigger_action) or "-",
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def relative_bbox_from_bounds(
    bounds: tuple[int, int, int, int] | list[int],
    *,
    screen_width: int,
    screen_height: int,
) -> tuple[float, float, float, float]:
    left, top, right, bottom = bounds
    w = max(0, right - left)
    h = max(0, bottom - top)
    if screen_width <= 0 or screen_height <= 0:
        return (0.0, 0.0, 0.0, 0.0)
    return (
        _clamp01(left / screen_width),
        _clamp01(top / screen_height),
        _clamp01(w / screen_width),
        _clamp01(h / screen_height),
    )


def is_ad_trigger_label(text: str, resource_id: str = "", content_description: str = "") -> bool:
    blob = f"{text} {resource_id} {content_description}"
    return bool(AD_TRIGGER_LABELS.search(blob))


def _normalize_page(page: str) -> str:
    value = (page or "unknown").strip() or "unknown"
    return value[:80]


def _action_bucket(trigger: str | None) -> str | None:
    if not trigger:
        return None
    kind = trigger.split(":", 1)[0].strip().lower()
    if kind in {"swipe_up", "swipe", "scroll"} and "up" in trigger.lower():
        return "scroll_up"
    if kind in {"swipe_down", "swipe", "scroll"} and "down" in trigger.lower():
        return "scroll_down"
    if kind == "tap":
        # Keep coarse tap bucket; label detail is not part of uniqueness beyond kind.
        return "tap"
    if kind in {"open_menu", "wait", "back", "entry"}:
        return kind
    return kind[:32]


def _q(value: float, step: float) -> str:
    """Bucket a relative coordinate. Floor keeps nearby creatives in one slot."""
    step = max(0.01, float(step))
    bucket = math.floor((float(value) + 1e-9) / step) * step
    return f"{bucket:.2f}"


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
