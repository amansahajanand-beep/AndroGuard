"""Phase 10: strict AI action schema (decision only — never executes)."""

from __future__ import annotations

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
        "stop",
    }
)


class AIActionDecision(BaseModel):
    """Only shape the model may return. No shell/ADB/code fields allowed."""

    action: AllowedActionName
    target: str | None = Field(
        default=None,
        description="Must be a candidate action key or null for non-tap gestures.",
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
        # Reject anything that looks like a shell / adb payload.
        lowered = text.lower()
        banned = ("adb ", "shell ", "rm ", "curl ", "http://", "https://", "`", "$(", "powershell")
        if any(token in lowered for token in banned):
            raise ValueError("target contains disallowed command-like content")
        if len(text) > 240:
            raise ValueError("target too long")
        return text

    @field_validator("reason", mode="before")
    @classmethod
    def _normalize_reason(cls, value: Any) -> str:
        text = str(value or "").strip()
        return text[:500]

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "target": self.target,
            "reason": self.reason,
        }
