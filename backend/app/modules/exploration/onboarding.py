"""First-run screens a person clears without thinking: language selection first.

The general planner ranks taps by label and role, with no idea that a screen full of
language names wants "pick one, then confirm". Without that it can wander onto
whatever else is tappable, including the ads that sit on these screens. This
module recognises a language-selection screen and plans the two steps a person
would take: choose a language (English when present), then press the confirm button.
"""

from __future__ import annotations

import re
from typing import Sequence

from app.modules.exploration.action_planner import (
    PlannedAction,
    _ad_text_regions,
    _element_action_key,
    _is_ad_cta,
    _is_ad_surface,
    _is_banner_ad_slot,
)
from app.modules.exploration.actions import TapAction
from app.modules.exploration.ui_element import UIElement

_LANGUAGE_NAMES = (
    "english", "hindi", "spanish", "español", "espanol", "french", "français", "francais",
    "german", "deutsch", "portuguese", "português", "portugues", "italian", "italiano",
    "russian", "русский", "arabic", "العربية", "chinese", "中文", "japanese", "日本語",
    "korean", "한국어", "turkish", "türkçe", "turkce", "indonesian", "bahasa", "bengali",
    "বাংলা", "telugu", "తెలుగు", "tamil", "தமிழ்", "marathi", "मराठी", "gujarati",
    "ગુજરાતી", "urdu", "اردو", "dutch", "nederlands", "polish", "polski", "thai",
    "ไทย", "vietnamese", "tiếng việt", "hindi (", "हिन्दी", "punjabi", "ਪੰਜਾਬੀ",
)
_LANG_ACTIVITY_RX = re.compile(r"(language|locale|chooselang|selectlang|langsel)", re.IGNORECASE)
_LANG_ID_RX = re.compile(r"(language|lang_|_lang|locale)", re.IGNORECASE)
_CONFIRM_RX = re.compile(
    r"^(done|continue|next|apply|save|ok|confirm|get started|start|let'?s go|proceed|submit|✓|✔)$",
    re.IGNORECASE,
)
_CONFIRM_ID_RX = re.compile(
    r"(btn_done|btn_next|btn_continue|btn_ok|btn_apply|btn_save|confirm|done_btn|next_btn|continue_btn)",
    re.IGNORECASE,
)


def _label(el: UIElement) -> str:
    return (el.text or el.content_description or "").strip()


def _is_language_name(label: str) -> bool:
    lowered = label.lower()
    if not lowered or len(lowered) > 40:
        return False
    return any(lowered == name or lowered.startswith(name) for name in _LANGUAGE_NAMES)


def _language_rows(elements: Sequence[UIElement]) -> list[UIElement]:
    return [el for el in elements if el.visible and el.enabled and _is_language_name(_label(el))]


def looks_like_language_screen(elements: Sequence[UIElement], *, activity: str | None = None) -> bool:
    """True when the screen is asking the user to choose a language."""
    rows = _language_rows(elements)
    if len(rows) >= 3:
        return True
    if activity and _LANG_ACTIVITY_RX.search(activity) and len(rows) >= 2:
        return True
    return bool(len(rows) >= 2 and any(el.resource_id and _LANG_ID_RX.search(el.resource_id) for el in elements))


def _is_ad(el: UIElement, screen_size: tuple[int, int] | None, ad_regions: list) -> bool:
    return (
        _is_ad_cta(el)
        or _is_ad_surface(el, screen_size=screen_size)
        or _is_banner_ad_slot(el, screen_size=screen_size, ad_regions=ad_regions)
    )


def _planned(el: UIElement, *, priority: int, tag: str) -> PlannedAction:
    return PlannedAction(
        key=_element_action_key("tap", el),
        action=TapAction(element=el),
        kind="tap",
        priority=priority,
        label=el.label(),
        meta={
            "text": el.text,
            "resource_id": el.resource_id,
            "bounds": list(el.bounds),
            "tag": tag,
            "is_onboarding_cta": True,
            "is_ad_cta": False,
        },
    )


def plan_language_actions(
    elements: Sequence[UIElement],
    *,
    screen_size: tuple[int, int] | None = None,
    skip_keys: set[str] | None = None,
) -> list[PlannedAction]:
    """Choose a language (English first), then confirm. Never taps ads."""
    skip = skip_keys or set()
    ad_regions = _ad_text_regions(elements)
    planned: list[PlannedAction] = []

    rows = [el for el in _language_rows(elements) if not _is_ad(el, screen_size, ad_regions)]
    rows.sort(key=lambda el: (0 if _label(el).lower().startswith("english") else 1, el.top, el.left))
    if rows:
        first = _planned(rows[0], priority=230, tag="language_select")
        if first.key not in skip:
            planned.append(first)

    for el in elements:
        if not (el.clickable and el.enabled and el.visible):
            continue
        if _is_ad(el, screen_size, ad_regions):
            continue
        label = _label(el)
        rid = el.resource_id or ""
        if (label and _CONFIRM_RX.match(label)) or (rid and _CONFIRM_ID_RX.search(rid)):
            item = _planned(el, priority=220, tag="language_confirm")
            if item.key not in skip:
                planned.append(item)

    planned.sort(key=lambda item: -item.priority)
    return planned
