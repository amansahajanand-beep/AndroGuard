"""Phase 12A — Unified Observation (read-only screen snapshot).

Aggregates existing subsystem outputs into one serializable object for a future
Observe → Understand → Plan → Act loop. Observation never executes ADB/actions.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_observation_id() -> str:
    return f"obs_{uuid.uuid4().hex[:12]}"


@dataclass
class Observation:
    """Complete read-only view of the app/emulator at one moment."""

    observation_id: str = field(default_factory=new_observation_id)
    timestamp: str = field(default_factory=_utcnow_iso)

    package_name: str | None = None
    activity: str | None = None

    screenshot_path: str | None = None
    screenshot_url: str | None = None
    screenshot_id: str | None = None

    screen_width: int | None = None
    screen_height: int | None = None

    state_id: str | None = None

    visible_text: list[str] = field(default_factory=list)
    clickable_elements: list[dict[str, Any]] = field(default_factory=list)
    ui_elements: list[dict[str, Any]] = field(default_factory=list)

    detected_ads: list[dict[str, Any]] = field(default_factory=list)

    hitl_required: bool = False
    hitl_type: str | None = None
    hitl_message: str | None = None
    hitl: dict[str, Any] = field(default_factory=lambda: {"required": False})

    webview_detected: bool = False

    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable representation (no image bytes, no secrets)."""
        return {
            "observation_id": self.observation_id,
            "timestamp": self.timestamp,
            "package_name": self.package_name,
            "activity": self.activity,
            "screenshot_path": self.screenshot_path,
            "screenshot_url": self.screenshot_url,
            "screenshot_id": self.screenshot_id,
            "screen_width": self.screen_width,
            "screen_height": self.screen_height,
            "state_id": self.state_id,
            "visible_text": list(self.visible_text),
            "clickable_elements": list(self.clickable_elements),
            "ui_elements": list(self.ui_elements),
            "detected_ads": list(self.detected_ads),
            "hitl_required": bool(self.hitl_required),
            "hitl_type": self.hitl_type,
            "hitl_message": self.hitl_message,
            "hitl": dict(self.hitl) if self.hitl else {"required": False},
            "webview_detected": bool(self.webview_detected),
            "metadata": dict(self.metadata),
        }
