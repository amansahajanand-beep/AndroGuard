"""Phase 3 CLI: capture and compare device screenshots / visual states.

Examples::

    python -m app.main --screenshot
    python -m app.main --screenshot --with-ui --package com.example.app
    python -m app.main --compare-screenshot
    python -m app.main --compare-screenshot --wait 2
    python -m app.main --compare-screenshot --left a.png --right b.png
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time

from app.core.logging import setup_logging
from app.modules.exploration.adb import AndroidADB, find_adb
from app.modules.exploration.errors import AdbUnavailableError, ExplorationError
from app.modules.exploration.screenshot_manager import ScreenshotManager
from app.modules.exploration.state_detector import StateDetector
from app.modules.exploration.ui_controller import UIController

logger = logging.getLogger("screenshot_cli")


def _print(label: str, value: object) -> None:
    print(f"  {label:<24} {value}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.main --screenshot|--compare-screenshot",
        description="Capture and compare Android screenshots (Phase 3).",
    )
    parser.add_argument("--screenshot", action="store_true", help="Capture one screenshot.")
    parser.add_argument(
        "--compare-screenshot",
        action="store_true",
        help="Compare two screenshots (device captures or local files).",
    )
    parser.add_argument("--serial", help="adb device serial.")
    parser.add_argument("--package", help="Optional package filter for UI dump.")
    parser.add_argument(
        "--with-ui",
        action="store_true",
        help="Also dump UIAutomator hierarchy for structure / ad-slot fingerprints.",
    )
    parser.add_argument("--trigger", default="manual", help="trigger_action metadata label.")
    parser.add_argument("--out-dir", help="Directory for saved PNGs (default: TEMP_ROOT/screenshots).")
    parser.add_argument("--wait", type=float, default=1.5, help="Seconds between compare captures.")
    parser.add_argument("--left", help="Local PNG for compare (left).")
    parser.add_argument("--right", help="Local PNG for compare (right).")
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Override visual similarity threshold (0-1).",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON only.")
    parser.add_argument("--verbose", action="store_true")
    return parser


def _bind_device(serial: str | None) -> AndroidADB:
    if find_adb() is None:
        raise AdbUnavailableError("adb was not found. Set ADB_PATH or ANDROID_SDK_ROOT.")
    base = AndroidADB()
    return base.for_serial(base.pick_device(serial))


def _dump_elements(adb: AndroidADB, package: str | None):
    controller = UIController(adb)
    return controller.dump_ui(package=package).elements


def cmd_screenshot(args: argparse.Namespace) -> int:
    adb = _bind_device(args.serial)
    manager = ScreenshotManager(adb, output_dir=args.out_dir)
    shot = manager.capture(trigger_action=args.trigger)

    elements = None
    decision = None
    if args.with_ui:
        elements = _dump_elements(adb, args.package)
        detector = StateDetector(similarity_threshold=args.threshold)
        decision = detector.observe(
            shot,
            elements=elements,
            trigger_action=args.trigger,
            retain=True,
            is_entry_point=True,
        )

    payload = {
        "screenshot": shot.to_dict(),
        "state": decision.to_dict() if decision else None,
        "element_count": len(elements) if elements is not None else None,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print("\nScreenshot")
    _print("state_id", shot.state_id)
    _print("local_path", shot.local_path)
    _print("size", f"{shot.width}x{shot.height}")
    _print("image_hash", shot.image_hash)
    _print("timestamp", shot.timestamp)
    _print("activity", shot.activity or "(unknown)")
    _print("trigger_action", shot.trigger_action)
    _print("sha256", shot.sha256[:16] + "…")
    if decision:
        print("\nState detection")
        _print("is_new", decision.is_new)
        _print("visual hash", decision.visual.ui_structure_hash or "(no ui)")
        _print("ad layout hash", decision.ad_placement.layout_hash or "(none)")
        _print("ad slot count", decision.ad_placement.slot_count)
        _print("reason", decision.reason)
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    detector = StateDetector(similarity_threshold=args.threshold)

    if args.left or args.right:
        if not (args.left and args.right):
            print("Provide both --left and --right for file comparison.")
            return 2
        # Local-file mode does not need a device for hashing, but ScreenshotManager
        # still requires an adb handle for construction — use a dummy binary path.
        adb = AndroidADB(binary=find_adb() or "adb", serial=None)
        manager = ScreenshotManager(adb, output_dir=args.out_dir)
        left = manager.hash_file(args.left)
        right = manager.hash_file(args.right)
        left_elements = right_elements = None
    else:
        adb = _bind_device(args.serial)
        manager = ScreenshotManager(adb, output_dir=args.out_dir)
        left = manager.capture(trigger_action=f"{args.trigger}:a")
        left_elements = _dump_elements(adb, args.package) if args.with_ui else None
        time.sleep(max(0.0, float(args.wait)))
        right = manager.capture(trigger_action=f"{args.trigger}:b")
        right_elements = _dump_elements(adb, args.package) if args.with_ui else None

    result = detector.compare_screenshots(
        left,
        right,
        left_elements=left_elements,
        right_elements=right_elements,
    )
    # Also run observe twice to show retain/dedupe behaviour when UI is available.
    retain_demo = None
    if left_elements is not None and right_elements is not None:
        demo = StateDetector(similarity_threshold=args.threshold)
        first = demo.observe(left, elements=left_elements, retain=True, trigger_action="compare:a")
        second = demo.observe(right, elements=right_elements, retain=True, trigger_action="compare:b")
        retain_demo = {
            "first": first.to_dict(),
            "second": second.to_dict(),
            "unique_states_retained": len(demo.states),
        }

    payload = {
        "comparison": result,
        "left_screenshot": left.to_dict(),
        "right_screenshot": right.to_dict(),
        "retain_demo": retain_demo,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print("\nCompare screenshots")
    _print("left", left.local_path)
    _print("right", right.local_path)
    _print("visual similarity", f"{result['visual_similarity']:.3f}")
    _print("threshold", result["threshold"])
    _print("same visual state", result["same_visual_state"])
    _print("UI structure match", result["ui_structure_match"])
    _print("same ad-placement", result["same_ad_placement_state"])
    if retain_demo:
        print("\nRetain demo")
        _print("first is_new", retain_demo["first"]["is_new"])
        _print("second is_new", retain_demo["second"]["is_new"])
        _print("unique retained", retain_demo["unique_states_retained"])
        _print("second reason", retain_demo["second"]["reason"])
    return 0


def run_screenshot_cli(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging()
    if args.verbose:
        logging.getLogger("app").setLevel(logging.DEBUG)

    try:
        if args.screenshot:
            return cmd_screenshot(args)
        if args.compare_screenshot:
            return cmd_compare(args)
        parser.print_help()
        return 2
    except ExplorationError as exc:
        print(f"\nFailed: {exc.message}")
        details = exc.details()
        for key in ("command", "stderr", "stdout"):
            if details.get(key):
                print(f"  {key}: {str(details[key])[:500]}")
        return 1
    except Exception as exc:  # pragma: no cover
        logger.exception("screenshot CLI failed")
        print(f"\nFailed: {exc}")
        return 1


def main(argv: list[str] | None = None) -> int:
    return run_screenshot_cli(argv)


if __name__ == "__main__":
    sys.exit(main())
