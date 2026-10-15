"""Phase 9: unified analyze-apk job response (backward-compatible).

Builds the public GET payload shape while preserving existing ``json_analysis``
and exploration fields. Never includes base64 / image binaries.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any


def public_job_status(status_value: str) -> str:
    """Map internal statuses onto the Phase 9 public contract."""
    raw = (status_value or "").strip().lower()
    if raw in {"running", "processing"}:
        return "processing"
    if raw == "queued":
        return "queued"
    return raw


def _page_name(state: dict[str, Any]) -> str:
    label = (state.get("label") or "").strip()
    if label and label.lower() not in {"entry", "after_human"}:
        return label
    activity = state.get("activity") or ""
    if "/" in activity:
        activity = activity.rsplit("/", 1)[-1]
    if "." in activity:
        activity = activity.rsplit(".", 1)[-1]
    return activity or "unknown"


def _bbox_from_placement(placement: dict[str, Any], shot: dict[str, Any]) -> dict[str, int] | None:
    bounds = placement.get("bounds") if isinstance(placement, dict) else None
    if isinstance(bounds, dict):
        left = int(bounds.get("left") or 0)
        top = int(bounds.get("top") or 0)
        right = int(bounds.get("right") or 0)
        bottom = int(bounds.get("bottom") or 0)
        return {
            "x": left,
            "y": top,
            "width": max(0, right - left),
            "height": max(0, bottom - top),
        }
    rel = placement.get("relative_bbox") if isinstance(placement, dict) else None
    width = shot.get("width")
    height = shot.get("height")
    if (
        isinstance(rel, (list, tuple))
        and len(rel) >= 4
        and isinstance(width, int)
        and isinstance(height, int)
        and width > 0
        and height > 0
    ):
        left, top, w, h = (float(rel[0]), float(rel[1]), float(rel[2]), float(rel[3]))
        return {
            "x": int(round(left * width)),
            "y": int(round(top * height)),
            "width": int(round(w * width)),
            "height": int(round(h * height)),
        }
    return None


def _confidence_value(raw: Any) -> float | None:
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        mapping = {"HIGH": 0.9, "MEDIUM": 0.65, "LOW": 0.4}
        return mapping.get(raw.upper())
    return None


def _ad_block(state: dict[str, Any], shot: dict[str, Any]) -> dict[str, Any]:
    placements = list(state.get("ad_placements") or [])
    placement = placements[0] if placements else None
    if isinstance(placement, dict) and placement.get("ad_detected"):
        return {
            "detected": True,
            "type": placement.get("ad_type") or "unknown",
            "position": placement.get("position"),
            "confidence": _confidence_value(placement.get("confidence")),
            "bounding_box": _bbox_from_placement(placement, shot),
        }
    if shot.get("ad_detected"):
        return {
            "detected": True,
            "type": shot.get("ad_type") or "unknown",
            "position": shot.get("ad_position"),
            "confidence": shot.get("confidence"),
            "bounding_box": None,
        }
    return {
        "detected": False,
        "type": None,
        "position": None,
        "confidence": None,
        "bounding_box": None,
    }


def build_screenshots_section(exploration: dict[str, Any] | None) -> dict[str, Any]:
    """Phase 9 ``screenshots`` object grouped by page (no image bytes)."""
    if not exploration:
        return {
            "status": "skipped",
            "total": 0,
            "pages": [],
            "error": None,
        }

    status = exploration.get("status") or "partial"
    reason = exploration.get("reason")
    if status == "failed":
        return {
            "status": "failed",
            "total": 0,
            "pages": [],
            "error": reason or "Screenshot exploration failed.",
        }
    if status == "skipped":
        return {
            "status": "skipped",
            "total": 0,
            "pages": [],
            "error": reason,
        }

    pages: "OrderedDict[str, list[dict[str, Any]]]" = OrderedDict()
    states = list(exploration.get("states") or [])
    for index, state in enumerate(states, start=1):
        if not isinstance(state, dict):
            continue
        page = _page_name(state)
        shot = state.get("screenshot") if isinstance(state.get("screenshot"), dict) else {}
        state_id = state.get("state_id") or shot.get("state_id") or f"state_{index:03d}"
        shot_id = (
            shot.get("screenshot_id")
            or f"{page.lower().replace(' ', '_')}_{len(pages.get(page, []))+1:03d}"
        )
        entry = {
            "id": shot_id,
            "state_id": state_id,
            "s3_key": shot.get("s3_key"),
            "s3_url": shot.get("url") or shot.get("s3_url"),
            "width": shot.get("width"),
            "height": shot.get("height"),
            "triggering_action": shot.get("triggering_action")
            or (
                (state.get("inbound_action") or {}).get("kind")
                if isinstance(state.get("inbound_action"), dict)
                else None
            ),
            "ad": _ad_block(state, shot),
        }
        pages.setdefault(page, []).append(entry)

    # Fallback: screenshot_records / flat screenshots list when states empty.
    if not pages:
        for index, shot in enumerate(exploration.get("screenshots") or [], start=1):
            if not isinstance(shot, dict):
                continue
            page = shot.get("page") or "unknown"
            entry = {
                "id": shot.get("screenshot_id") or f"{page}_{index:03d}",
                "state_id": shot.get("state_id") or f"state_{index:03d}",
                "s3_key": shot.get("s3_key"),
                "s3_url": shot.get("url") or shot.get("s3_url"),
                "width": shot.get("width"),
                "height": shot.get("height"),
                "triggering_action": shot.get("triggering_action"),
                "ad": {
                    "detected": bool(shot.get("ad_detected")),
                    "type": shot.get("ad_type"),
                    "position": shot.get("ad_position"),
                    "confidence": shot.get("confidence"),
                    "bounding_box": None,
                },
            }
            pages.setdefault(str(page), []).append(entry)

    total = sum(len(items) for items in pages.values())
    page_list = [{"page": name, "screenshots": items} for name, items in pages.items()]
    out_status = "completed" if status == "completed" else "partial"
    return {
        "status": out_status,
        "total": total,
        "pages": page_list,
        "error": reason if out_status == "partial" and reason else None,
    }


def build_apk_summary(
    *,
    result: dict[str, Any] | None,
    file_name: str | None,
    package_name: str | None,
) -> dict[str, Any]:
    data = (result or {}).get("data") if isinstance(result, dict) else None
    apk = data.get("apk") if isinstance(data, dict) else None
    if not isinstance(apk, dict):
        apk = {}
    return {
        "name": apk.get("file_name") or file_name,
        "package": apk.get("package_name") or package_name,
    }


def build_analysis_section(result: dict[str, Any] | None) -> dict[str, Any] | None:
    """Existing static analysis JSON fields (exploration stripped to avoid duplication)."""
    if not isinstance(result, dict):
        return None
    data = result.get("data")
    if not isinstance(data, dict):
        return {
            "schema_version": result.get("schema_version"),
            "status": result.get("status"),
        }
    analysis = {key: value for key, value in data.items() if key != "exploration"}
    return {
        "schema_version": result.get("schema_version"),
        "status": result.get("status"),
        **analysis,
    }


def enrich_job_public_payload(
    body: dict[str, Any],
    *,
    result: dict[str, Any] | None,
    file_name: str | None = None,
    package_name: str | None = None,
) -> dict[str, Any]:
    """Attach Phase 9 unified fields onto an existing public payload."""
    status = body.get("status")
    body["status"] = public_job_status(str(status or ""))

    if body["status"] not in {
        "completed",
        "partial",
        "cancelled",
        "timeout",
    }:
        return body

    if result is None:
        return body

    data = result.get("data") if isinstance(result, dict) else None
    exploration = data.get("exploration") if isinstance(data, dict) else None

    body["success"] = body["status"] in {"completed", "partial", "cancelled", "timeout"}
    body["apk"] = build_apk_summary(
        result=result, file_name=file_name, package_name=package_name
    )
    body["analysis"] = build_analysis_section(result)
    # Preserve full existing document for legacy clients.
    body["json_analysis"] = result
    body["schema_version"] = result.get("schema_version")

    screenshots = build_screenshots_section(exploration if isinstance(exploration, dict) else None)
    body["screenshots"] = screenshots
    # Keep raw exploration under its own key (was previously aliased as screenshots).
    if isinstance(exploration, dict):
        body["exploration"] = exploration

    # If exploration failed but static JSON exists, surface partial clearly.
    if body["status"] == "completed" and isinstance(exploration, dict):
        if exploration.get("status") == "failed":
            body["status"] = "partial"
            body["success"] = True
            screenshots["status"] = "failed"
            screenshots["error"] = exploration.get("reason") or screenshots.get("error")
            body["screenshots"] = screenshots

    return body
