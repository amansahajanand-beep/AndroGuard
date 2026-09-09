from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.config import settings
from app.modules.exploration.errors import (
    AdbCommandError,
    AdbTimeoutError,
    AdbUnavailableError,
    NoDeviceError,
)
from app.schemas.exploration import DeviceInfo

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30

_DEVICE_LINE = re.compile(r"^(\S+)\s+(device|offline|unauthorized|bootloader)\b")
_WM_SIZE = re.compile(r"Physical size:\s*(\d+)x(\d+)")
_WM_DENSITY = re.compile(r"Physical density:\s*(\d+)")


@dataclass(frozen=True)
class AdbDevice:
    serial: str
    state: str

    @property
    def is_ready(self) -> bool:
        return self.state == "device"

    @property
    def is_emulator(self) -> bool:
        return self.serial.startswith("emulator-")


@lru_cache(maxsize=1)
def find_adb() -> str | None:
    """Locate the adb binary from settings, PATH, or the Android SDK layout.

    Mirrors ``find_aapt`` so no Android Studio installation is required at runtime.
    """
    configured = (settings.adb_path or "").strip()
    if configured and configured not in {"adb", "adb.exe"}:
        path = Path(configured)
        if path.is_file():
            return str(path)
    for name in ("adb", "adb.exe"):
        found = shutil.which(name)
        if found:
            return found
    home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if not home:
        return None
    for exe in ("adb.exe", "adb"):
        candidate = Path(home) / "platform-tools" / exe
        if candidate.is_file():
            return str(candidate)
    return None


def adb_available() -> bool:
    return find_adb() is not None


def _require_adb() -> str:
    binary = find_adb()
    if binary is None:
        raise AdbUnavailableError(
            "adb was not found. Set ADB_PATH or install Android platform-tools."
        )
    return binary


def run_adb(
    args: list[str],
    *,
    serial: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    check: bool = True,
    binary_output: bool = False,
) -> subprocess.CompletedProcess:
    """Invoke adb with an optional device selector."""
    binary = _require_adb()
    command = [binary]
    if serial:
        command += ["-s", serial]
    command += args
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=not binary_output,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise AdbTimeoutError(f"adb {' '.join(args)} timed out after {timeout}s.") from exc
    except OSError as exc:
        raise AdbCommandError(f"adb {' '.join(args)} could not be executed: {exc}") from exc
    if check and completed.returncode != 0:
        detail = completed.stderr if not binary_output else b""
        message = detail.strip() if isinstance(detail, str) else str(detail)
        raise AdbCommandError(
            f"adb {' '.join(args)} exited {completed.returncode}: {message[:400]}"
        )
    return completed


def shell(command: str, *, serial: str | None = None, timeout: int = DEFAULT_TIMEOUT) -> str:
    completed = run_adb(["shell", command], serial=serial, timeout=timeout)
    return completed.stdout or ""


def list_devices() -> list[AdbDevice]:
    if not adb_available():
        return []
    try:
        completed = run_adb(["devices"], check=False)
    except (AdbCommandError, AdbTimeoutError, AdbUnavailableError):
        return []
    devices: list[AdbDevice] = []
    for line in (completed.stdout or "").splitlines()[1:]:
        match = _DEVICE_LINE.match(line.strip())
        if match:
            devices.append(AdbDevice(serial=match.group(1), state=match.group(2)))
    return devices


def pick_device(preferred: str | None = None) -> str:
    """Choose a target serial, preferring configuration then emulators."""
    wanted = (preferred or settings.emulator_serial or "").strip()
    devices = list_devices()
    ready = [item for item in devices if item.is_ready]
    if wanted:
        for item in ready:
            if item.serial == wanted:
                return item.serial
        raise NoDeviceError(f"Device '{wanted}' is not connected or not ready.")
    if not ready:
        raise NoDeviceError(
            "No ready Android device found. Start an emulator via `emulator -avd <name>`."
        )
    for item in ready:
        if item.is_emulator:
            return item.serial
    return ready[0].serial


def _getprop(serial: str, prop: str) -> str | None:
    try:
        value = shell(f"getprop {prop}", serial=serial, timeout=10).strip()
    except (AdbCommandError, AdbTimeoutError):
        return None
    return value or None


def describe_device(serial: str) -> DeviceInfo:
    """Collect identifying properties for the exploration report."""
    sdk_raw = _getprop(serial, "ro.build.version.sdk")
    try:
        sdk_int = int(sdk_raw) if sdk_raw else None
    except ValueError:
        sdk_int = None

    width = height = density = None
    try:
        size_out = shell("wm size", serial=serial, timeout=10)
        size_match = _WM_SIZE.search(size_out)
        if size_match:
            width = int(size_match.group(1))
            height = int(size_match.group(2))
    except (AdbCommandError, AdbTimeoutError):
        logger.debug("Could not read screen size for %s", serial)
    try:
        density_out = shell("wm density", serial=serial, timeout=10)
        density_match = _WM_DENSITY.search(density_out)
        if density_match:
            density = int(density_match.group(1))
    except (AdbCommandError, AdbTimeoutError):
        logger.debug("Could not read density for %s", serial)

    return DeviceInfo(
        serial=serial,
        avd_name=_getprop(serial, "ro.boot.qemu.avd_name")
        or _getprop(serial, "ro.kernel.qemu.avd_name"),
        android_version=_getprop(serial, "ro.build.version.release"),
        sdk_int=sdk_int,
        screen_width=width,
        screen_height=height,
        density=density,
        is_emulator=serial.startswith("emulator-")
        or _getprop(serial, "ro.kernel.qemu") == "1",
    )


def is_booted(serial: str) -> bool:
    return _getprop(serial, "sys.boot_completed") == "1"


def capability_report() -> dict:
    """Non-throwing snapshot for the /health endpoint."""
    binary = find_adb()
    devices = list_devices() if binary else []
    return {
        "enabled": settings.exploration_enabled,
        "adb_available": binary is not None,
        "adb_path": binary,
        "devices": [{"serial": item.serial, "state": item.state} for item in devices],
        "ready": bool(
            settings.exploration_enabled
            and binary is not None
            and any(item.is_ready for item in devices)
        ),
    }
