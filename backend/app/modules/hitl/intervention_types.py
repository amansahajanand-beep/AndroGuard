"""Human-in-the-loop intervention type definitions (Phase 7)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class InterventionType(str, Enum):
    TERMS_CONSENT = "terms_consent"
    PRIVACY_CONSENT = "privacy_consent"
    PERMISSION = "permission"
    DEFAULT_APP = "default_app"
    SYSTEM_SETTINGS = "system_settings"
    LOGIN = "login"
    OTP = "otp"
    CAPTCHA = "captcha"
    VERIFICATION = "verification"
    UNKNOWN_BLOCKING_SCREEN = "unknown_blocking_screen"


class InterventionStatus(str, Enum):
    WAITING = "waiting"
    RESOLVED = "resolved"
    SKIPPED = "skipped"
    STOPPED = "stopped"
    TIMEOUT = "timeout"


class HumanDecision(str, Enum):
    CONTINUE = "continue"
    SKIP = "skip"
    STOP = "stop"
    TIMEOUT = "timeout"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def new_intervention_id() -> str:
    return f"hitl_{uuid4().hex[:12]}"


@dataclass
class Intervention:
    """One human-intervention request attached to an analysis job."""

    intervention_id: str
    job_id: str
    run_id: str | None = None
    type: InterventionType = InterventionType.UNKNOWN_BLOCKING_SCREEN
    title: str = "Human action required"
    message: str = "Human action required"
    package: str | None = None
    activity: str | None = None
    screenshot_path: str | None = None
    screenshot_s3_key: str | None = None
    screenshot_s3_url: str | None = None
    ui_dump_path: str | None = None
    status: InterventionStatus = InterventionStatus.WAITING
    created_at: datetime = field(default_factory=_now)
    timeout_at: datetime | None = None
    resolved_at: datetime | None = None
    decision: HumanDecision | None = None
    evidence: list[str] = field(default_factory=list)
    state_id: str | None = None
    parent_state_id: str | None = None
    depth: int = 0
    is_system_ui: bool = False
    confidence: float = 0.0
    suggested_action: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["type"] = self.type.value
        payload["status"] = self.status.value
        payload["decision"] = self.decision.value if self.decision else None
        payload["created_at"] = self.created_at.isoformat()
        payload["timeout_at"] = self.timeout_at.isoformat() if self.timeout_at else None
        payload["resolved_at"] = self.resolved_at.isoformat() if self.resolved_at else None
        return payload

    def public_payload(self) -> dict[str, Any]:
        """Shape embedded in GET /analyze-apk/{job_id}."""
        screenshot = None
        if self.screenshot_s3_url:
            screenshot = self.screenshot_s3_url
        elif self.screenshot_path:
            screenshot = (
                f"/api/v1/analyze-apk/{self.job_id}/intervention/"
                f"{self.intervention_id}/screenshot"
            )
        suggested = self.suggested_action or (self.extras or {}).get("suggested_action")
        return {
            "id": self.intervention_id,
            "type": self.type.value,
            "type_label": _type_label(self.type),
            "title": self.title,
            "message": self.message or "Please complete this action in the emulator.",
            "suggested_action": suggested
            or "Complete the required step in the emulator, then click Continue.",
            "package": self.package,
            "activity": self.activity,
            "status": self.status.value,
            "screenshot": screenshot,
            "screenshot_s3_key": self.screenshot_s3_key,
            "screenshot_s3_url": self.screenshot_s3_url,
            "is_system_ui": self.is_system_ui,
            "evidence": list(self.evidence),
            "created_at": self.created_at.isoformat(),
            "timeout_at": self.timeout_at.isoformat() if self.timeout_at else None,
        }


def _type_label(kind: InterventionType) -> str:
    return {
        InterventionType.TERMS_CONSENT: "Terms & Conditions",
        InterventionType.PRIVACY_CONSENT: "Privacy Policy",
        InterventionType.PERMISSION: "Android Permission",
        InterventionType.DEFAULT_APP: "Default App",
        InterventionType.SYSTEM_SETTINGS: "System Settings",
        InterventionType.LOGIN: "Login / Sign in",
        InterventionType.OTP: "OTP / Verification code",
        InterventionType.CAPTCHA: "CAPTCHA",
        InterventionType.VERIFICATION: "Account verification",
        InterventionType.UNKNOWN_BLOCKING_SCREEN: "Blocking screen",
    }.get(kind, kind.value.replace("_", " ").title())


@dataclass
class DetectionResult:
    """Output of :class:`InterventionDetector` for one screen."""

    required: bool
    type: InterventionType | None = None
    title: str = ""
    message: str = "Human action required"
    evidence: list[str] = field(default_factory=list)
    confidence: float = 0.0
    is_system_ui: bool = False
    suggested_action: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "required": self.required,
            "type": self.type.value if self.type else None,
            "title": self.title,
            "message": self.message,
            "evidence": list(self.evidence),
            "confidence": self.confidence,
            "is_system_ui": self.is_system_ui,
            "suggested_action": self.suggested_action,
        }
