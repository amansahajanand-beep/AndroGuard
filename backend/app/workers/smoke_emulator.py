"""Minimal smoke test for the Phase 1 emulator layer.

    APK -> start emulator -> wait for boot -> install -> launch -> success

Usage (from the backend/ directory, with the venv active):

    python -m app.workers.smoke_emulator --check
    python -m app.workers.smoke_emulator --apk path\\to\\app.apk
    python -m app.workers.smoke_emulator --apk app.apk --avd Pixel_6_API_34 --keep-emulator

Exits 0 on success and 1 on failure.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from app.core.config import settings
from app.core.logging import setup_logging
from app.jobs.models import JobStage
from app.modules.exploration.adb import AndroidADB, find_adb
from app.modules.exploration.emulator import EmulatorManager, find_emulator
from app.workers.emulator_stage import run_device_stage

logger = logging.getLogger("smoke_emulator")


def _print(label: str, value: object) -> None:
    print(f"  {label:<22} {value}")


def check_environment() -> bool:
    """Report tool detection without touching a device."""
    adb_path = find_adb()
    emulator_path = find_emulator()

    print("\nEnvironment")
    _print("ANDROID_SDK_ROOT", settings.android_sdk_root or "(unset)")
    _print("ADB_PATH", settings.adb_path or "(unset)")
    _print("EMULATOR_PATH", settings.emulator_path or "(unset)")
    _print("AVD_NAME", settings.avd_name or "(unset)")
    _print("EXPLORATION_ENABLED", settings.exploration_enabled)

    print("\nDetected tools")
    _print("adb", adb_path or "NOT FOUND")
    _print("emulator", emulator_path or "NOT FOUND")

    if adb_path is None:
        print("\nadb was not found. Install Android platform-tools, then set ADB_PATH")
        print("or ANDROID_SDK_ROOT (expected <sdk>\\platform-tools\\adb.exe).")
        return False

    devices = AndroidADB().devices()
    print("\nConnected devices")
    if not devices:
        _print("(none)", "start an emulator or run with --apk to boot one")
    for device in devices:
        _print(device.serial, device.state)

    if emulator_path is None:
        print("\nThe emulator binary was not found. Set EMULATOR_PATH or ANDROID_SDK_ROOT")
        print("(expected <sdk>\\emulator\\emulator.exe).")
        return False

    try:
        avds = EmulatorManager().list_avds()
        print("\nAvailable AVDs")
        if not avds:
            _print("(none)", "create one with avdmanager")
        for name in avds:
            marker = "  <- AVD_NAME" if name == settings.avd_name else ""
            _print(name, marker)
        return bool(avds)
    except Exception as exc:
        print(f"\nCould not list AVDs: {exc}")
        return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.workers.smoke_emulator",
        description="Boot an emulator, install an APK and launch it.",
    )
    parser.add_argument("--apk", help="Path to the APK to install and launch.")
    parser.add_argument("--avd", help="AVD name (defaults to AVD_NAME).")
    parser.add_argument("--package", help="Override the package name.")
    parser.add_argument("--activity", help="Override the launch activity.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only report tool/AVD detection, then exit.",
    )
    parser.add_argument(
        "--keep-emulator",
        action="store_true",
        help="Leave the emulator running after the test.",
    )
    parser.add_argument(
        "--keep-app",
        action="store_true",
        help="Do not force-stop the app afterwards.",
    )
    parser.add_argument(
        "--reinstall",
        action="store_true",
        help="Reinstall even when the package is already present.",
    )
    parser.add_argument(
        "--uninstall-after",
        action="store_true",
        help="Uninstall the package after a successful launch.",
    )
    parser.add_argument("--json", action="store_true", help="Emit the result as JSON.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging()
    if args.verbose:
        logging.getLogger("app").setLevel(logging.DEBUG)

    if args.check or not args.apk:
        ok = check_environment()
        if not args.apk:
            if not args.check:
                print("\nPass --apk <path> to run the full boot/install/launch flow.")
            return 0 if ok else 1
        if not ok:
            return 1

    apk_path = Path(args.apk).expanduser()
    if not apk_path.is_file():
        print(f"APK not found: {apk_path}")
        return 1

    print(f"\nSmoke test: {apk_path.name}")

    def on_progress(stage: JobStage) -> None:
        print(f"  -> {stage.value}")

    result = run_device_stage(
        apk_path,
        package_name=args.package,
        activity=args.activity,
        avd_name=args.avd,
        progress=on_progress,
        force_reinstall=args.reinstall,
        stop_emulator=not args.keep_emulator,
        uninstall_after=args.uninstall_after,
        keep_app_running=args.keep_app,
    )

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        _report(result)

    return 0 if result.ok else 1


def _report(result) -> None:
    print("\nResult")
    _print("status", result.status)
    if result.target:
        _print("package", result.target.package_name)
        _print("activity", result.target.activity or "(resolved on device)")
        _print("target source", result.target.source)
    if result.device:
        _print("serial", result.device.serial)
        _print("android", f"{result.device.android_version} (SDK {result.device.sdk_int})")
        _print("screen", f"{result.device.screen_width}x{result.device.screen_height}")
    _print("already installed", result.already_installed)
    _print("installed now", result.installed_now)
    if result.launch:
        _print("launched via", result.launch.method)
        _print("component", result.launch.component or "(monkey)")
        _print("foreground", result.launch.foreground)
    _print("duration", f"{result.duration_ms} ms")

    for warning in result.warnings:
        print(f"  warning: {warning}")

    if result.error:
        print("\nError")
        for key, value in result.error.items():
            _print(key, value)

    print("\nSUCCESS" if result.ok else "\nFAILED")


if __name__ == "__main__":
    sys.exit(main())
