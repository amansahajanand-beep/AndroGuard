"""Debug helper: dump the current device UI hierarchy via UIAutomator.

Invoked as::

    python -m app.main --inspect-ui

Or directly::

    python -m app.workers.inspect_ui
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from app.core.logging import setup_logging
from app.modules.exploration.adb import AndroidADB, find_adb
from app.modules.exploration.errors import ExplorationError
from app.modules.exploration.ui_controller import UIController
from app.modules.exploration.ui_dump import filter_elements

logger = logging.getLogger("inspect_ui")


def _print(label: str, value: object) -> None:
    print(f"  {label:<22} {value}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.main --inspect-ui",
        description="Dump and summarize the UI hierarchy of a connected Android device.",
    )
    parser.add_argument(
        "--inspect-ui",
        action="store_true",
        help="Dump the current UI hierarchy (required when run via app.main).",
    )
    parser.add_argument("--serial", help="adb device serial (default: first ready emulator/device).")
    parser.add_argument("--package", help="Keep only nodes belonging to this package name.")
    parser.add_argument(
        "--clickable",
        action="store_true",
        help="Only list clickable, enabled nodes.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=40,
        help="Max elements to print in the human-readable view (default: 40).",
    )
    parser.add_argument("--json", action="store_true", help="Emit the full dump as JSON.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    return parser


def inspect_ui(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging()
    if args.verbose:
        logging.getLogger("app").setLevel(logging.DEBUG)

    if find_adb() is None:
        print("adb was not found. Set ADB_PATH or ANDROID_SDK_ROOT.")
        return 1

    try:
        adb = AndroidADB()
        serial = adb.pick_device(args.serial)
        device = adb.for_serial(serial)
        controller = UIController(device)
        dump = controller.dump_ui(package=args.package)
        size = controller.screen_size()
    except ExplorationError as exc:
        print(f"\nUI inspect failed: {exc.message}")
        details = exc.details()
        for key in ("command", "stderr", "stdout"):
            if details.get(key):
                print(f"  {key}: {details[key][:500]}")
        return 1
    except Exception as exc:  # pragma: no cover - unexpected device errors
        logger.exception("Unexpected inspect failure")
        print(f"\nUI inspect failed: {exc}")
        return 1

    elements = dump.elements
    if args.clickable:
        elements = filter_elements(elements, clickable_only=True, enabled_only=True)

    if args.json:
        payload = dump.to_dict()
        payload["screen_size"] = list(size)
        if args.clickable:
            payload["elements"] = [item.to_dict() for item in elements]
            payload["element_count"] = len(elements)
        print(json.dumps(payload, indent=2))
        return 0

    print("\nUI hierarchy")
    _print("serial", serial)
    _print("dump path", dump.path)
    _print("screen", f"{size[0]}x{size[1]}")
    _print("nodes", len(dump.elements))
    _print("clickable", len(dump.clickable()))
    _print("duration", f"{dump.duration_ms} ms")
    if dump.package_filter:
        _print("package filter", dump.package_filter)

    print("\nElements" + (" (clickable only)" if args.clickable else ""))
    if not elements:
        print("  (none)")
        return 0

    shown = elements[: max(0, args.limit)]
    for index, item in enumerate(shown, start=1):
        flags = []
        if item.clickable:
            flags.append("clickable")
        if item.scrollable:
            flags.append("scrollable")
        if not item.enabled:
            flags.append("disabled")
        if not item.visible:
            flags.append("hidden")
        flag_text = f" [{', '.join(flags)}]" if flags else ""
        print(f"  {index:>3}. {item.label()}{flag_text}")
        _print("class", item.class_name or "(none)")
        if item.resource_id:
            _print("resource-id", item.resource_id)
        if item.content_description and item.content_description != item.text:
            _print("content-desc", item.content_description)
        if item.package:
            _print("package", item.package)
        _print("bounds", list(item.bounds))
        _print("center", list(item.center))
        print()

    remaining = len(elements) - len(shown)
    if remaining > 0:
        print(f"  ... {remaining} more (raise --limit to see them)")

    return 0


def main(argv: list[str] | None = None) -> int:
    return inspect_ui(argv)


if __name__ == "__main__":
    sys.exit(main())
