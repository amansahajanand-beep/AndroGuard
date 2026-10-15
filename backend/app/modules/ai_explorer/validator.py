"""Validate AI decisions and map them onto deterministic PlannedAction objects."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Sequence

from pydantic import ValidationError

from app.modules.ai_explorer.schema import ALLOWED_ACTIONS, AIActionDecision
from app.modules.exploration.action_planner import PlannedAction, back_action
from app.modules.exploration.actions import MenuAction, TypeTextAction, WaitAction, sanitize_type_text

logger = logging.getLogger(__name__)

_JSON_BLOCK = re.compile(r"\{[^{}]*\}", re.DOTALL)


class ActionValidationError(ValueError):
    """Raised when an AI response cannot be safely mapped to an allowed action."""


def extract_json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        raise ActionValidationError("empty AI response")
    # Strip common markdown fences without executing anything.
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    data: Any = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_BLOCK.search(text)
        if not match:
            raise ActionValidationError("AI response is not a JSON object")
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise ActionValidationError("AI JSON parse failed") from exc
    if not isinstance(data, dict):
        raise ActionValidationError("AI JSON root must be an object")
    # Reject unexpected executable-looking keys.
    banned_keys = {
        "command",
        "shell",
        "adb",
        "code",
        "python",
        "script",
        "env",
        "credentials",
        "aws",
    }
    lowered = {str(k).lower() for k in data.keys()}
    if lowered & banned_keys:
        raise ActionValidationError("AI response contains disallowed keys")
    return data


def parse_ai_decision(raw: str | dict[str, Any]) -> AIActionDecision:
    if isinstance(raw, dict):
        data = raw
        banned_keys = {
            "command",
            "shell",
            "adb",
            "code",
            "python",
            "script",
            "env",
            "credentials",
            "aws",
        }
        lowered = {str(k).lower() for k in data.keys()}
        if lowered & banned_keys:
            raise ActionValidationError("AI response contains disallowed keys")
    else:
        data = extract_json_object(raw)
    # Keep only known fields.
    filtered = {
        "action": data.get("action"),
        "target": data.get("target"),
        "text": data.get("text"),
        "confidence": data.get("confidence"),
        "reason": data.get("reason") or "",
    }
    try:
        return AIActionDecision.model_validate(filtered)
    except ValidationError as exc:
        raise ActionValidationError(str(exc)) from exc


def candidate_summaries(candidates: Sequence[PlannedAction]) -> list[dict[str, Any]]:
    return [
        {
            "key": item.key,
            "action": _normalize_kind(item.kind),
            "label": item.label,
            "priority": item.priority,
            "default_text": (item.meta or {}).get("default_text"),
        }
        for item in candidates
    ]


def _normalize_kind(kind: str) -> str:
    raw = (kind or "").strip().lower()
    if raw == "menu":
        return "open_menu"
    if raw == "swipe":
        return "swipe_up"
    return raw


def map_decision_to_planned(
    decision: AIActionDecision,
    candidates: Sequence[PlannedAction],
) -> PlannedAction:
    """Map a validated decision onto a concrete PlannedAction from candidates.

    Rejects decisions that do not match an allow-listed candidate (except
    ``back`` / ``stop`` / ``wait`` / ``open_menu`` synthetics when needed).
    """
    action = decision.action
    if action not in ALLOWED_ACTIONS:
        raise ActionValidationError(f"disallowed action: {action}")

    if action == "stop":
        return PlannedAction(
            key="stop:ai",
            action=WaitAction(seconds=0),
            kind="stop",
            priority=0,
            label="stop exploration (AI)",
            meta={"reason": decision.reason, "source": "ai"},
        )

    if action == "back":
        planned = back_action()
        return PlannedAction(
            key=planned.key,
            action=planned.action,
            kind=planned.kind,
            priority=planned.priority,
            label=planned.label,
            meta={**planned.meta, "reason": decision.reason, "source": "ai"},
        )

    # Prefer exact key match.
    if decision.target:
        for item in candidates:
            if item.key == decision.target and _normalize_kind(item.kind) == action:
                return _with_ai_meta(item, decision)
        # Target key exists but kind mismatch — still allow if key matches uniquely.
        for item in candidates:
            if item.key == decision.target:
                if _normalize_kind(item.kind) not in ALLOWED_ACTIONS and action == "tap":
                    pass
                if _normalize_kind(item.kind) == action or (
                    action == "tap" and _normalize_kind(item.kind) == "tap"
                ):
                    return _with_ai_meta(item, decision)
        raise ActionValidationError(
            f"target '{decision.target}' is not an allowed candidate for action={action}"
        )

    # No target: first candidate of that action kind.
    for item in candidates:
        if _normalize_kind(item.kind) == action:
            return _with_ai_meta(item, decision)

    if action == "wait":
        return PlannedAction(
            key="wait:ai",
            action=WaitAction(seconds=2.0),
            kind="wait",
            priority=10,
            label="wait (AI)",
            meta={"reason": decision.reason, "source": "ai", "seconds": 2.0},
        )
    if action == "open_menu":
        return PlannedAction(
            key="menu:ai",
            action=MenuAction(),
            kind="menu",
            priority=15,
            label="open menu (AI)",
            meta={"reason": decision.reason, "source": "ai"},
        )

    raise ActionValidationError(f"no candidate available for action={action}")


def _with_ai_meta(item: PlannedAction, decision: AIActionDecision) -> PlannedAction:
    meta = dict(item.meta)
    meta["reason"] = decision.reason
    meta["source"] = "ai"
    meta["planner_source"] = "AI"
    if decision.confidence is not None:
        meta["confidence"] = decision.confidence
    action = item.action
    # Allow AI to override typed text on type_text candidates only.
    if decision.action == "type_text" and isinstance(item.action, TypeTextAction):
        override = sanitize_type_text(decision.text or item.action.text)
        if not override:
            override = sanitize_type_text(item.action.text) or "Test"
        action = TypeTextAction(
            text=override,
            element=item.action.element,
            x=item.action.x,
            y=item.action.y,
            clear_first=item.action.clear_first,
        )
        meta["default_text"] = override
    return PlannedAction(
        key=item.key,
        action=action,
        kind=item.kind,
        priority=item.priority,
        label=item.label,
        meta=meta,
    )


def validate_and_map(
    raw: str | dict[str, Any],
    candidates: Sequence[PlannedAction],
) -> PlannedAction:
    decision = parse_ai_decision(raw)
    planned = map_decision_to_planned(decision, candidates)
    logger.info(
        "AI decision accepted action=%s key=%s reason=%s",
        decision.action,
        planned.key,
        (decision.reason or "")[:120],
    )
    return planned
