"""Phase 12A — ObservationBuilder (read-only assembly of existing subsystem outputs).

Does not call ADB, execute taps, capture screenshots, or alter StateDetector.
All inputs are supplied by the exploration loop / callers.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

from app.modules.exploration.observation import Observation, new_observation_id
from app.modules.exploration.ui_element import UIElement

logger = logging.getLogger(__name__)

# Cap hierarchy size in Observation to keep session memory bounded.
_MAX_UI_ELEMENTS = 120
_MAX_CLICKABLES = 60
_MAX_VISIBLE_TEXT = 80


def _element_to_dict(el: UIElement) -> dict[str, Any]:
    left, top, right, bottom = el.bounds
    return {
        "text": el.text or None,
        "content_description": el.content_description or None,
        "resource_id": el.resource_id or None,
        "class_name": el.class_name or None,
        "package": el.package or None,
        "clickable": bool(el.clickable),
        "enabled": bool(el.enabled),
        "scrollable": bool(el.scrollable),
        "visible": bool(el.visible),
        "selected": bool(el.selected),
        "checked": bool(el.checked),
        "focused": bool(el.focused),
        "focusable": bool(el.focusable),
        "bounds": {
            "left": int(left),
            "top": int(top),
            "right": int(right),
            "bottom": int(bottom),
        },
    }


def _visible_text_from_elements(elements: Sequence[UIElement]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for el in elements:
        if not el.visible:
            continue
        for raw in (el.text, el.content_description):
            text = (raw or "").strip()
            if not text or len(text) > 120:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(text)
            if len(out) >= _MAX_VISIBLE_TEXT:
                return out
    return out


def _clickables_from_elements(elements: Sequence[UIElement]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for el in elements:
        if not (el.clickable and el.enabled and el.visible):
            continue
        out.append(_element_to_dict(el))
        if len(out) >= _MAX_CLICKABLES:
            break
    return out


def _ui_elements_from_elements(elements: Sequence[UIElement]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for el in elements[:_MAX_UI_ELEMENTS]:
        out.append(_element_to_dict(el))
    return out


def _webview_detected(elements: Sequence[UIElement]) -> bool:
    for el in elements:
        cls = (el.class_name or "").lower()
        if "webview" in cls:
            return True
    return False


def _normalize_ads(ad_results: Sequence[Any] | None) -> list[dict[str, Any]]:
    if not ad_results:
        return []
    out: list[dict[str, Any]] = []
    for item in ad_results:
        try:
            if hasattr(item, "to_dict"):
                payload = item.to_dict()
            elif isinstance(item, dict):
                payload = dict(item)
            else:
                continue
            # Drop bulky raw blobs from Observation (keep evidence/summary).
            payload.pop("raw", None)
            if payload.get("detected") is False and not payload.get("evidence"):
                continue
            out.append(payload)
        except Exception:
            continue
    return out


def _normalize_hitl(hitl: Any | None) -> tuple[bool, str | None, str | None, dict[str, Any]]:
    if hitl is None:
        return False, None, None, {"required": False}
    try:
        if hasattr(hitl, "to_dict"):
            payload = hitl.to_dict()
        elif isinstance(hitl, dict):
            payload = dict(hitl)
        else:
            return False, None, None, {"required": False}
        required = bool(payload.get("required"))
        hitl_type = payload.get("type")
        message = payload.get("message") or payload.get("title")
        return required, (str(hitl_type) if hitl_type else None), (
            str(message) if message else None
        ), payload
    except Exception:
        return False, None, None, {"required": False}


def build_observation(
    *,
    package_name: str | None = None,
    activity: str | None = None,
    elements: Sequence[UIElement] | None = None,
    screen_size: tuple[int, int] | None = None,
    state_id: str | None = None,
    screenshot: Any | None = None,
    screenshot_path: str | None = None,
    screenshot_url: str | None = None,
    screenshot_id: str | None = None,
    ad_results: Sequence[Any] | None = None,
    hitl: Any | None = None,
    metadata: dict[str, Any] | None = None,
    observation_id: str | None = None,
) -> Observation:
    """Assemble a read-only Observation from already-collected subsystem outputs."""
    elements = list(elements or [])
    width = height = None
    if screen_size and len(screen_size) >= 2:
        width = int(screen_size[0]) or None
        height = int(screen_size[1]) or None

    path = screenshot_path
    url = screenshot_url
    sid = screenshot_id
    if screenshot is not None:
        try:
            path = path or getattr(screenshot, "local_path", None)
            url = url or getattr(screenshot, "s3_url", None)
            sid = sid or getattr(screenshot, "state_id", None)
            if width is None:
                width = getattr(screenshot, "width", None)
            if height is None:
                height = getattr(screenshot, "height", None)
        except Exception:
            pass

    hitl_required, hitl_type, hitl_message, hitl_payload = _normalize_hitl(hitl)
    ads = _normalize_ads(ad_results)

    meta = dict(metadata or {})
    # Never allow secrets into metadata even if a caller slips.
    for banned in ("api_key", "password", "otp", "token", "secret", "authorization"):
        meta.pop(banned, None)

    return Observation(
        observation_id=observation_id or new_observation_id(),
        package_name=package_name,
        activity=activity,
        screenshot_path=path,
        screenshot_url=url,
        screenshot_id=sid,
        screen_width=width,
        screen_height=height,
        state_id=state_id,
        visible_text=_visible_text_from_elements(elements),
        clickable_elements=_clickables_from_elements(elements),
        ui_elements=_ui_elements_from_elements(elements),
        detected_ads=ads,
        hitl_required=hitl_required,
        hitl_type=hitl_type,
        hitl_message=hitl_message,
        hitl=hitl_payload,
        webview_detected=_webview_detected(elements),
        metadata=meta,
    )


def emit_observation_log(observation: Observation) -> None:
    """INFO: counts only. DEBUG: richer (still no secrets)."""
    from app.modules.exploration.log_tags import log_observation

    log_observation(
        "id=%s state=%s activity=%s elements=%s clickable=%s ads=%s hitl=%s webview=%s",
        observation.observation_id,
        observation.state_id or "-",
        (observation.activity or "-")[-80:],
        len(observation.ui_elements),
        len(observation.clickable_elements),
        len(observation.detected_ads),
        observation.hitl_required,
        observation.webview_detected,
    )
    logger.debug(
        "observation detail id=%s visible_text_count=%s hitl_type=%s meta_keys=%s",
        observation.observation_id,
        len(observation.visible_text),
        observation.hitl_type,
        sorted(observation.metadata.keys()),
    )
