from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable, Sequence

from app.core.config import settings
from app.modules.exploration.errors import (
    AdbCommandError,
    AdbTimeoutError,
    AdbUnavailableError,
    NoDeviceError,
)
from app.schemas.exploration import DeviceInfo

logger = logging.getLogger(__name__)

_DEVICE_LINE = re.compile(r"^(\S+)\s+(device|offline|unauthorized|bootloader|recovery)\b")
_WM_SIZE = re.compile(r"Physical size:\s*(\d+)x(\d+)")
_WM_DENSITY = re.compile(r"Physical density:\s*(\d+)")

# Windows executables need the .exe suffix; keep the ordering platform agnostic.
_ADB_NAMES = ("adb.exe", "adb") if os.name == "nt" else ("adb", "adb.exe")


@dataclass(frozen=True)
class CommandResult:
    """Captured outcome of a single subprocess invocation."""

    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    duration_ms: int

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def command(self) -> str:
        return " ".join(self.args)

    @property
    def output(self) -> str:
        """Combined stream, for adb commands that report errors on stdout."""
        return f"{self.stdout}\n{self.stderr}".strip()

    def fail_message(self, prefix: str) -> str:
        detail = (self.stderr or self.stdout or "").strip().replace("\r", "")
        return f"{prefix} (exit {self.returncode}): {detail[:500]}"


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


Runner = Callable[[Sequence[str], int], CommandResult]


def _default_runner(args: Sequence[str], timeout: int) -> CommandResult:
    """Execute a command, capturing both streams. Raises only on timeout/OS errors."""
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            list(args),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise AdbTimeoutError(
            f"`{' '.join(args)}` timed out after {timeout}s."
        ).with_output(command=" ".join(args), stdout=_as_text(exc.stdout), stderr=_as_text(exc.stderr)) from exc
    except OSError as exc:
        raise AdbCommandError(f"`{' '.join(args)}` could not be executed: {exc}") from exc
    duration_ms = int((time.perf_counter() - started) * 1000)
    return CommandResult(
        args=tuple(args),
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        duration_ms=duration_ms,
    )


def _as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _repair_png_bytes(data: bytes) -> bytes:
    """Fix the common Windows ``adb exec-out`` CRLF corruption of PNG streams."""
    if not data:
        return data
    if data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\x89PNG\n"):
        return data
    # Some hosts expand LF to CRLF inside the binary stream.
    fixed = data.replace(b"\r\n", b"\n")
    if fixed.startswith(b"\x89PNG"):
        return fixed
    return data


@lru_cache(maxsize=1)
def find_adb() -> str | None:
    """Locate adb from ADB_PATH, PATH, then the Android SDK layout.

    Nothing is hardcoded and Android Studio is never required; only the
    platform-tools directory of an SDK install is needed.
    """
    configured = (settings.adb_path or "").strip()
    if configured and configured.lower() not in {"adb", "adb.exe"}:
        candidate = Path(configured)
        if candidate.is_file():
            return str(candidate)
        logger.warning("ADB_PATH=%s does not point to a file; falling back.", configured)
    for name in _ADB_NAMES:
        found = shutil.which(name)
        if found:
            return found
    for root in _sdk_roots():
        for name in _ADB_NAMES:
            candidate = root / "platform-tools" / name
            if candidate.is_file():
                return str(candidate)
    return None


def _sdk_roots() -> list[Path]:
    """Candidate SDK roots, in priority order."""
    raw = [
        (settings.android_sdk_root or "").strip(),
        os.environ.get("ANDROID_SDK_ROOT", ""),
        os.environ.get("ANDROID_HOME", ""),
    ]
    roots: list[Path] = []
    for value in raw:
        if not value:
            continue
        path = Path(value)
        if path.is_dir() and path not in roots:
            roots.append(path)
    return roots


def adb_available() -> bool:
    return find_adb() is not None


class AndroidADB:
    """Thin, testable wrapper around the adb executable.

    Every method surfaces captured stdout/stderr on failure rather than
    swallowing it. Instances may be bound to a serial via :meth:`for_serial`.
    """

    def __init__(
        self,
        *,
        binary: str | None = None,
        serial: str | None = None,
        timeout: int | None = None,
        runner: Runner | None = None,
    ) -> None:
        self._binary = binary
        self.serial = serial
        self.timeout = timeout or settings.adb_command_timeout_seconds
        self._runner = runner or _default_runner

    # -- plumbing ------------------------------------------------------------

    @property
    def binary(self) -> str:
        if self._binary:
            return self._binary
        found = find_adb()
        if found is None:
            raise AdbUnavailableError(
                "adb was not found. Set ADB_PATH or ANDROID_SDK_ROOT, or install "
                "Android platform-tools and add it to PATH."
            )
        self._binary = found
        return found

    def for_serial(self, serial: str) -> "AndroidADB":
        return AndroidADB(
            binary=self._binary,
            serial=serial,
            timeout=self.timeout,
            runner=self._runner,
        )

    def run(
        self,
        args: Sequence[str],
        *,
        timeout: int | None = None,
        check: bool = True,
        with_serial: bool = True,
    ) -> CommandResult:
        command: list[str] = [self.binary]
        if with_serial and self.serial:
            command += ["-s", self.serial]
        command += list(args)
        result = self._runner(command, timeout or self.timeout)
        logger.debug("adb %s -> %s in %sms", " ".join(args), result.returncode, result.duration_ms)
        if check and not result.ok:
            raise AdbCommandError(result.fail_message(f"adb {' '.join(args)} failed")).with_output(
                command=result.command, stdout=result.stdout, stderr=result.stderr
            )
        return result

    def shell(
        self,
        command: str,
        *,
        timeout: int | None = None,
        check: bool = True,
    ) -> CommandResult:
        return self.run(["shell", command], timeout=timeout, check=check)

    def shell_text(self, command: str, *, timeout: int | None = None) -> str:
        return self.shell(command, timeout=timeout).stdout.strip()

    def run_binary(
        self,
        args: Sequence[str],
        *,
        timeout: int | None = None,
        with_serial: bool = True,
    ) -> bytes:
        """Run an adb command and return raw stdout bytes (for screencap, pull, etc.).

        The normal :meth:`run` path decodes as UTF-8, which corrupts PNG payloads.
        """
        command: list[str] = [self.binary]
        if with_serial and self.serial:
            command += ["-s", self.serial]
        command += list(args)
        limit = timeout or self.timeout
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                timeout=limit,
            )
        except subprocess.TimeoutExpired as exc:
            raise AdbTimeoutError(
                f"`{' '.join(command)}` timed out after {limit}s."
            ).with_output(command=" ".join(command), stdout="", stderr=_as_text(exc.stderr)) from exc
        except OSError as exc:
            raise AdbCommandError(f"`{' '.join(command)}` could not be executed: {exc}") from exc

        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.debug(
            "adb binary %s -> %s (%s bytes, %sms)",
            " ".join(args),
            completed.returncode,
            len(completed.stdout or b""),
            duration_ms,
        )
        if completed.returncode != 0:
            stderr = _as_text(completed.stderr)
            raise AdbCommandError(
                f"adb {' '.join(args)} failed (exit {completed.returncode}): {stderr[:500]}"
            ).with_output(command=" ".join(command), stdout="", stderr=stderr)
        return completed.stdout or b""

    def screencap_png(self, *, timeout: int | None = None) -> bytes:
        """Capture the framebuffer as PNG bytes via ``adb exec-out screencap -p``."""
        raw = self.run_binary(["exec-out", "screencap", "-p"], timeout=timeout or 60)
        return _repair_png_bytes(raw)

    # -- device discovery ----------------------------------------------------

    def devices(self) -> list[AdbDevice]:
        """Parse `adb devices`. Returns an empty list when adb is missing."""
        if find_adb() is None and self._binary is None:
            return []
        result = self.run(["devices"], check=False, with_serial=False)
        found: list[AdbDevice] = []
        for line in result.stdout.splitlines()[1:]:
            match = _DEVICE_LINE.match(line.strip())
            if match:
                found.append(AdbDevice(serial=match.group(1), state=match.group(2)))
        return found

    def ready_devices(self) -> list[AdbDevice]:
        return [item for item in self.devices() if item.is_ready]

    def emulators(self) -> list[AdbDevice]:
        return [item for item in self.devices() if item.is_emulator]

    def pick_device(self, preferred: str | None = None) -> str:
        wanted = (preferred or settings.emulator_serial or "").strip()
        ready = self.ready_devices()
        if wanted:
            for item in ready:
                if item.serial == wanted:
                    return item.serial
            raise NoDeviceError(f"Device '{wanted}' is not connected or not ready.")
        if not ready:
            raise NoDeviceError(
                "No ready Android device found. Start an emulator first "
                "(see EmulatorManager.start or `emulator -avd <name>`)."
            )
        for item in ready:
            if item.is_emulator:
                return item.serial
        return ready[0].serial

    def wait_for_device(self, timeout: int = 120) -> CommandResult:
        return self.run(["wait-for-device"], timeout=timeout)

    def start_server(self) -> CommandResult:
        return self.run(["start-server"], check=False, with_serial=False)

    def kill_server(self) -> CommandResult:
        return self.run(["kill-server"], check=False, with_serial=False)

    # -- device state --------------------------------------------------------

    def getprop(self, name: str) -> str | None:
        result = self.shell(f"getprop {name}", timeout=15, check=False)
        if not result.ok:
            return None
        value = result.stdout.strip()
        return value or None

    def is_boot_completed(self) -> bool:
        return self.getprop("sys.boot_completed") == "1"

    def is_boot_animation_stopped(self) -> bool:
        # Some images never expose this; treat "unknown" as stopped.
        value = self.getprop("init.svc.bootanim")
        return value in (None, "stopped")

    def is_package_manager_ready(self) -> bool:
        result = self.shell("pm path android", timeout=20, check=False)
        return result.ok and "package:" in result.stdout

    def describe(self) -> DeviceInfo:
        """Collect identifying properties for the analysis report."""
        serial = self.serial or ""
        sdk_raw = self.getprop("ro.build.version.sdk")
        try:
            sdk_int = int(sdk_raw) if sdk_raw else None
        except ValueError:
            sdk_int = None

        width = height = density = None
        size = self.shell("wm size", timeout=15, check=False)
        if size.ok:
            match = _WM_SIZE.search(size.stdout)
            if match:
                width, height = int(match.group(1)), int(match.group(2))
        dens = self.shell("wm density", timeout=15, check=False)
        if dens.ok:
            match = _WM_DENSITY.search(dens.stdout)
            if match:
                density = int(match.group(1))

        return DeviceInfo(
            serial=serial or None,
            avd_name=self.avd_name(),
            android_version=self.getprop("ro.build.version.release"),
            sdk_int=sdk_int,
            screen_width=width,
            screen_height=height,
            density=density,
            is_emulator=serial.startswith("emulator-") or self.getprop("ro.kernel.qemu") == "1",
        )

    def avd_name(self) -> str | None:
        for prop in ("ro.boot.qemu.avd_name", "ro.kernel.qemu.avd_name", "ro.boot.avd_name"):
            value = self.getprop(prop)
            if value:
                return value.replace(" ", "_")
        result = self.run(["emu", "avd", "name"], check=False)
        if result.ok:
            first = result.stdout.strip().splitlines()
            if first and first[0].strip().upper() != "OK":
                return first[0].strip()
        return None

    def emu_kill(self) -> CommandResult:
        return self.run(["emu", "kill"], check=False, timeout=30)


# --- Health reporting --------------------------------------------------------


@dataclass
class _Capability:
    enabled: bool = False
    adb_available: bool = False
    adb_path: str | None = None
    devices: list[dict] = field(default_factory=list)
    ready: bool = False


def capability_report() -> dict:
    """Non-throwing snapshot for the /health endpoint."""
    from app.modules.exploration.emulator import find_emulator

    binary = find_adb()
    devices: list[AdbDevice] = []
    if binary is not None:
        try:
            devices = AndroidADB(binary=binary).devices()
        except Exception:  # never break liveness checks
            logger.debug("adb devices failed during health check", exc_info=True)
    emulator_binary = find_emulator()
    return {
        "enabled": settings.exploration_enabled,
        "adb_available": binary is not None,
        "adb_path": binary,
        "emulator_available": emulator_binary is not None,
        "emulator_path": emulator_binary,
        "avd_name": settings.avd_name,
        "devices": [{"serial": item.serial, "state": item.state} for item in devices],
        "ready": bool(
            settings.exploration_enabled
            and binary is not None
            and any(item.is_ready for item in devices)
        ),
    }
