"""Phase 6 advertisement detection result models.

Screenshot analysis only — these types never drive emulator input.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

AdTypeName = Literal["banner", "native", "interstitial", "rewarded", "unknown"]
AdPositionName = Literal["top", "bottom", "middle", "fullscreen", "unknown"]


@dataclass(frozen=True)
class BoundingBox:
    """Pixel box on the screenshot: origin top-left."""

    x: int
    y: int
    width: int
    height: int

    def to_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "BoundingBox | None":
        if not data:
            return None
        return cls(
            x=int(data.get("x", 0)),
            y=int(data.get("y", 0)),
            width=int(data.get("width", 0)),
            height=int(data.get("height", 0)),
        )


@dataclass
class AdDetectionResult:
    """Outcome of analyzing one screenshot for visible advertisements."""

    detected: bool
    type: AdTypeName = "unknown"
    confidence: float = 0.0
    bounding_box: BoundingBox | None = None
    position: AdPositionName = "unknown"
    provider: str = ""
    image_path: str | None = None
    image_width: int | None = None
    image_height: int | None = None
    evidence: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "detected": self.detected,
            "type": self.type,
            "confidence": round(float(self.confidence), 4),
            "bounding_box": self.bounding_box.to_dict() if self.bounding_box else None,
            "position": self.position,
            "provider": self.provider,
            "image_path": self.image_path,
            "image_width": self.image_width,
            "image_height": self.image_height,
            "evidence": list(self.evidence),
        }
        if self.raw:
            payload["raw"] = dict(self.raw)
        return payload

    @classmethod
    def none(
        cls,
        *,
        provider: str = "",
        image_path: str | None = None,
        image_width: int | None = None,
        image_height: int | None = None,
        evidence: list[str] | None = None,
    ) -> "AdDetectionResult":
        return cls(
            detected=False,
            type="unknown",
            confidence=0.0,
            bounding_box=None,
            position="unknown",
            provider=provider,
            image_path=image_path,
            image_width=image_width,
            image_height=image_height,
            evidence=list(evidence or []),
        )


def infer_position(
    box: BoundingBox,
    *,
    image_width: int,
    image_height: int,
) -> AdPositionName:
    """Map a pixel box onto a coarse screen band."""
    if image_width <= 0 or image_height <= 0:
        return "unknown"
    coverage = (box.width * box.height) / float(image_width * image_height)
    top_ratio = box.y / float(image_height)
    bottom_ratio = (box.y + box.height) / float(image_height)
    height_ratio = box.height / float(image_height)
    if coverage >= 0.55 or (box.width / image_width >= 0.85 and height_ratio >= 0.55):
        return "fullscreen"
    if top_ratio <= 0.15 and height_ratio <= 0.30:
        return "top"
    if bottom_ratio >= 0.85 or top_ratio >= 0.70:
        return "bottom"
    if 0.20 <= top_ratio <= 0.70:
        return "middle"
    return "unknown"


def normalize_ad_type(value: str | None) -> AdTypeName:
    key = (value or "unknown").strip().lower().replace("-", "_").replace(" ", "_")
    mapping = {
        "banner": "banner",
        "native": "native",
        "native_ad": "native",
        "interstitial": "interstitial",
        "fullscreen": "interstitial",
        "full_screen": "interstitial",
        "rewarded": "rewarded",
        "reward": "rewarded",
        "rewarded_video": "rewarded",
        "unknown": "unknown",
    }
    return mapping.get(key, "unknown")  # type: ignore[return-value]
