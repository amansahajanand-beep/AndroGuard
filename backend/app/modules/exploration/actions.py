"""Deterministic UI input actions executed through adb ``input`` / keyevents.

No LLM is involved: each action encodes a concrete gesture that
:class:`~app.modules.exploration.ui_controller.UIController` can perform.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from app.modules.exploration.errors import UiActionError
from app.modules.exploration.ui_element import UIElement

if TYPE_CHECKING:
    from app.modules.exploration.adb import AndroidADB

SwipeDirection = Literal["up", "down", "left", "right"]

KEYCODE_HOME = 3
KEYCODE_BACK = 4
KEYCODE_MENU = 82


@dataclass(frozen=True)
class ActionResult:
    """Outcome of a single :class:`Action` execution."""

    kind: str
    ok: bool
    detail: str = ""
    duration_ms: int = 0
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "ok": self.ok,
            "detail": self.detail,
            "duration_ms": self.duration_ms,
            "meta": dict(self.meta),
        }


class Action(ABC):
    """Base class for device gestures."""

    @property
    @abstractmethod
    def kind(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def execute(self, adb: "AndroidADB", *, screen_size: tuple[int, int] | None = None) -> ActionResult:
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind}


def _run_input(adb: "AndroidADB", command: str, *, kind: str, meta: dict[str, Any] | None = None) -> ActionResult:
    started = time.perf_counter()
    result = adb.shell(command, timeout=30, check=False)
    duration_ms = int((time.perf_counter() - started) * 1000)
    if not result.ok:
        raise UiActionError(result.fail_message(f"{kind} failed")).with_output(
            command=result.command, stdout=result.stdout, stderr=result.stderr
        )
    return ActionResult(
        kind=kind,
        ok=True,
        detail=command,
        duration_ms=duration_ms,
        meta=meta or {},
    )


@dataclass(frozen=True)
class TapAction(Action):
    """Tap the center of a :class:`UIElement`."""

    element: UIElement

    @property
    def kind(self) -> str:
        return "tap"

    def execute(self, adb: "AndroidADB", *, screen_size: tuple[int, int] | None = None) -> ActionResult:
        del screen_size  # unused; kept for a uniform Action.execute signature
        if not self.element.enabled:
            raise UiActionError(f"Cannot tap disabled element: {self.element.label()}")
        x, y = self.element.center
        if self.element.width <= 0 or self.element.height <= 0:
            raise UiActionError(f"Cannot tap element with empty bounds: {self.element.label()}")
        return _run_input(
            adb,
            f"input tap {x} {y}",
            kind=self.kind,
            meta={
                "x": x,
                "y": y,
                "text": self.element.text,
                "resource_id": self.element.resource_id,
                "class_name": self.element.class_name,
                "bounds": list(self.element.bounds),
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "element": self.element.to_dict()}


@dataclass(frozen=True)
class CoordinateTapAction(Action):
    """Tap absolute device coordinates."""

    x: int
    y: int

    @property
    def kind(self) -> str:
        return "coordinate_tap"

    def execute(self, adb: "AndroidADB", *, screen_size: tuple[int, int] | None = None) -> ActionResult:
        del screen_size
        return _run_input(
            adb,
            f"input tap {int(self.x)} {int(self.y)}",
            kind=self.kind,
            meta={"x": int(self.x), "y": int(self.y)},
        )

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "x": self.x, "y": self.y}


@dataclass(frozen=True)
class SwipeAction(Action):
    """Swipe across the screen in a cardinal direction, or between two points."""

    direction: SwipeDirection | None = None
    start: tuple[int, int] | None = None
    end: tuple[int, int] | None = None
    duration_ms: int = 300
    # Fraction of the shorter screen edge used as inset when deriving points.
    edge_inset: float = 0.2

    @property
    def kind(self) -> str:
        return "swipe"

    def _resolve_points(self, screen_size: tuple[int, int] | None) -> tuple[int, int, int, int]:
        if self.start is not None and self.end is not None:
            return (*self.start, *self.end)
        if self.direction is None:
            raise UiActionError("SwipeAction requires either direction or start/end points.")
        if not screen_size:
            raise UiActionError("Screen size is required to derive directional swipe points.")
        width, height = screen_size
        if width <= 0 or height <= 0:
            raise UiActionError(f"Invalid screen size for swipe: {screen_size}")
        inset_x = max(1, int(width * self.edge_inset))
        inset_y = max(1, int(height * self.edge_inset))
        cx, cy = width // 2, height // 2
        if self.direction == "up":
            return (cx, height - inset_y, cx, inset_y)
        if self.direction == "down":
            return (cx, inset_y, cx, height - inset_y)
        if self.direction == "left":
            return (width - inset_x, cy, inset_x, cy)
        if self.direction == "right":
            return (inset_x, cy, width - inset_x, cy)
        raise UiActionError(f"Unsupported swipe direction: {self.direction}")

    def execute(self, adb: "AndroidADB", *, screen_size: tuple[int, int] | None = None) -> ActionResult:
        x1, y1, x2, y2 = self._resolve_points(screen_size)
        duration = max(50, int(self.duration_ms))
        return _run_input(
            adb,
            f"input swipe {x1} {y1} {x2} {y2} {duration}",
            kind=self.kind,
            meta={
                "direction": self.direction,
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "duration_ms": duration,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "direction": self.direction,
            "start": list(self.start) if self.start else None,
            "end": list(self.end) if self.end else None,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True)
class BackAction(Action):
    @property
    def kind(self) -> str:
        return "back"

    def execute(self, adb: "AndroidADB", *, screen_size: tuple[int, int] | None = None) -> ActionResult:
        del screen_size
        return _run_input(adb, f"input keyevent {KEYCODE_BACK}", kind=self.kind, meta={"keycode": KEYCODE_BACK})


@dataclass(frozen=True)
class HomeAction(Action):
    @property
    def kind(self) -> str:
        return "home"

    def execute(self, adb: "AndroidADB", *, screen_size: tuple[int, int] | None = None) -> ActionResult:
        del screen_size
        return _run_input(adb, f"input keyevent {KEYCODE_HOME}", kind=self.kind, meta={"keycode": KEYCODE_HOME})


@dataclass(frozen=True)
class WaitAction(Action):
    """Pause the worker thread. Useful between gestures for UI settle time."""

    seconds: float = 1.0

    @property
    def kind(self) -> str:
        return "wait"

    def execute(self, adb: "AndroidADB", *, screen_size: tuple[int, int] | None = None) -> ActionResult:
        del adb, screen_size
        delay = max(0.0, float(self.seconds))
        started = time.perf_counter()
        time.sleep(delay)
        duration_ms = int((time.perf_counter() - started) * 1000)
        return ActionResult(
            kind=self.kind,
            ok=True,
            detail=f"waited {delay:.3f}s",
            duration_ms=duration_ms,
            meta={"seconds": delay},
        )

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "seconds": self.seconds}


@dataclass(frozen=True)
class MenuAction(Action):
    """Open the options menu (KEYCODE_MENU)."""

    @property
    def kind(self) -> str:
        return "open_menu"

    def execute(self, adb: "AndroidADB", *, screen_size: tuple[int, int] | None = None) -> ActionResult:
        del screen_size
        return _run_input(
            adb,
            f"input keyevent {KEYCODE_MENU}",
            kind=self.kind,
            meta={"keycode": KEYCODE_MENU},
        )


def sanitize_type_text(value: str, *, max_len: int = 48) -> str:
    """Allow only safe printable characters for ``adb input text``."""
    import re

    text = str(value or "").strip()
    # Keep letters, numbers, spaces, and a small punctuation set.
    text = re.sub(r"[^A-Za-z0-9 _.\-@+]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]


def _adb_input_text_payload(text: str) -> str:
    """Encode text for ``adb shell input text`` (spaces → %s)."""
    safe = sanitize_type_text(text)
    if not safe:
        raise UiActionError("type_text payload is empty after sanitization")
    return safe.replace(" ", "%s")


@dataclass(frozen=True)
class TypeTextAction(Action):
    """Tap an editable field (optional) then type sanitized text via adb.

    Used by the AI assist gate for create/form screens. Never executes shell
    beyond ``input tap`` / ``input text``.
    """

    text: str
    element: UIElement | None = None
    x: int | None = None
    y: int | None = None
    clear_first: bool = True

    @property
    def kind(self) -> str:
        return "type_text"

    def execute(self, adb: "AndroidADB", *, screen_size: tuple[int, int] | None = None) -> ActionResult:
        del screen_size
        started = time.perf_counter()
        payload = _adb_input_text_payload(self.text)
        meta: dict[str, Any] = {"text": sanitize_type_text(self.text)}

        # Focus the field first.
        if self.element is not None:
            x, y = self.element.center
            meta.update({"x": x, "y": y, "resource_id": self.element.resource_id})
            tap = adb.shell(f"input tap {x} {y}", timeout=30, check=False)
            if not tap.ok:
                raise UiActionError(tap.fail_message("type_text focus tap failed")).with_output(
                    command=tap.command, stdout=tap.stdout, stderr=tap.stderr
                )
            time.sleep(0.25)
        elif self.x is not None and self.y is not None:
            meta.update({"x": self.x, "y": self.y})
            tap = adb.shell(f"input tap {self.x} {self.y}", timeout=30, check=False)
            if not tap.ok:
                raise UiActionError(tap.fail_message("type_text focus tap failed")).with_output(
                    command=tap.command, stdout=tap.stdout, stderr=tap.stderr
                )
            time.sleep(0.25)

        if self.clear_first:
            # Select-all + delete is unreliable across OEMs; send a few DELs.
            adb.shell("input keyevent 123", timeout=10, check=False)  # move end
            for _ in range(24):
                adb.shell("input keyevent 67", timeout=10, check=False)  # DEL

        result = adb.shell(f"input text {payload}", timeout=30, check=False)
        duration_ms = int((time.perf_counter() - started) * 1000)
        if not result.ok:
            raise UiActionError(result.fail_message("type_text failed")).with_output(
                command=result.command, stdout=result.stdout, stderr=result.stderr
            )
        return ActionResult(
            kind=self.kind,
            ok=True,
            detail=f"input text ({len(sanitize_type_text(self.text))} chars)",
            duration_ms=duration_ms,
            meta=meta,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "text": sanitize_type_text(self.text),
            "element": self.element.to_dict() if self.element else None,
            "x": self.x,
            "y": self.y,
        }
