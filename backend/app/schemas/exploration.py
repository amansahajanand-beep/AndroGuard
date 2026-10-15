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
    screenshot_id: str | None = None
    state_id: str | None = None
    page: str | None = None
    width: int | None = None
    height: int | None = None
    format: str | None = None
    byte_size: int | None = None
    sha256: str | None = None
    captured_at: str | None = None
    triggering_action: str | None = None
    ad_detected: bool = False
    ad_type: str | None = None
    ad_position: str | None = None
    confidence: float | None = None
    upload_error: str | None = None


class AdPlacement(BaseModel):
    """One advertisement occurrence / unique placement variation.

    Phase 5 uniqueness is driven by page + ad_type + relative geometry + trigger,
    not by screenshot pixel identity. ``relative_bbox`` is
    ``[left, top, width, height]`` in ``[0, 1]`` of the screen.
    """

    page: str | None = None
    ad_detected: bool = True
    ad_type: AdType = "unknown"
    position: str | None = Field(
        default=None,
        description="Coarse band: top | bottom | middle | fullscreen | unknown.",
    )
    relative_bbox: list[float] | None = Field(
        default=None,
        description="[left, top, width, height] relative to the screen (0..1).",
    )
    uniqueness_key: str | None = None
    trigger_action: str | None = None
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
    matched_goals: list[str] = Field(
        default_factory=list,
        description="Blueprint goal ids this placement advances (code-aware plan).",
    )
    expected_from_sdk: bool = Field(
        default=False,
        description="True when this ad_type was expected from static SDK analysis.",
    )


GoalKind = Literal[
    "feature",
    "create",
    "settings",
    "onboarding",
    "ad_trigger",
    "destination",
    "sidebar",
    "home",
]


class ExplorationGoal(BaseModel):
    """One code-derived exploration target (page / feature / ad trigger)."""

    id: str
    kind: GoalKind = "destination"
    title: str
    activity_hints: list[str] = Field(default_factory=list)
    ui_labels: list[str] = Field(default_factory=list)
    expected_ad_types: list[AdType] = Field(default_factory=list)
    priority: int = 50
    step_order: int = Field(
        default=50,
        description="Human-like journey order (lower = earlier). onboarding→create→home→sidebar→…",
    )
    why: str | None = None
    covered: bool = False


class NavigationStep(BaseModel):
    """Ordered step in the per-app navigation map."""

    goal_id: str
    order: int = 0
    summary: str = ""


class ExplorationBlueprint(BaseModel):
    """Trusted plan mined from static APK analysis (optionally LLM-enriched)."""

    package_name: str | None = None
    app_summary: str | None = Field(
        default=None,
        description="Short description of what this app appears to be (from code).",
    )
    goals: list[ExplorationGoal] = Field(default_factory=list)
    nav_path: list[NavigationStep] = Field(
        default_factory=list,
        description="Ordered journey like a human: onboard → create → home → sidebar → settings.",
    )
    ad_expectations: list[AdType] = Field(default_factory=list)
    ad_sdk_names: list[str] = Field(default_factory=list)
    preferred_labels: list[str] = Field(default_factory=list)
    ad_trigger_labels: list[str] = Field(default_factory=list)
    source: str = "deterministic"
    enricher_notes: str | None = None


class GoalCoverageItem(BaseModel):
    goal_id: str
    title: str
    kind: str | None = None
    covered: bool = False
    evidence: list[str] = Field(default_factory=list)


class ExplorationCoverage(BaseModel):
    """How live exploration satisfied the code-aware blueprint."""

    goals: list[GoalCoverageItem] = Field(default_factory=list)
    ad_types_expected: list[str] = Field(default_factory=list)
    ad_types_found: list[str] = Field(default_factory=list)
    ad_types_missing: list[str] = Field(default_factory=list)
    goals_covered: int = 0
    goals_total: int = 0


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


class AdSighting(BaseModel):
    """One distinct ad layout seen while dwelling on a screen."""

    offset_seconds: float = 0.0
    ad_type: str = "unknown"
    position: str | None = None
    relative_bbox: list[float] | None = None
    coverage_ratio: float | None = None
    is_fullscreen: bool = False
    evidence: list[str] = Field(default_factory=list)
    frame_id: str | None = Field(default=None, description="state_id of the screenshot showing it.")


class ScreenAdTimeline(BaseModel):
    """How the ads on one screen appeared and moved while the agent stayed on it."""

    state_id: str
    page: str | None = None
    activity: str | None = None
    sightings: list[AdSighting] = Field(default_factory=list)
    positions_seen: list[str] = Field(default_factory=list)
    position_changed: bool = False
    dwell_seconds: float = 0.0
    stopped_reason: str = "completed"


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
    blueprint: ExplorationBlueprint | None = None
    coverage: ExplorationCoverage | None = None
    warnings: list[str] = Field(default_factory=list)
    # Phase 8 metadata (URLs / keys only — never base64 image bodies).
    screenshot_records: list[dict[str, Any]] = Field(default_factory=list)
    # Phase 12A — latest unified observation (optional; backward compatible).
    current_observation: dict[str, Any] | None = None
    observation_count: int = 0
    # Phase 12B — compact agent memory summary (optional; runtime only).
    agent_state: dict[str, Any] | None = None
    # Phase 12G — active ad-discovery goal + unique placement discoveries (optional).
    active_goal: dict[str, Any] | None = None
    ad_discoveries: list[dict[str, Any]] = Field(default_factory=list)
    # Per-screen ad timeline from the dwell step (position changes, late and fullscreen ads).
    ad_timeline: list[ScreenAdTimeline] = Field(default_factory=list)

    @classmethod
    def skipped(cls, reason: str) -> "ExplorationResult":
        return cls(status="skipped", reason=reason)

    @classmethod
    def failed(cls, reason: str) -> "ExplorationResult":
        return cls(status="failed", reason=reason)
