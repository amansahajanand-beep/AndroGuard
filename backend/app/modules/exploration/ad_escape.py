"""Get out of an ad and back into the target app, verifying every step.

Ads often run inside the app's own package (``com.google.android.gms.ads.AdActivity``),
so "the foreground package is still ours" does not mean we are on app content.
This module detects an ad screen by activity, package and layout, then escalates:

1. tap a Close / Skip control found in the UI tree,
2. wait for a countdown ad to reveal its close control,
3. tap the usual corner "X" position (fullscreen ad activities only),
4. press Back,
5. fall back to the explorer's own recovery (Back chain / relaunch).

Every step re-reads the screen, so the routine stops as soon as the ad is gone.
All device access is injected so it can be tested without an emulator.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from app.modules.exploration.action_planner import (
    _AD_SURFACE_ID,
    _AD_SURFACE_PKG,
    _INTERSTITIAL_ACTIVITY,
    looks_like_interstitial_ad,
)
from app.modules.exploration.actions import BackAction, CoordinateTapAction
from app.modules.exploration.ui_element import UIElement

logger = logging.getLogger(__name__)

# Countdown copy such as "Skip in 5", "Reward in 3s", "Close in 2": the control is not ready yet.
_COUNTDOWN_RX = re.compile(r"(skip|close|reward|continue)\D{0,12}\d+\s*s?\b", re.I)


@dataclass
class AdEscapeResult:
    ad_seen: bool = False
    escaped: bool = False
    steps: list[str] = field(default_factory=list)

    def note(self, step: str) -> None:
        self.steps.append(step)


def _package_of(activity: str | None, package: str | None) -> str:
    if package:
        return package
    if activity and "/" in activity:
        return activity.split("/", 1)[0]
    return ""


def is_ad_screen(
    elements: Sequence[UIElement],
    *,
    activity: str | None,
    package: str | None,
    target_package: str,
    screen_size: tuple[int, int] | None,
) -> bool:
    """True when the visible screen is an ad creative, even inside the target package."""
    if activity and _INTERSTITIAL_ACTIVITY.search(activity):
        return True
    pkg = _package_of(activity, package)
    if pkg and pkg != target_package and _AD_SURFACE_PKG.search(pkg):
        return True
    # Layout heuristics alone mistake WebView pages with a corner icon for ads, so they only count
    # when some element also carries ad-SDK evidence (package, class or resource id).
    if not any(_has_ad_evidence(el) for el in elements):
        return False
    return looks_like_interstitial_ad(elements, activity=activity, screen_size=screen_size)


def _has_ad_evidence(el: UIElement) -> bool:
    return bool(
        (el.package and _AD_SURFACE_PKG.search(el.package))
        or (el.class_name and _AD_SURFACE_PKG.search(el.class_name))
        or (el.resource_id and _AD_SURFACE_ID.search(el.resource_id))
    )


def has_countdown(elements: Sequence[UIElement]) -> bool:
    for el in elements:
        for value in (el.text, el.content_description):
            if value and _COUNTDOWN_RX.search(value):
                return True
    return False


def _corner_taps(screen_size: tuple[int, int]) -> list[tuple[int, int]]:
    width, height = screen_size
    if width <= 0 or height <= 0:
        return []
    top = int(height * 0.06)
    margin = int(width * 0.07)
    return [(width - margin, top), (margin, top)]


def escape_ad(
    *,
    ui: Any,
    dump: Callable[[], tuple[Sequence[UIElement], tuple[int, int], str | None]],
    package: Callable[[], str | None],
    is_foreground: Callable[[], bool],
    target_package: str,
    dismiss_candidates: Callable[..., Sequence[Any]],
    recover: Callable[[], bool],
    settle: Callable[[], None] = lambda: None,
    sleep: Callable[[float], None] = time.sleep,
    max_rounds: int = 6,
    countdown_wait_seconds: float = 8.0,
) -> AdEscapeResult:
    """Leave the current ad. Returns without acting when no ad is on screen."""
    result = AdEscapeResult()
    corner_attempted = False
    waited = 0.0

    for round_no in range(max_rounds):
        elements, screen_size, activity = dump()
        pkg = package()
        in_ad = is_ad_screen(
            elements,
            activity=activity,
            package=pkg,
            target_package=target_package,
            screen_size=screen_size,
        )
        in_app = is_foreground()

        if not in_ad and in_app:
            result.escaped = result.ad_seen
            return result
        if not in_ad and not in_app:
            # Browser / store / home opened by the ad.
            result.ad_seen = True
            result.note("left_app")
            result.escaped = bool(recover())
            return result

        result.ad_seen = True

        candidates = list(dismiss_candidates(elements, screen_size=screen_size))
        if candidates:
            selected = candidates[0]
            try:
                ui.perform(selected.action)
            except Exception as exc:  # noqa: BLE001 - device errors must not abort exploration
                result.note(f"close_failed:{type(exc).__name__}")
            else:
                result.note(f"close:{getattr(selected, 'label', '') or getattr(selected, 'key', '')}")
            settle()
            continue

        if has_countdown(elements) and waited < countdown_wait_seconds:
            sleep(1.0)
            waited += 1.0
            result.note("wait_countdown")
            continue

        fullscreen_activity = bool(activity and _INTERSTITIAL_ACTIVITY.search(activity))
        if fullscreen_activity and not corner_attempted:
            corner_attempted = True
            for x, y in _corner_taps(screen_size):
                try:
                    ui.perform(CoordinateTapAction(x=x, y=y))
                except Exception as exc:  # noqa: BLE001
                    result.note(f"corner_failed:{type(exc).__name__}")
                    continue
                result.note(f"corner:{x},{y}")
                settle()
                elements, screen_size, activity = dump()
                if not is_ad_screen(
                    elements,
                    activity=activity,
                    package=package(),
                    target_package=target_package,
                    screen_size=screen_size,
                ):
                    break
            continue

        try:
            ui.perform(BackAction())
            result.note("back")
        except Exception as exc:  # noqa: BLE001
            result.note(f"back_failed:{type(exc).__name__}")
        settle()

    # Still stuck after every step: hand over to the explorer's recovery (Back chain / relaunch).
    result.note("recover")
    result.escaped = bool(recover())
    logger.info("[AD-ESCAPE] steps=%s escaped=%s", result.steps, result.escaped)
    return result
