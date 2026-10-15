"""Parse UIAutomator hierarchy XML into :class:`UIElement` objects."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Iterable

from app.modules.exploration.errors import UiParseError
from app.modules.exploration.ui_element import UIElement

# UIAutomator emits bounds as "[left,top][right,bottom]".
_BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def parse_bounds(raw: str | None) -> tuple[int, int, int, int]:
    """Convert a UIAutomator bounds string into ``(left, top, right, bottom)``."""
    if not raw:
        return (0, 0, 0, 0)
    match = _BOUNDS.fullmatch(raw.strip())
    if not match:
        raise UiParseError(f"Unrecognized UIAutomator bounds value: {raw!r}")
    return (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
        int(match.group(4)),
    )


def _truthy(raw: str | None, default: bool = False) -> bool:
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"true", "1", "yes"}


def _attr(node: ET.Element, *names: str) -> str:
    for name in names:
        value = node.attrib.get(name)
        if value is not None:
            return value
    return ""


def node_to_element(node: ET.Element) -> UIElement:
    """Map one ``<node>`` element to a :class:`UIElement`."""
    index_raw = node.attrib.get("index")
    try:
        index = int(index_raw) if index_raw not in (None, "") else None
    except ValueError:
        index = None

    # Prefer the explicit visibility flag when present; otherwise treat a
    # zero-area node as not visible.
    bounds = parse_bounds(node.attrib.get("bounds"))
    if "visible-to-user" in node.attrib:
        visible = _truthy(node.attrib.get("visible-to-user"), default=True)
    elif "visible" in node.attrib:
        visible = _truthy(node.attrib.get("visible"), default=True)
    else:
        visible = bounds[2] > bounds[0] and bounds[3] > bounds[1]

    return UIElement(
        text=_attr(node, "text"),
        resource_id=_attr(node, "resource-id", "resourceId"),
        content_description=_attr(node, "content-desc", "contentDescription"),
        class_name=_attr(node, "class", "className"),
        package=_attr(node, "package"),
        bounds=bounds,
        clickable=_truthy(node.attrib.get("clickable")),
        enabled=_truthy(node.attrib.get("enabled"), default=True),
        scrollable=_truthy(node.attrib.get("scrollable")),
        visible=visible,
        checkable=_truthy(node.attrib.get("checkable")),
        checked=_truthy(node.attrib.get("checked")),
        focusable=_truthy(node.attrib.get("focusable")),
        focused=_truthy(node.attrib.get("focused")),
        long_clickable=_truthy(node.attrib.get("long-clickable", node.attrib.get("longClickable"))),
        selected=_truthy(node.attrib.get("selected")),
        index=index,
    )


def parse_ui_hierarchy(xml_text: str) -> list[UIElement]:
    """Parse a full UIAutomator dump into a flat list of nodes (depth-first)."""
    text = (xml_text or "").strip()
    if not text:
        raise UiParseError("UIAutomator dump was empty.")

    # adb sometimes prefixes the dump with a status line.
    if text.startswith("UI hierchary dumped") or text.startswith("UI hierarchy dumped"):
        newline = text.find("\n")
        text = text[newline + 1 :].strip() if newline >= 0 else ""
        if not text:
            raise UiParseError("UIAutomator dump contained only the status line.")

    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise UiParseError(f"Invalid UIAutomator XML: {exc}") from exc

    elements: list[UIElement] = []
    for node in root.iter("node"):
        elements.append(node_to_element(node))
    return elements


def filter_elements(
    elements: Iterable[UIElement],
    *,
    package: str | None = None,
    clickable_only: bool = False,
    enabled_only: bool = False,
    visible_only: bool = False,
    with_text: bool = False,
) -> list[UIElement]:
    """Deterministic filters for debug / later exploration use."""
    out: list[UIElement] = []
    for item in elements:
        if package and item.package != package:
            continue
        if clickable_only and not item.clickable:
            continue
        if enabled_only and not item.enabled:
            continue
        if visible_only and not item.visible:
            continue
        if with_text and not (item.text or item.content_description):
            continue
        out.append(item)
    return out
