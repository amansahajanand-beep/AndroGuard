"""Auto-assist for gates the explorer can clear without a human.

Handles permissions, default-app, terms/privacy Agree, form/select/create,
and ad close/skip. Login / OTP / CAPTCHA / verification stay on HITL.

Actions are always chosen from allow-listed PlannedAction candidates.
When AI is enabled it may rank candidates; otherwise the highest-priority
deterministic candidate is used.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Sequence

from app.core.config import settings
from app.modules.exploration.action_planner import (
    PlannedAction,
    _element_action_key,
    _is_ad_cta,
    _is_ad_surface,
    _is_banner_ad_slot,
    _is_close_control,
    _is_home_hijack_cta,
    _is_primary_submit_cta,
    _ad_text_regions,
    looks_like_interstitial_ad,
)
from app.modules.exploration.actions import BackAction, TapAction, TypeTextAction
from app.modules.exploration.ui_element import UIElement
from app.modules.hitl.intervention_types import DetectionResult, InterventionType

logger = logging.getLogger(__name__)

# Screens we try to clear automatically (AI + deterministic).
AI_ASSISTABLE_TYPES: frozenset[InterventionType] = frozenset(
    {
        InterventionType.FORM_INPUT,
        InterventionType.SELECTION,
        InterventionType.CREATE_CONTENT,
        InterventionType.PERMISSION,
        InterventionType.DEFAULT_APP,
        InterventionType.TERMS_CONSENT,
        InterventionType.PRIVACY_CONSENT,
        InterventionType.SYSTEM_SETTINGS,
        InterventionType.UNKNOWN_BLOCKING_SCREEN,
    }
)

# True human-only: secrets / challenges.
HITL_ONLY_TYPES: frozenset[InterventionType] = frozenset(
    {
        InterventionType.LOGIN,
        InterventionType.OTP,
        InterventionType.CAPTCHA,
        InterventionType.VERIFICATION,
    }
)

_FORM_TYPES = frozenset(
    {
        InterventionType.FORM_INPUT,
        InterventionType.CREATE_CONTENT,
    }
)

_ALLOW_RX = re.compile(
    r"^(allow|allow all|while using the app|only this time|allow once|"
    r"accept|agree|i agree|agree and continue|continue|ok|got it|next)$",
    re.I,
)
_DENY_RX = re.compile(
    r"^(don'?t allow|deny|reject|decline|cancel|no|not now)$",
    re.I,
)
_CONSENT_RX = re.compile(
    r"^(agree|accept|i agree|agree and continue|continue|ok|got it|next|start)$",
    re.I,
)
_DEFAULT_RX = re.compile(
    r"(set as default|set default|always|use this app|make default)",
    re.I,
)
# Never grant HOME/launcher during exploration — dismiss these gates.
_DEFAULT_DISMISS_RX = re.compile(
    r"^(cancel|not now|no thanks|skip|dismiss|close|don'?t ask again)$",
    re.I,
)
_CTA_RX = re.compile(
    r"^(create|add|save|done|next|continue|ok|submit|finish|start|set|select|choose)$",
    re.I,
)
_SKIP_AD_RX = re.compile(
    r"^(close|close ad|skip|skip ad|skip video|no thanks|not now|maybe later|"
    r"dismiss|×|x)$",
    re.I,
)
_PLACEHOLDER_RX = re.compile(
    r"^(alarm name|name|title|label|enter name|enter title|type here|hint)$",
    re.I,
)
_OUR_FILL_RX = re.compile(r"^(test( item| alarm| user)?|test@example\.com|9999999999)$", re.I)


def is_ai_assistable(detection: DetectionResult | None) -> bool:
    if detection is None or not detection.required or detection.type is None:
        return False
    if detection.type in HITL_ONLY_TYPES:
        return False
    return detection.type in AI_ASSISTABLE_TYPES


def _default_text_for_field(label: str, *, detection: DetectionResult | None) -> str:
    blob = (label or "").lower()
    if "email" in blob:
        return "test@example.com"
    if "phone" in blob or "mobile" in blob:
        return "9999999999"
    if "name" in blob or "title" in blob or "label" in blob or "alarm" in blob:
        if detection and detection.type is InterventionType.CREATE_CONTENT:
            return "Test Alarm"
        return "Test User"
    if detection and detection.type is InterventionType.CREATE_CONTENT:
        return "Test Item"
    return "Test"


def _is_edit_text(el: UIElement) -> bool:
    cls = (el.class_name or "").lower()
    rid = (el.resource_id or "").lower()
    if any(token in cls for token in ("edittext", "autocompletetextview", "textinputedittext")):
        return True
    if el.focusable and any(token in rid for token in ("edit", "input", "name", "title")):
        return True
    return False


def _label(el: UIElement) -> str:
    return (el.text or el.content_description or "").strip()


def _field_needs_text(el: UIElement) -> bool:
    """True when the edit field still looks empty / placeholder."""
    text = (el.text or "").strip()
    if not text:
        return True
    if _PLACEHOLDER_RX.match(text):
        return True
    if _OUR_FILL_RX.match(text):
        return False
    # Already has real content — don't retype.
    return False


def _add_tap(
    planned: list[PlannedAction],
    seen: set[str],
    el: UIElement,
    *,
    priority: int,
    tag: str,
) -> None:
    key = _element_action_key("tap", el)
    if key in seen:
        return
    seen.add(key)
    planned.append(
        PlannedAction(
            key=key,
            action=TapAction(element=el),
            kind="tap",
            priority=priority,
            label=(_label(el) or tag)[:60],
            meta={"source": "ai_assist", "tag": tag},
        )
    )


def plan_ai_assist_actions(
    elements: Sequence[UIElement],
    *,
    detection: DetectionResult | None = None,
    target_package: str | None = None,
    screen_size: tuple[int, int] | None = None,
    prefer_submit: bool = False,
) -> list[PlannedAction]:
    """Build allow-listed tap / type_text candidates for auto-assist."""
    planned: list[PlannedAction] = []
    seen: set[str] = set()
    kind = detection.type if detection else None
    pkg_token = (target_package or "").rsplit(".", 1)[-1].lower() if target_package else ""
    ad_regions = _ad_text_regions(elements)

    # --- Permission / consent / default / ad-close taps (high priority) ---
    for el in elements:
        if not (el.clickable and el.enabled and el.visible):
            continue
        if (
            _is_ad_cta(el)
            or _is_ad_surface(el, screen_size=screen_size)
            or _is_banner_ad_slot(el, screen_size=screen_size, ad_regions=ad_regions)
        ):
            continue
        label = _label(el)
        rid = (el.resource_id or "").lower()

        if _is_close_control(el, screen_size=screen_size) or (
            label and _SKIP_AD_RX.match(label)
        ):
            _add_tap(planned, seen, el, priority=125, tag="close_ad")
            continue

        if kind is InterventionType.PERMISSION or "permission" in rid:
            if label and _ALLOW_RX.match(label):
                _add_tap(planned, seen, el, priority=120, tag="permission_allow")
                continue
            if "permission_allow" in rid or "allow_button" in rid:
                _add_tap(planned, seen, el, priority=118, tag="permission_allow")
                continue
            if label and _DENY_RX.match(label):
                _add_tap(planned, seen, el, priority=10, tag="permission_deny")
                continue

        if kind in {
            InterventionType.TERMS_CONSENT,
            InterventionType.PRIVACY_CONSENT,
            InterventionType.UNKNOWN_BLOCKING_SCREEN,
        }:
            if label and _CONSENT_RX.match(label):
                _add_tap(planned, seen, el, priority=115, tag="consent_agree")
                continue

        if kind is InterventionType.DEFAULT_APP or _is_home_hijack_cta(el):
            if str(getattr(settings, "default_app_policy", "dismiss")).lower() == "grant":
                # Operator opted in: accept the default / role picker for the app under test.
                blob = f"{label} {rid}".lower()
                if label and _DEFAULT_RX.search(label):
                    _add_tap(planned, seen, el, priority=150, tag="default_app_grant")
                    continue
                if pkg_token and pkg_token in blob:
                    _add_tap(planned, seen, el, priority=145, tag="default_app_pick_app")
                    continue
                if label and re.match(r"^(ok|done|confirm)$", label, re.I):
                    _add_tap(planned, seen, el, priority=140, tag="default_app_confirm")
                    continue
                continue
            # Exploration must NOT become the device Home launcher.
            # Prefer Cancel / Not now; never tap "Set as default".
            if label and _DEFAULT_DISMISS_RX.match(label):
                _add_tap(planned, seen, el, priority=140, tag="default_app_cancel")
                continue
            if label and _DEFAULT_RX.search(label):
                # Explicit demotion — do not add as candidate.
                continue
            # Ignore package rows that would lead to granting HOME.
            continue

        if kind is InterventionType.SYSTEM_SETTINGS and label and _ALLOW_RX.match(label):
            _add_tap(planned, seen, el, priority=112, tag="system_allow")

    empty_fields = 0
    # --- Form typing (only empty / placeholder fields) ---
    if kind in {
        InterventionType.FORM_INPUT,
        InterventionType.CREATE_CONTENT,
        InterventionType.UNKNOWN_BLOCKING_SCREEN,
        None,
    }:
        for el in elements:
            if not el.visible or not el.enabled:
                continue
            if not _is_edit_text(el):
                continue
            if not _field_needs_text(el):
                continue
            empty_fields += 1
            label = (_label(el) or el.resource_id or "field").strip()
            text = _default_text_for_field(label, detection=detection)
            key = _element_action_key("type_text", el)
            if key in seen:
                continue
            seen.add(key)
            # Below Save once we prefer submit; otherwise type first.
            planned.append(
                PlannedAction(
                    key=key,
                    action=TypeTextAction(text=text, element=el),
                    kind="type_text",
                    priority=50 if prefer_submit else 90,
                    label=f"type into {label[:40]}",
                    meta={"default_text": text, "field_label": label, "source": "ai_assist"},
                )
            )

    # --- Primary CTAs / selection ---
    for el in elements:
        if not (el.clickable and el.enabled and el.visible):
            continue
        if (
            _is_ad_cta(el)
            or _is_ad_surface(el, screen_size=screen_size)
            or _is_banner_ad_slot(el, screen_size=screen_size, ad_regions=ad_regions)
        ):
            continue
        label = _label(el)
        rid = (el.resource_id or "").lower()
        is_submit = _is_primary_submit_cta(el) or (bool(label) and _CTA_RX.match(label))
        if not label and not is_submit:
            continue
        priority = 0
        if kind in _FORM_TYPES and is_submit:
            # After typing (or when fields already filled), Save/Create wins.
            if prefer_submit or empty_fields == 0:
                priority = 145
            else:
                priority = 80  # below type_text (90) so we fill first
        elif label and _CTA_RX.match(label):
            priority = 85
        elif label and re.search(r"\b(select|choose|english|yes|ok)\b", label, re.I):
            priority = 70
        elif kind is InterventionType.SELECTION and label:
            priority = 60
        elif is_submit:
            priority = 80
        else:
            continue
        tag = "submit_cta" if is_submit else "cta"
        _add_tap(planned, seen, el, priority=priority, tag=tag)

    planned.sort(key=lambda item: (-item.priority, item.label))
    return planned[:28]


def plan_ad_dismiss_actions(
    elements: Sequence[UIElement],
    *,
    screen_size: tuple[int, int] | None = None,
) -> list[PlannedAction]:
    """Candidates that only close / skip ads (never Install / banner creatives)."""
    planned: list[PlannedAction] = []
    seen: set[str] = set()
    ad_regions = _ad_text_regions(elements)
    for el in elements:
        if not (el.clickable and el.enabled and el.visible):
            continue
        if _is_ad_cta(el):
            continue
        if _is_banner_ad_slot(el, screen_size=screen_size, ad_regions=ad_regions):
            continue
        if _is_ad_surface(el, screen_size=screen_size) and not _is_close_control(
            el, screen_size=screen_size
        ):
            continue
        label = _label(el)
        if _is_close_control(el, screen_size=screen_size) or (
            label and _SKIP_AD_RX.match(label)
        ):
            _add_tap(planned, seen, el, priority=100, tag="close_ad")
    planned.sort(key=lambda item: (-item.priority, item.label))
    return planned[:8]


def try_dismiss_ads(
    *,
    ui: Any,
    elements: Sequence[UIElement],
    screen_size: tuple[int, int] | None = None,
    activity: str | None = None,
    settle: Any | None = None,
    allow_back: bool = True,
) -> tuple[bool, str]:
    """Tap Close/Skip if present; otherwise Back on fullscreen ad creatives."""
    if not getattr(settings, "ai_assist_gates_enabled", True):
        return False, "disabled"
    candidates = plan_ad_dismiss_actions(elements, screen_size=screen_size)
    if candidates:
        selected = candidates[0]
        try:
            ui.perform(selected.action)
        except Exception as exc:
            return False, f"failed:{type(exc).__name__}"
        if settle is not None:
            try:
                settle()
            except Exception:
                pass
        return True, selected.label or selected.key

    if allow_back and looks_like_interstitial_ad(
        elements, activity=activity, screen_size=screen_size
    ):
        try:
            ui.perform(BackAction())
        except Exception as exc:
            return False, f"back_failed:{type(exc).__name__}"
        if settle is not None:
            try:
                settle()
            except Exception:
                pass
        return True, "back_on_interstitial"
    return False, "no_close_control"


def try_ai_assist(
    *,
    ui: Any,
    elements: Sequence[UIElement],
    detection: DetectionResult,
    activity: str | None,
    package_name: str | None,
    screen_size: tuple[int, int] | None = None,
    settle: Any | None = None,
    relaunch: Any | None = None,
) -> tuple[bool, list[str]]:
    """Attempt assist actions. Returns (cleared, notes)."""
    notes: list[str] = []
    if not getattr(settings, "ai_assist_gates_enabled", True):
        return False, ["ai_assist_gates_disabled"]
    if not is_ai_assistable(detection):
        return False, ["not_assistable"]

    max_steps = max(1, int(getattr(settings, "ai_assist_max_steps", 6) or 6))
    use_llm = bool(settings.ai_explorer_enabled)
    from app.modules.hitl.intervention_detector import InterventionDetector
    from app.modules.exploration.action_planner import is_home_launcher

    detector = InterventionDetector(target_package=package_name)
    current_elements = list(elements)
    current_detection = detection
    current_activity = activity
    typed_any = False
    tapped_submit = False
    prefer_submit = False

    for step in range(max_steps):
        # Home / launcher → swipe-right into default app (callback may soft-resume).
        if is_home_launcher(current_activity, target_package=package_name) and relaunch:
            try:
                relaunch()
                notes.append(f"step{step}:home_swipe_enter")
                if settle is not None:
                    settle()
            except Exception as exc:
                notes.append(f"step{step}:home_enter_failed:{type(exc).__name__}")
                return False, notes

        candidates = plan_ai_assist_actions(
            current_elements,
            detection=current_detection,
            target_package=package_name,
            screen_size=screen_size,
            prefer_submit=prefer_submit or typed_any,
        )
        if not candidates:
            # Default-home / launcher gates: NEVER press Back — that exits to the
            # system Nexus/Launcher home. Prefer swipe-right into default app.
            if current_detection.type is InterventionType.DEFAULT_APP:
                if relaunch is not None:
                    try:
                        relaunch()
                        notes.append(f"step{step}:home_swipe_default_app")
                        if settle is not None:
                            settle()
                        return True, notes
                    except Exception as exc:
                        notes.append(f"step{step}:home_enter_failed:{type(exc).__name__}")
                notes.append(f"step{step}:skip_default_app_no_back")
                return True, notes  # skip HITL; do not leave the app via Back
            notes.append(f"step{step}:no_candidates")
            break

        # After typing on create/form screens, force Save/Create before anything else.
        if (prefer_submit or typed_any) and current_detection.type in _FORM_TYPES:
            submit = [
                c
                for c in candidates
                if c.kind == "tap"
                and (
                    (c.meta or {}).get("tag") == "submit_cta"
                    or _CTA_RX.match((c.label or "").strip())
                    or (c.meta or {}).get("tag") == "cta"
                    and _is_primary_submit_like(c)
                )
            ]
            if submit:
                candidates = submit + [c for c in candidates if c not in submit]

        selected = candidates[0]
        if use_llm and not (
            (prefer_submit or typed_any)
            and current_detection.type in _FORM_TYPES
            and selected.kind == "tap"
            and (selected.meta or {}).get("tag") == "submit_cta"
        ):
            try:
                from app.modules.ai_explorer import run_decision_pipeline

                picked, meta = run_decision_pipeline(
                    candidates,
                    visited_keys=[],
                    activity=current_activity,
                    package_name=package_name,
                    stagnation_count=2,
                    force_ai=True,
                )
                if picked is not None:
                    selected = picked
                    if meta.get("ai_used"):
                        notes.append(f"step{step}:ai:{selected.kind}:{selected.key}")
                    else:
                        notes.append(f"step{step}:policy:{selected.kind}:{selected.key}")
                else:
                    notes.append(f"step{step}:deterministic:{selected.kind}")
            except Exception as exc:
                notes.append(f"step{step}:llm_fallback:{type(exc).__name__}")
        else:
            notes.append(f"step{step}:deterministic:{selected.kind}:{selected.key}")

        try:
            ui.perform(selected.action)
        except Exception as exc:
            notes.append(f"step{step}:execute_failed:{type(exc).__name__}")
            break

        if selected.kind == "type_text":
            typed_any = True
            prefer_submit = True
        elif selected.kind == "tap" and (
            (selected.meta or {}).get("tag") == "submit_cta"
            or _is_primary_submit_like(selected)
        ):
            tapped_submit = True

        if settle is not None:
            try:
                settle()
            except Exception:
                pass

        try:
            dump = ui.dump_ui(package=None)
            current_elements = list(getattr(dump, "elements", None) or current_elements)
            current_activity = getattr(dump, "activity", None) or current_activity
        except Exception:
            notes.append(f"step{step}:redump_failed")
            break

        again = detector.detect(
            elements=current_elements,
            package=package_name,
            activity=current_activity,
        )
        if not again.required:
            # Form screens: do not stop after typing — still need Save/Create.
            if (
                current_detection.type in _FORM_TYPES
                and typed_any
                and not tapped_submit
            ):
                submit_left = plan_ai_assist_actions(
                    current_elements,
                    detection=current_detection,
                    target_package=package_name,
                    screen_size=screen_size,
                    prefer_submit=True,
                )
                if any(
                    c.kind == "tap" and (c.meta or {}).get("tag") == "submit_cta"
                    for c in submit_left
                ):
                    prefer_submit = True
                    notes.append(f"step{step}:need_submit_cta")
                    continue
            notes.append("cleared")
            return True, notes
        if again.type in HITL_ONLY_TYPES:
            notes.append(f"escalated:{again.type.value if again.type else None}")
            return False, notes
        if not is_ai_assistable(again):
            notes.append(f"not_assistable_after:{again.type.value if again.type else None}")
            return False, notes
        current_detection = again

    return False, notes


def _is_primary_submit_like(planned: PlannedAction) -> bool:
    label = (planned.label or "").strip()
    if label and _CTA_RX.match(label):
        return True
    action = planned.action
    el = getattr(action, "element", None)
    if el is not None and _is_primary_submit_cta(el):
        return True
    return False
