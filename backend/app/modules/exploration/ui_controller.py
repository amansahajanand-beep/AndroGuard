"""ADB + UIAutomator controller for inspecting and driving a running app.

Phase 2 scope: dump the UI hierarchy and execute deterministic input actions.
Exploration strategy, ad detection and S3 upload are intentionally absent.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from app.modules.exploration.actions import (
    Action,
    ActionResult,
    BackAction,
    CoordinateTapAction,
    HomeAction,
    SwipeAction,
    SwipeDirection,
    TapAction,
    WaitAction,
)
from app.modules.exploration.adb import AndroidADB
from app.modules.exploration.errors import UiDumpError
from app.modules.exploration.ui_dump import filter_elements, parse_ui_hierarchy
from app.modules.exploration.ui_element import UIElement

logger = logging.getLogger(__name__)

# Default on-device path used by ``uiautomator dump`` when no argument is given.
_DEFAULT_DUMP_PATH = "/sdcard/window_dump.xml"
_DUMP_OK = re.compile(r"UI hier(?:arch|chary) dumped to:\s*(\S+)", re.IGNORECASE)


@dataclass(frozen=True)
class UiDump:
    """One hierarchy snapshot plus the raw XML for debugging."""

    elements: list[UIElement]
    xml: str
    path: str
    duration_ms: int
    package_filter: str | None = None

    def clickable(self) -> list[UIElement]:
        return filter_elements(self.elements, clickable_only=True, enabled_only=True)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "duration_ms": self.duration_ms,
            "package_filter": self.package_filter,
            "element_count": len(self.elements),
            "clickable_count": len(self.clickable()),
            "elements": [item.to_dict() for item in self.elements],
        }


class UIController:
    """Inspect and control the foreground UI without Android Studio."""

    def __init__(
        self,
        adb: AndroidADB,
        *,
        dump_path: str = _DEFAULT_DUMP_PATH,
        settle_ms: int = 0,
    ) -> None:
        self.adb = adb
        self.dump_path = dump_path
        self.settle_ms = settle_ms
        self._screen_size: tuple[int, int] | None = None
        self._u2: Any = None

    # -- inspection ----------------------------------------------------------

    def dump_ui(self, *, package: str | None = None) -> UiDump:
        """Run ``uiautomator dump``, pull the XML, and parse it.

        When ``package`` is set, only nodes belonging to that package are kept.
        """
        if self.settle_ms > 0:
            time.sleep(self.settle_ms / 1000.0)

        started = time.perf_counter()
        xml_text, path = self._dump_via_u2()
        if xml_text is None:
            xml_text, path = self._dump_via_adb()
        elements = parse_ui_hierarchy(xml_text)
        if package:
            elements = filter_elements(elements, package=package)

        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "UI dump on %s: %s nodes (%sms)%s",
            self.adb.serial or "(default)",
            len(elements),
            duration_ms,
            f" package={package}" if package else "",
        )
        return UiDump(
            elements=elements,
            xml=xml_text,
            path=path,
            duration_ms=duration_ms,
            package_filter=package,
        )

    def _dump_via_u2(self) -> tuple[str | None, str]:
        """uiautomator2 hierarchy, or (None, "") when disabled / unavailable / failed."""
        from app.core.config import settings

        if not getattr(settings, "uiautomator2_enabled", True):
            return None, ""
        try:
            if self._u2 is None:
                from app.modules.exploration.u2_dump import U2Dumper

                binary = None
                try:
                    binary = self.adb.binary
                except Exception:
                    binary = None
                self._u2 = U2Dumper(self.adb.serial, adb_binary=binary)
            return self._u2.dump_xml(), "uiautomator2"
        except Exception as exc:
            logger.info("uiautomator2 dump unavailable (%s); using adb uiautomator dump", type(exc).__name__)
            return None, ""

    def _dump_via_adb(self) -> tuple[str, str]:
        """`uiautomator dump` with retries: it fails transiently on animated screens."""
        last: UiDumpError | None = None
        for attempt in range(3):
            if attempt:
                time.sleep(0.7)
            dump = self.adb.shell(f"uiautomator dump {self.dump_path}", timeout=60, check=False)
            if not dump.ok:
                last = UiDumpError(dump.fail_message("uiautomator dump failed")).with_output(
                    command=dump.command, stdout=dump.stdout, stderr=dump.stderr
                )
                continue
            path = self.dump_path
            match = _DUMP_OK.search(dump.stdout) or _DUMP_OK.search(dump.stderr)
            if match:
                path = match.group(1)
            try:
                return self._read_dump_file(path), path
            except UiDumpError as exc:
                last = exc
        assert last is not None
        raise last

    def _read_dump_file(self, path: str) -> str:
        # Prefer exec-out to avoid Windows CR/LF and shell quoting issues.
        pulled = self.adb.run(["exec-out", "cat", path], check=False)
        if pulled.ok and pulled.stdout.strip():
            return pulled.stdout

        fallback = self.adb.shell(f"cat {path}", check=False)
        if fallback.ok and fallback.stdout.strip():
            return fallback.stdout

        raise UiDumpError(
            f"Could not read UIAutomator dump at {path}."
        ).with_output(
            command=pulled.command,
            stdout=pulled.stdout or fallback.stdout,
            stderr=pulled.stderr or fallback.stderr,
        )

    def screen_size(self, *, refresh: bool = False) -> tuple[int, int]:
        """Return ``(width, height)`` from ``wm size``, cached on the controller."""
        if self._screen_size is not None and not refresh:
            return self._screen_size
        info = self.adb.describe()
        width = info.screen_width or 0
        height = info.screen_height or 0
        if width <= 0 or height <= 0:
            raise UiDumpError("Could not determine device screen size via `wm size`.")
        self._screen_size = (width, height)
        return self._screen_size

    # -- actions -------------------------------------------------------------

    def perform(self, action: Action) -> ActionResult:
        size = None
        if isinstance(action, SwipeAction) and (action.start is None or action.end is None):
            size = self.screen_size()
        result = action.execute(self.adb, screen_size=size)
        logger.debug("UI action %s ok=%s (%sms)", result.kind, result.ok, result.duration_ms)
        return result

    def tap_element(self, element: UIElement) -> ActionResult:
        return self.perform(TapAction(element=element))

    def tap_coordinates(self, x: int, y: int) -> ActionResult:
        return self.perform(CoordinateTapAction(x=x, y=y))

    def swipe(self, direction: SwipeDirection, *, duration_ms: int = 300) -> ActionResult:
        return self.perform(SwipeAction(direction=direction, duration_ms=duration_ms))

    def swipe_up(self, *, duration_ms: int = 300) -> ActionResult:
        return self.swipe("up", duration_ms=duration_ms)

    def swipe_down(self, *, duration_ms: int = 300) -> ActionResult:
        return self.swipe("down", duration_ms=duration_ms)

    def swipe_left(self, *, duration_ms: int = 300) -> ActionResult:
        return self.swipe("left", duration_ms=duration_ms)

    def swipe_right(self, *, duration_ms: int = 300) -> ActionResult:
        return self.swipe("right", duration_ms=duration_ms)

    def press_back(self) -> ActionResult:
        return self.perform(BackAction())

    def press_home(self) -> ActionResult:
        return self.perform(HomeAction())

    def wait(self, seconds: float = 1.0) -> ActionResult:
        return self.perform(WaitAction(seconds=seconds))
