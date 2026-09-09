from __future__ import annotations

from typing import Any
from xml.etree.ElementTree import Element

ANDROID_NS = "http://schemas.android.com/apk/res/android"
NS = f"{{{ANDROID_NS}}}"


def android_attr(el: Element, name: str) -> str | None:
    value = el.get(f"{NS}{name}")
    if value is None:
        value = el.get(name)
    return value


def parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in {"true", "1"}:
        return True
    if lowered in {"false", "0"}:
        return False
    return None


def parse_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    text = value.strip()
    try:
        if text.startswith("0x") or text.startswith("0X"):
            return int(text, 16)
        return int(text, 10)
    except ValueError:
        return None


def resolve_component_name(package: str, raw: str | None) -> str | None:
    if not raw:
        return None
    if raw.startswith("."):
        return f"{package}{raw}"
    if "." not in raw:
        return f"{package}.{raw}"
    return raw


def local_tag(el: Element) -> str:
    tag = el.tag
    if isinstance(tag, str) and tag.startswith("{"):
        return tag.split("}", 1)[1]
    return str(tag)


def find_application(manifest: Element) -> Element | None:
    app = manifest.find("application")
    if app is not None:
        return app
    for child in list(manifest):
        if local_tag(child) == "application":
            return child
    return None


def children_by_tag(parent: Element, tag: str) -> list[Element]:
    matches: list[Element] = []
    for child in list(parent):
        if local_tag(child) == tag:
            matches.append(child)
    return matches


def iter_descendants(root: Element) -> list[Element]:
    return list(root.iter())


def typed_value(raw: str | None) -> tuple[Any, str]:
    if raw is None:
        return None, "null"
    if raw.startswith("@") or raw.startswith("res/"):
        return raw, "resource"
    lowered = raw.strip().lower()
    if lowered in {"true", "false"}:
        return lowered == "true", "boolean"
    as_int = parse_int(raw)
    if as_int is not None and str(as_int) == raw.strip().lstrip("+"):
        return as_int, "integer"
    if raw.strip().isdigit() or (raw.strip().startswith("-") and raw.strip()[1:].isdigit()):
        return int(raw.strip()), "integer"
    return raw, "string"
