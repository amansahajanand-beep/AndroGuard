"""Phase 10: strict AI action schema (decision only — never executes)."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

AllowedActionName = Literal[
    "tap",
    "swipe_up",
    "swipe_down",
    "swipe_left",
    "swipe_right",
    "back",
    "wait",
    "open_menu",
    "type_text",
    "stop",
]

ALLOWED_ACTIONS: frozenset[str] = frozenset(
    {
        "tap",
        "swipe_up",
        "swipe_down",
        "swipe_left",
        "swipe_right",
        "back",
        "wait",
        "open_menu",
        "type_text",
        "stop",
    }
)

_SAFE_TEXT = re.compile(r"^[A-Za-z0-9 _.\-@+]{1,48}$")


class AIActionDecision(BaseModel):
    """Only shape the model may return. No shell/ADB/code fields allowed."""

    action: AllowedActionName
    target: str | None = Field(
        default=None,
        description="Must be a candidate action key or null for non-tap gestures.",
    )
    text: str | None = Field(
        default=None,
        description="Only for type_text — sanitized short string to type.",
        max_length=48,
    )
    confidence: float | None = Field(
        default=None,
        description="Optional model confidence in [0, 1]. Low values trigger fallback.",
        ge=0.0,
        le=1.0,
    )
    reason: str = Field(default="", max_length=500)

    @field_validator("action", mode="before")
    @classmethod
    def _normalize_action(cls, value: Any) -> str:
        raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "menu": "open_menu",
            "openmenu": "open_menu",
            "swipeup": "swipe_up",
            "swipedown": "swipe_down",
            "swipeleft": "swipe_left",
            "swiperight": "swipe_right",
            "type": "type_text",
            "input": "type_text",
            "type_text": "type_text",
            "enter_text": "type_text",
        }
        raw = aliases.get(raw, raw)
        if raw not in ALLOWED_ACTIONS:
            raise ValueError(f"action '{raw}' is not in the allowed set")
        return raw

    @field_validator("target", mode="before")
    @classmethod
    def _normalize_target(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text or text.lower() in {"null", "none", "-"}:
            return None
        lowered = text.lower()
        banned = ("adb ", "shell ", "rm ", "curl ", "http://", "https://", "`", "$(", "powershell")
        if any(token in lowered for token in banned):
            raise ValueError("target contains disallowed command-like content")
        if len(text) > 240:
            raise ValueError("target too long")
        return text

    @field_validator("text", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        raw = str(value).strip()
        if not raw or raw.lower() in {"null", "none"}:
            return None
        # Strip to safe charset (same rules as TypeTextAction).
        cleaned = re.sub(r"[^A-Za-z0-9 _.\-@+]", "", raw)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()[:48]
        if not cleaned:
            return None
        if not _SAFE_TEXT.match(cleaned):
            raise ValueError("text contains disallowed characters")
        banned = ("adb", "shell", "rm -", "curl", "http", "$(", "`")
        lowered = cleaned.lower()
        if any(token in lowered for token in banned):
            raise ValueError("text contains disallowed command-like content")
        return cleaned

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_confidence(cls, value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            conf = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("confidence must be a number") from exc
        if conf < 0.0 or conf > 1.0:
            raise ValueError("confidence must be between 0 and 1")
        return conf

    @field_validator("reason", mode="before")
    @classmethod
    def _normalize_reason(cls, value: Any) -> str:
        text = str(value or "").strip()
        return text[:500]

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "target": self.target,
            "text": self.text,
            "confidence": self.confidence,
            "reason": self.reason,
        }
