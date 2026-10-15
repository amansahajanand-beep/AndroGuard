"""Phase 12H — test doubles for reliability / failure injection (tests only)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
from unittest.mock import MagicMock

from app.modules.exploration.actions import Action, ActionResult
from app.modules.exploration.observation_builder import build_observation
from app.modules.exploration.ui_element import UIElement


def make_element(
    text: str = "OK",
    *,
    y0: int = 100,
    y1: int = 180,
    package: str = "com.example.app",
    clickable: bool = True,
) -> UIElement:
    return UIElement(
        text=text,
        resource_id="btn",
        content_description="",
        class_name="android.widget.Button",
        package=package,
        bounds=(40, y0, 400, y1),
        clickable=clickable,
        enabled=True,
        scrollable=False,
        visible=True,
        selected=False,
        checked=False,
        focused=False,
        focusable=True,
    )


class FailingUIController:
    """UIController stand-in that fails or succeeds deterministically."""

    def __init__(self, *, fail_kinds: set[str] | None = None, fail_n: int = 0) -> None:
        self.fail_kinds = fail_kinds or set()
        self.fail_n = fail_n
        self.calls: list[str] = []
        self._fail_remaining = fail_n

    def perform(self, action: Action) -> ActionResult:
        kind = getattr(action, "kind", type(action).__name__)
        self.calls.append(str(kind))
        if kind in self.fail_kinds or self._fail_remaining > 0:
            if self._fail_remaining > 0:
                self._fail_remaining -= 1
            return ActionResult(kind=str(kind), ok=False, error="injected_ui_failure")
        return ActionResult(kind=str(kind), ok=True)

    def wait(self, seconds: float = 0.5) -> None:
        self.calls.append(f"wait:{seconds}")


class DelayedObservationProvider:
    """Yields a sequence of observations; later frames may include ads."""

    def __init__(self, frames: list[dict[str, Any]]) -> None:
        self.frames = list(frames)
        self.index = 0

    def next(self) -> Any:
        if self.index >= len(self.frames):
            frame = self.frames[-1] if self.frames else {}
        else:
            frame = self.frames[self.index]
            self.index += 1
        return build_observation(**frame)


class DelayedAdDetector:
    """Returns no ads for N calls, then returns injected runtime ads."""

    def __init__(self, ads_after: int, ads: list[dict[str, Any]]) -> None:
        self.ads_after = ads_after
        self.ads = ads
        self.calls = 0

    def detect(self, *args: Any, **kwargs: Any) -> list[Any]:
        self.calls += 1
        if self.calls <= self.ads_after:
            return []
        return list(self.ads)


class FailingAIProvider:
    """Raises or returns invalid payloads for AI resilience tests."""

    def __init__(self, mode: str = "timeout") -> None:
        self.mode = mode
        self.calls = 0

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        if self.mode == "timeout":
            raise TimeoutError("ai_timeout")
        if self.mode == "invalid_json":
            return "not-json{{"
        if self.mode == "low_confidence":
            return {
                "action": "tap",
                "target": "tap:A",
                "text": None,
                "confidence": 0.01,
                "reason": "guess",
            }
        if self.mode == "invalid_candidate":
            return {
                "action": "tap",
                "target": "tap:DOES_NOT_EXIST",
                "text": None,
                "confidence": 0.99,
                "reason": "invented",
            }
        if self.mode == "shell":
            return {
                "action": "shell",
                "target": "adb shell am start",
                "text": None,
                "confidence": 0.99,
                "reason": "hack",
            }
        raise RuntimeError("provider_unavailable")


@dataclass
class SimulatedScreen:
    state_id: str
    activity: str
    labels: list[str] = field(default_factory=list)
    ads: list[dict[str, Any]] = field(default_factory=list)
    hitl: dict[str, Any] | None = None
    crash: bool = False


class ExplorationSimulator:
    """Deterministic exploration loop for soak / invariant tests (no emulator)."""

    def __init__(
        self,
        screens: dict[str, SimulatedScreen],
        *,
        transitions: dict[tuple[str, str], str],
        seed: int = 12345,
    ) -> None:
        self.screens = screens
        self.transitions = transitions
        self.seed = seed
        self.current = next(iter(screens))
        self.app_running = True
        self.observations: list[Any] = []

    def observe(self) -> Any:
        screen = self.screens[self.current]
        if screen.crash:
            self.app_running = False
        els = [make_element(t, y0=80 + i * 90) for i, t in enumerate(screen.labels)]
        obs = build_observation(
            package_name="com.example.app" if self.app_running else None,
            activity=screen.activity if self.app_running else None,
            elements=els,
            state_id=screen.state_id,
            screen_size=(1080, 2400),
            ad_results=list(screen.ads) if self.app_running else None,
            hitl=screen.hitl,
        )
        self.observations.append(obs)
        return obs

    def apply_action(self, label: str) -> bool:
        key = (self.current, label)
        nxt = self.transitions.get(key)
        if nxt is None:
            return False
        self.current = nxt
        self.app_running = not self.screens[nxt].crash
        return True


def mock_ui_success() -> MagicMock:
    ui = MagicMock()
    ui.perform.return_value = ActionResult(kind="tap", ok=True)
    ui.wait = MagicMock()
    return ui
