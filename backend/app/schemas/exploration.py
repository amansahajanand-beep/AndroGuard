from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# NOTE: These models describe screenshots captured from a *running* app on an emulator.
# They are intentionally separate from `ScreenshotInfo` in app.schemas.analysis, which
# describes static raster assets extracted from inside the APK archive.

ExplorationStatus = Literal["completed", "partial", "skipped", "failed"]
AdType = Literal["banner", "interstitial", "native", "rewarded", "app_open", "unknown"]
DetectionMethod = Literal["ui_tree", "vision", "heuristic", "manifest_hint"]
Confidence = Literal["HIGH", "MEDIUM", "LOW"]


class Bounds(BaseModel):
    """Pixel rectangle on the device screen, matching UIAutomator's bounds format."""

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    @property
    def area(self) -> int:
        return self.width * self.height


class DeviceInfo(BaseModel):
    serial: str | None = None
    avd_name: str | None = None
    android_version: str | None = None
    sdk_int: int | None = None
    screen_width: int | None = None
    screen_height: int | None = None
    density: int | None = None
    is_emulator: bool = True


class ExplorationScreenshotInfo(BaseModel):
    """A single screen capture taken from the running application."""

    file_name: str
    url: str | None = None
    s3_key: str | None = None
    state_id: str | None = None
    width: int | None = None
    height: int | None = None
    format: str | None = None
    byte_size: int | None = None
    sha256: str | None = None
    captured_at: str | None = None


class AdPlacement(BaseModel):
    """One advertisement occurrence located on a discovered screen."""

    ad_type: AdType = "unknown"
    network: str | None = None
    sdk_class: str | None = None
    bounds: Bounds | None = None
    coverage_ratio: float | None = Field(
        default=None,
        description="Fraction of the screen area covered by this placement (0.0-1.0).",
    )
    is_fullscreen: bool = False
    detection_method: DetectionMethod = "heuristic"
    confidence: Confidence = "LOW"
    state_id: str | None = None
    screenshot_file: str | None = None
    evidence: list[str] = Field(default_factory=list)


class UiAction(BaseModel):
    """An input gesture the explorer performed to move between states."""

    kind: str
    target_text: str | None = None
    target_resource_id: str | None = None
    bounds: Bounds | None = None
    from_state_id: str | None = None
    to_state_id: str | None = None
    succeeded: bool = True


class ScreenState(BaseModel):
    """A unique UI state discovered while exploring the application."""

    state_id: str
    fingerprint: str
    activity: str | None = None
    label: str | None = None
    depth: int = 0
    is_entry_point: bool = False
    element_count: int = 0
    clickable_count: int = 0
    screenshot: ExplorationScreenshotInfo | None = None
    ad_placements: list[AdPlacement] = Field(default_factory=list)
    inbound_action: UiAction | None = None
    discovered_at: str | None = None
    extras: dict[str, Any] = Field(default_factory=dict)


class ExplorationSummary(BaseModel):
    states_discovered: int = 0
    screenshots_captured: int = 0
    screenshots_uploaded: int = 0
    actions_performed: int = 0
    ads_detected: int = 0
    unique_ad_networks: list[str] = Field(default_factory=list)
    activities_visited: list[str] = Field(default_factory=list)
    max_depth_reached: int = 0
    duration_ms: int = 0
    hit_state_limit: bool = False
    hit_action_limit: bool = False
    hit_timeout: bool = False


class ExplorationResult(BaseModel):
    """The dynamic-analysis counterpart to the static APK analysis payload."""

    status: ExplorationStatus = "skipped"
    reason: str | None = Field(
        default=None,
        description="Why exploration was skipped or failed, when not completed.",
    )
    package_name: str | None = None
    launch_activity: str | None = None
    device: DeviceInfo | None = None
    summary: ExplorationSummary = Field(default_factory=ExplorationSummary)
    states: list[ScreenState] = Field(default_factory=list)
    screenshots: list[ExplorationScreenshotInfo] = Field(default_factory=list)
    ad_placements: list[AdPlacement] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @classmethod
    def skipped(cls, reason: str) -> "ExplorationResult":
        return cls(status="skipped", reason=reason)

    @classmethod
    def failed(cls, reason: str) -> "ExplorationResult":
        return cls(status="failed", reason=reason)
