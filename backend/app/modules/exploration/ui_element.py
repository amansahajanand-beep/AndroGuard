"""Structured UI nodes extracted from a UIAutomator hierarchy dump."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class UIElement:
    """One node from ``uiautomator dump``.

    ``bounds`` is ``[left, top, right, bottom]`` in device pixels, matching the
    UIAutomator rectangle format.
    """

    text: str = ""
    resource_id: str = ""
    content_description: str = ""
    class_name: str = ""
    package: str = ""
    bounds: tuple[int, int, int, int] = (0, 0, 0, 0)
    clickable: bool = False
    enabled: bool = True
    scrollable: bool = False
    visible: bool = True
    checkable: bool = False
    checked: bool = False
    focusable: bool = False
    focused: bool = False
    long_clickable: bool = False
    selected: bool = False
    index: int | None = None

    @property
    def left(self) -> int:
        return self.bounds[0]

    @property
    def top(self) -> int:
        return self.bounds[1]

    @property
    def right(self) -> int:
        return self.bounds[2]

    @property
    def bottom(self) -> int:
        return self.bounds[3]

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    @property
    def center(self) -> tuple[int, int]:
        """Pixel center used by :class:`TapAction`."""
        return (self.left + self.width // 2, self.top + self.height // 2)

    @property
    def has_label(self) -> bool:
        return bool(self.text or self.content_description or self.resource_id)

    def label(self) -> str:
        """Short human-readable identity for debug output."""
        if self.text:
            return self.text
        if self.content_description:
            return self.content_description
        if self.resource_id:
            return self.resource_id
        short = self.class_name.rsplit(".", 1)[-1] if self.class_name else "node"
        return f"{short}@{self.bounds}"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["bounds"] = list(self.bounds)
        return payload
