"""Stay on a newly reached screen and record how its ads change over time.

One screenshot per screen misses ads that load late or move: a bottom banner at
t=0 can become a top banner at t=6s, or a fullscreen ad can cover the screen.
After the explorer reaches a new screen this routine re-reads the UI every
``interval`` seconds for ``seconds`` seconds, runs the placement detector on
each frame, and keeps one sighting per distinct layout (type + position + box).
A screenshot is captured only when the layout changes, so the cost stays small.

All device access is injected so it can be tested without an emulator.
"""

from __future__ import annotations

import logging
import time
from types import SimpleNamespace
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from app.modules.exploration.ad_escape import is_ad_screen
from app.modules.exploration.ui_element import UIElement

logger = logging.getLogger(__name__)


@dataclass
class AdSightingRecord:
    offset_seconds: float
    ad_type: str
    position: str | None
    relative_bbox: list[float] | None
    coverage_ratio: float | None
    is_fullscreen: bool
    evidence: list[str] = field(default_factory=list)
    frame_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "offset_seconds": round(self.offset_seconds, 2),
            "ad_type": self.ad_type,
            "position": self.position,
            "relative_bbox": self.relative_bbox,
            "coverage_ratio": self.coverage_ratio,
            "is_fullscreen": self.is_fullscreen,
            "evidence": list(self.evidence),
            "frame_id": self.frame_id,
        }


@dataclass
class ScreenAdTimelineRecord:
    state_id: str
    page: str | None
    activity: str | None
    sightings: list[AdSightingRecord] = field(default_factory=list)
    dwell_seconds: float = 0.0
    stopped_reason: str = "completed"

    @property
    def positions_seen(self) -> list[str]:
        ordered: list[str] = []
        for item in self.sightings:
            if item.position and item.position not in ordered:
                ordered.append(item.position)
        return ordered

    def to_dict(self) -> dict[str, Any]:
        positions = self.positions_seen
        return {
            "state_id": self.state_id,
            "page": self.page,
            "activity": self.activity,
            "sightings": [item.to_dict() for item in self.sightings],
            "positions_seen": positions,
            "position_changed": len(positions) > 1,
            "dwell_seconds": round(self.dwell_seconds, 2),
            "stopped_reason": self.stopped_reason,
        }


@dataclass
class DwellOutcome:
    timeline: ScreenAdTimelineRecord
    frames: list[Any] = field(default_factory=list)  # CapturedScreenshot-like, with .state_id


def _signature(fp: Any) -> tuple[str, str, tuple[float, ...]]:
    bbox = tuple(round(float(v) * 20) / 20 for v in (fp.relative_bbox or ()))
    return (str(fp.ad_type), str(fp.position), bbox)


def dwell_observe(
    *,
    state_id: str,
    page: str | None,
    activity: str | None,
    target_package: str,
    dump: Callable[[], tuple[Sequence[UIElement], tuple[int, int], str | None]],
    package: Callable[[], str | None],
    detect: Callable[[Sequence[UIElement], tuple[int, int], str | None], Sequence[Any]],
    capture: Callable[[], Any],
    seconds: float = 6.0,
    interval: float = 1.5,
    max_frames: int = 4,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> DwellOutcome:
    """Re-observe the current screen and record each distinct ad layout."""
    timeline = ScreenAdTimelineRecord(state_id=state_id, page=page, activity=activity)
    frames: list[Any] = []
    seen: set[frozenset] = set()
    started = clock()
    first_tick = True

    def add(fps: Sequence[Any], offset: float, frame_id: str | None, fullscreen: bool) -> None:
        for fp in fps:
            timeline.sightings.append(
                AdSightingRecord(
                    offset_seconds=offset,
                    ad_type=str(fp.ad_type),
                    position=fp.position,
                    relative_bbox=list(fp.relative_bbox) if fp.relative_bbox else None,
                    coverage_ratio=_coverage(fp),
                    is_fullscreen=fullscreen or fp.position == "fullscreen",
                    evidence=list(fp.evidence or ()),
                    frame_id=frame_id,
                )
            )

    while True:
        offset = clock() - started
        try:
            elements, size, current_activity = dump()
        except Exception as exc:  # noqa: BLE001 - never break exploration for a missed frame
            logger.debug("[AD-DWELL] dump failed: %s", exc)
            timeline.stopped_reason = "dump_failed"
            break

        if activity and current_activity and current_activity != activity:
            timeline.stopped_reason = "navigated"
            break

        fullscreen_ad = is_ad_screen(
            elements,
            activity=current_activity,
            package=package(),
            target_package=target_package,
            screen_size=size,
        )
        fps = list(detect(elements, size, current_activity))
        signature = frozenset(_signature(fp) for fp in fps)

        if fps and signature not in seen:
            seen.add(signature)
            frame_id: str | None = state_id if first_tick else None
            if not first_tick and len(frames) < max_frames:
                try:
                    shot = capture()
                    frames.append(shot)
                    frame_id = getattr(shot, "state_id", None)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("[AD-DWELL] capture failed: %s", exc)
            add(fps, offset, frame_id, fullscreen_ad)

        if fullscreen_ad:
            # The explorer's ad-escape handles closing it on the next step.
            if not fps:
                frame_id = None
                if len(frames) < max_frames:
                    try:
                        shot = capture()
                        frames.append(shot)
                        frame_id = getattr(shot, "state_id", None)
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("[AD-DWELL] capture failed: %s", exc)
                add(_fullscreen_stub(), offset, frame_id, True)
            timeline.stopped_reason = "ad_screen"
            break

        first_tick = False
        if clock() - started + interval > seconds:
            break
        sleep(interval)

    timeline.dwell_seconds = clock() - started
    return DwellOutcome(timeline=timeline, frames=frames)


def _coverage(fp: Any) -> float | None:
    bbox = fp.relative_bbox
    if bbox and len(bbox) == 4:
        return round(float(bbox[2]) * float(bbox[3]), 3)
    return None


@dataclass
class _Stub:
    ad_type: str = "interstitial"
    position: str = "fullscreen"
    relative_bbox: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
    evidence: tuple[str, ...] = ("activity:ad_screen",)


def _fullscreen_stub() -> list[_Stub]:
    return [_Stub()]


def frame_publish_records(frames: Sequence[Any], timelines: dict[str, ScreenAdTimelineRecord]) -> list[Any]:
    """Wrap dwell frames so they can be uploaded like state screenshots.

    ``publish_exploration_screenshots`` reads ``screenshot`` / ``visual`` / ``ad_placement``
    from each record; these carry the position and type seen in that frame.
    """
    by_frame: dict[str, tuple[str, AdSightingRecord]] = {}
    for timeline in timelines.values():
        for item in timeline.sightings:
            if item.frame_id and item.frame_id not in by_frame:
                by_frame[item.frame_id] = (timeline.state_id, item)

    records: list[Any] = []
    for shot in frames:
        frame_id = getattr(shot, "state_id", None)
        owner = by_frame.get(frame_id or "")
        regions: list[dict[str, Any]] = []
        if owner is not None:
            _, sighting = owner
            regions = [
                {"ad_type": sighting.ad_type, "position": sighting.position, "confidence": 0.7}
            ]
        records.append(
            SimpleNamespace(
                state_id=frame_id,
                screenshot=shot,
                visual=SimpleNamespace(activity=getattr(shot, "activity", None)),
                label="ad_dwell",
                trigger_action="ad_dwell",
                ad_placement=SimpleNamespace(slot_count=len(regions), candidate_regions=regions),
            )
        )
    return records
