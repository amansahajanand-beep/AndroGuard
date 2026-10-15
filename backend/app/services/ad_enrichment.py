"""Phase 9 helpers: attach ad detections onto exploration states (best-effort)."""

from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import settings
from app.schemas.exploration import (
    AdPlacement,
    Bounds,
    ExplorationResult,
)

logger = logging.getLogger(__name__)


def _confidence_label(value: float) -> str:
    if value >= 0.8:
        return "HIGH"
    if value >= 0.55:
        return "MEDIUM"
    return "LOW"


def enrich_exploration_ads(exploration: ExplorationResult) -> None:
    """Fill ``ad_placements`` / screenshot ad fields from Phase 5 + Phase 6.

    Never raises; failures become exploration warnings.
    """
    if exploration is None or exploration.status in {"skipped", "failed"}:
        return

    announce_ads = 0
    try:
        from app.modules.ad_detection.factory import build_ad_detector
    except Exception:
        build_ad_detector = None  # type: ignore[assignment]

    detector = None
    if settings.ad_detection_enabled and build_ad_detector is not None:
        try:
            detector = build_ad_detector()
        except Exception:
            logger.warning("Could not build AdDetector for Phase 9", exc_info=True)
            exploration.warnings.append("Ad detector unavailable; using placement heuristics only.")

    blueprint = exploration.blueprint
    found_types: list[str] = []

    for state in exploration.states:
        shot = state.screenshot
        local_path = None
        if shot and getattr(shot, "local_path", None):
            candidate = Path(shot.local_path)
            if candidate.is_file():
                local_path = candidate
        if local_path is None and shot and shot.file_name:
            # Prefer package/job layout; fall back to legacy flat screenshots/.
            roots = [Path(settings.temp_root) / "screenshots"]
            package = exploration.package_name
            job = getattr(exploration, "job_id", None)
            if package or job:
                from app.modules.exploration.screenshot_storage import local_screenshots_dir

                roots.insert(0, local_screenshots_dir(package, job or "adhoc", ensure=False))
            for root in roots:
                candidate = root / shot.file_name
                if candidate.is_file():
                    local_path = candidate
                    break
                # Nested search when only the basename is known.
                matches = list(root.rglob(shot.file_name)) if root.is_dir() else []
                if matches:
                    local_path = matches[0]
                    break

        # Prefer existing Phase 5 placements already on the state.
        if state.ad_placements:
            primary = state.ad_placements[0]
            try:
                from app.modules.exploration.blueprint import tag_ad_placement

                for placement in state.ad_placements:
                    tag_ad_placement(
                        placement,
                        blueprint=blueprint,
                        activity=state.activity,
                    )
                    if placement.ad_detected and placement.ad_type:
                        found_types.append(str(placement.ad_type))
            except Exception:
                pass
            if shot is not None:
                shot.ad_detected = bool(primary.ad_detected)
                shot.ad_type = primary.ad_type
                shot.ad_position = primary.position
                conf = primary.confidence
                if isinstance(conf, str):
                    shot.confidence = {"HIGH": 0.9, "MEDIUM": 0.65, "LOW": 0.4}.get(conf)
                announce_ads += 1 if primary.ad_detected else 0
            continue

        # Phase 6 vision on unique screenshots (optional).
        if detector is None or local_path is None:
            continue
        try:
            detection = detector.detect(local_path)
        except Exception:
            logger.warning("Ad detect failed for %s", local_path, exc_info=True)
            continue

        if shot is not None:
            shot.ad_detected = bool(detection.detected)
            shot.ad_type = detection.type if detection.detected else None
            shot.ad_position = detection.position if detection.detected else None
            shot.confidence = float(detection.confidence) if detection.detected else None

        if not detection.detected:
            continue

        bbox = None
        box = getattr(detection, "bounding_box", None)
        if box is not None:
            bbox = Bounds(
                left=int(getattr(box, "x", 0)),
                top=int(getattr(box, "y", 0)),
                right=int(getattr(box, "x", 0)) + int(getattr(box, "width", 0)),
                bottom=int(getattr(box, "y", 0)) + int(getattr(box, "height", 0)),
            )

        ad_type = detection.type if detection.type in {
            "banner", "interstitial", "native", "rewarded", "app_open", "unknown"
        } else "unknown"

        placement = AdPlacement(
            page=state.label or (shot.page if shot else None),
            ad_detected=True,
            ad_type=ad_type,  # type: ignore[arg-type]
            position=detection.position,
            confidence=_confidence_label(float(detection.confidence)),  # type: ignore[arg-type]
            bounds=bbox,
            state_id=state.state_id,
            screenshot_file=shot.file_name if shot else None,
            detection_method="vision",
            evidence=list(getattr(detection, "evidence", None) or []),
        )
        try:
            from app.modules.exploration.blueprint import tag_ad_placement

            tag_ad_placement(placement, blueprint=blueprint, activity=state.activity)
        except Exception:
            pass
        found_types.append(str(ad_type))
        state.ad_placements.append(placement)
        exploration.ad_placements.append(placement)
        announce_ads += 1

    exploration.summary.ads_detected = max(
        exploration.summary.ads_detected, announce_ads
    )

    # Refresh coverage with observed ad types vs blueprint expectations.
    if blueprint is not None:
        try:
            from app.modules.exploration.blueprint import build_coverage

            covered = {}
            if exploration.coverage and exploration.coverage.goals:
                covered = {
                    item.goal_id: list(item.evidence)
                    for item in exploration.coverage.goals
                    if item.covered
                }
            exploration.coverage = build_coverage(
                blueprint,
                covered_goal_ids=covered,
                ad_types_found=found_types,
            )
        except Exception:
            logger.debug("Could not refresh exploration coverage", exc_info=True)


def exploration_implies_partial(exploration: ExplorationResult | None) -> bool:
    if exploration is None:
        return False
    return exploration.status in {"failed", "partial"} and exploration.status != "skipped"
