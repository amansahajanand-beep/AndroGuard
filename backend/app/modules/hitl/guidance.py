"""Build clear operator-facing HITL instructions from screen context."""

from __future__ import annotations

import re
from typing import Sequence

from app.modules.exploration.ui_element import UIElement
from app.modules.hitl.intervention_types import InterventionType


def _is_edit_text(el: UIElement) -> bool:
    cls = (el.class_name or "").lower()
    rid = (el.resource_id or "").lower()
    if (
        "edittext" in cls
        or "autocompletetextview" in cls
        or "textinputedittext" in cls
        or "searchview" in cls
    ):
        return True
    if el.focusable and any(
        token in rid for token in ("edit", "input", "name", "title", "search", "query")
    ):
        return True
    return False


def _is_spinner_or_picker(el: UIElement) -> bool:
    cls = (el.class_name or "").lower()
    text = f"{el.text} {el.content_description}".lower()
    return (
        "spinner" in cls
        or "numberpicker" in cls
        or "datepicker" in cls
        or "timepicker" in cls
        or bool(re.search(r"\b(select|choose|pick|dropdown)\b", text))
    )


def summarize_inputs(elements: Sequence[UIElement]) -> dict[str, list[str]]:
    """Collect editable fields, selectable controls, and primary CTAs."""
    fields: list[str] = []
    selectors: list[str] = []
    ctas: list[str] = []
    for el in elements:
        if not el.visible or not el.enabled:
            continue
        label = (el.text or el.content_description or el.resource_id or "").strip()
        short = label[-80:] if label else ""
        if _is_edit_text(el):
            fields.append(short or "text field")
        elif _is_spinner_or_picker(el) or (
            el.clickable and short and re.search(r"\b(select|choose|pick)\b", short, re.I)
        ):
            selectors.append(short or "option picker")
        elif el.clickable and short and re.search(
            r"^(create|add|save|done|next|continue|ok|submit|finish|start|set)$",
            short,
            re.I,
        ):
            ctas.append(short)
    # de-dupe preserving order
    def _uniq(items: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for item in items:
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
            if len(out) >= 6:
                break
        return out

    return {
        "fields": _uniq(fields),
        "selectors": _uniq(selectors),
        "ctas": _uniq(ctas),
    }


def default_steps_for(kind: InterventionType) -> list[str]:
    return {
        InterventionType.TERMS_CONSENT: [
            "In the emulator, review the terms if needed.",
            "Tap Agree / Accept / Continue on that screen.",
            "Return here and click Continue.",
        ],
        InterventionType.PRIVACY_CONSENT: [
            "In the emulator, review the privacy policy if needed.",
            "Tap Agree / Accept / Continue.",
            "Return here and click Continue.",
        ],
        InterventionType.PERMISSION: [
            "In the emulator, choose Allow (or Deny if you prefer).",
            "Return here and click Continue.",
        ],
        InterventionType.DEFAULT_APP: [
            "In the emulator, pick the default app (or Cancel).",
            "Return here and click Continue.",
        ],
        InterventionType.SYSTEM_SETTINGS: [
            "In the emulator, complete the system prompt / toggle.",
            "Return here and click Continue.",
        ],
        InterventionType.LOGIN: [
            "In the emulator, type email/username and password with the keyboard.",
            "Tap Sign in / Log in (or Skip if available).",
            "Return here and click Continue.",
        ],
        InterventionType.OTP: [
            "In the emulator, type the verification code with the keyboard.",
            "Tap Verify / Submit.",
            "Return here and click Continue.",
        ],
        InterventionType.CAPTCHA: [
            "In the emulator, complete the CAPTCHA / image challenge.",
            "Return here and click Continue.",
        ],
        InterventionType.VERIFICATION: [
            "In the emulator, finish account/device verification.",
            "Return here and click Continue.",
        ],
        InterventionType.FORM_INPUT: [
            "In the emulator, tap each empty text field.",
            "Type the required values with the keyboard.",
            "Tap Save / Next / Done when finished.",
            "Return here and click Continue.",
        ],
        InterventionType.SELECTION: [
            "In the emulator, tap the dropdown / list item to select.",
            "Confirm with OK / Next / Done if shown.",
            "Return here and click Continue.",
        ],
        InterventionType.CREATE_CONTENT: [
            "In the emulator, fill name/title and any required fields (keyboard).",
            "Select options (time, category, etc.) if shown.",
            "Tap Create / Add / Save.",
            "Return here and click Continue.",
        ],
        InterventionType.UNKNOWN_BLOCKING_SCREEN: [
            "Look at the emulator screenshot below.",
            "Complete whatever the app is asking (tap, type, or select).",
            "Return here and click Continue.",
        ],
    }.get(
        kind,
        [
            "Complete the required action in the emulator.",
            "Return here and click Continue.",
        ],
    )


def build_guidance(
    *,
    kind: InterventionType,
    title: str,
    elements: Sequence[UIElement] | None = None,
    labels: Sequence[str] | None = None,
    base_suggested: str | None = None,
) -> tuple[str, str, list[str]]:
    """Return ``(message, suggested_action, steps)`` for the operator UI."""
    summary = summarize_inputs(elements or [])
    fields = summary["fields"]
    selectors = summary["selectors"]
    ctas = summary["ctas"]
    steps = list(default_steps_for(kind))

    # Contextualize steps when we can see fields / selectors on screen.
    if fields and kind in {
        InterventionType.FORM_INPUT,
        InterventionType.CREATE_CONTENT,
        InterventionType.LOGIN,
        InterventionType.OTP,
        InterventionType.UNKNOWN_BLOCKING_SCREEN,
    }:
        preview = ", ".join(fields[:3])
        steps[0] = f"In the emulator, tap these fields and type with the keyboard: {preview}."
    if selectors and kind in {
        InterventionType.SELECTION,
        InterventionType.CREATE_CONTENT,
        InterventionType.UNKNOWN_BLOCKING_SCREEN,
        InterventionType.DEFAULT_APP,
    }:
        preview = ", ".join(selectors[:3])
        insert = f"Select from: {preview}."
        if len(steps) >= 2:
            steps.insert(1, insert)
        else:
            steps.append(insert)
    if ctas:
        steps.insert(
            max(0, len(steps) - 1),
            f"When finished, tap {ctas[0]} on the emulator screen.",
        )

    # De-dupe consecutive identical steps.
    cleaned: list[str] = []
    for step in steps:
        if cleaned and cleaned[-1] == step:
            continue
        cleaned.append(step)
    steps = cleaned[:6]

    label_hint = ""
    if labels:
        sample = [lab for lab in labels[:5] if lab]
        if sample:
            label_hint = " On-screen: " + " · ".join(sample) + "."

    messages = {
        InterventionType.FORM_INPUT: (
            "This screen needs keyboard input (name, title, or other text fields)."
            " The explorer cannot type for you."
        ),
        InterventionType.SELECTION: (
            "This screen needs you to choose an option from a list or dropdown."
            " The explorer will not guess the selection."
        ),
        InterventionType.CREATE_CONTENT: (
            "The app is asking you to create or set something up"
            " (type a name, pick options, then save)."
        ),
        InterventionType.LOGIN: (
            "Sign-in is required. Type credentials in the emulator with the keyboard."
        ),
        InterventionType.OTP: (
            "Enter the one-time / verification code in the emulator keyboard."
        ),
        InterventionType.UNKNOWN_BLOCKING_SCREEN: (
            "Exploration paused on a screen that needs a human decision"
            " (tap, type, or select)."
        ),
    }
    message = messages.get(
        kind,
        f"{title}: complete this step in the emulator, then click Continue here.",
    )
    message = message + label_hint

    suggested = base_suggested
    if not suggested:
        if kind is InterventionType.FORM_INPUT:
            suggested = "Type the required fields in the emulator keyboard, then Save/Next"
        elif kind is InterventionType.SELECTION:
            suggested = "Select the required option in the emulator, then confirm"
        elif kind is InterventionType.CREATE_CONTENT:
            suggested = "Create/setup in the emulator (type + select), then Save/Create"
        else:
            suggested = f"{title} — finish it in the emulator, then click Continue"
    if fields and kind in {
        InterventionType.FORM_INPUT,
        InterventionType.CREATE_CONTENT,
        InterventionType.LOGIN,
    }:
        suggested = f"Type into: {', '.join(fields[:3])} — then continue in the emulator"
    elif selectors and kind is InterventionType.SELECTION:
        suggested = f"Select: {', '.join(selectors[:3])} — then continue in the emulator"

    return message, suggested, steps
