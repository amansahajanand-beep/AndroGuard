from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from app.core.config import settings
from app.modules.exploration.adb import AndroidADB, _sdk_roots
from app.modules.exploration.errors import (
    AvdNotFoundError,
    EmulatorBootTimeoutError,
    EmulatorStartError,
    EmulatorStopError,
    EmulatorUnavailableError,
)

logger = logging.getLogger(__name__)

_EMULATOR_NAMES = ("emulator.exe", "emulator") if os.name == "nt" else ("emulator", "emulator.exe")

BOOT_POLL_SECONDS = 3
STOP_POLL_SECONDS = 1


@lru_cache(maxsize=1)
def find_emulator() -> str | None:
    """Locate the emulator binary from EMULATOR_PATH, PATH, then the SDK layout."""
    configured = (settings.emulator_path or "").strip()
    if configured:
        candidate = Path(configured)
        if candidate.is_file():
            return str(candidate)
        logger.warning("EMULATOR_PATH=%s does not point to a file; falling back.", configured)
    for name in _EMULATOR_NAMES:
        found = shutil.which(name)
        if found:
            return found
    for root in _sdk_roots():
        for relative in ("emulator", "tools"):
            for name in _EMULATOR_NAMES:
                candidate = root / relative / name
                if candidate.is_file():
                    return str(candidate)
    return None


def emulator_available() -> bool:
    return find_emulator() is not None


def _log_dir() -> Path:
    path = Path(settings.temp_root) / "emulator"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _detached_flags() -> int:
    """Keep the emulator alive independently of the worker process."""
    if os.name != "nt":
        return 0
    new_group = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    detached = getattr(subprocess, "DETACHED_PROCESS", 0)
    return new_group | detached


class EmulatorManager:
    """Owns the Android emulator lifecycle: detect, start, wait, stop, reset.

    Intended to run inside the analysis worker, never inside an HTTP request:
    booting an emulator takes minutes.
    """

    def __init__(
        self,
        *,
        adb: AndroidADB | None = None,
        avd_name: str | None = None,
        emulator_binary: str | None = None,
        preferred_serial: str | None = None,
    ) -> None:
        self.preferred_serial = (preferred_serial or "").strip() or None
        self.adb = adb or AndroidADB(serial=self.preferred_serial)
        self.avd_name = (avd_name or settings.avd_name or "").strip() or None
        self._binary = emulator_binary
        self._process: subprocess.Popen | None = None
        self._serial: str | None = self.preferred_serial
        self._started_by_us = False
        self._log_path: Path | None = None

    # -- discovery -----------------------------------------------------------

    @property
    def binary(self) -> str:
        if self._binary:
            return self._binary
        found = find_emulator()
        if found is None:
            raise EmulatorUnavailableError(
                "The Android emulator binary was not found. Set EMULATOR_PATH or "
                "ANDROID_SDK_ROOT (expected <sdk>/emulator/emulator)."
            )
        self._binary = found
        return found

    @property
    def serial(self) -> str | None:
        return self._serial

    @property
    def started_by_us(self) -> bool:
        return self._started_by_us

    def list_avds(self) -> list[str]:
        """Return configured AVD names via `emulator -list-avds`."""
        from app.modules.exploration.adb import _default_runner

        result = _default_runner([self.binary, "-list-avds"], 60)
        if not result.ok:
            raise EmulatorStartError(
                result.fail_message("emulator -list-avds failed")
            ).with_output(command=result.command, stdout=result.stdout, stderr=result.stderr)
        names: list[str] = []
        for line in result.stdout.splitlines():
            name = line.strip()
            # The emulator prints incidental warnings to stdout on some builds.
            if name and not name.startswith(("INFO", "WARNING", "ERROR", "handleCpuAcceleration")):
                names.append(name)
        return names

    def resolve_avd(self, avd_name: str | None = None) -> str:
        """Pick and validate the AVD to boot."""
        wanted = (avd_name or self.avd_name or "").strip()
        available = self.list_avds()
        if not available:
            raise AvdNotFoundError(
                "No AVDs are defined. Create one with avdmanager, e.g. "
                "`avdmanager create avd -n androguard -k \"system-images;android-34;google_apis;x86_64\"`."
            )
        if not wanted:
            if len(available) == 1:
                return available[0]
            raise AvdNotFoundError(
                "AVD_NAME is not set and multiple AVDs exist: " + ", ".join(available)
            )
        for name in available:
            if name.lower() == wanted.lower():
                return name
        raise AvdNotFoundError(
            f"AVD '{wanted}' does not exist. Available: {', '.join(available)}"
        )

    # -- state ---------------------------------------------------------------

    def running_serial(self) -> str | None:
        """Serial of a booted emulator matching our AVD, if any."""
        candidates = [item for item in self.adb.devices() if item.is_emulator and item.is_ready]
        if not candidates:
            return None
        if self.avd_name:
            for item in candidates:
                name = self.adb.for_serial(item.serial).avd_name()
                if name and name.lower() == self.avd_name.lower():
                    return item.serial
            # An emulator is up but not the requested AVD; reuse it only if unnamed.
        return candidates[0].serial

    def is_running(self) -> bool:
        return self.running_serial() is not None

    # -- lifecycle -----------------------------------------------------------

    def start(self, avd_name: str | None = None, *, wait: bool = True) -> str:
        """Start the AVD unless a suitable emulator is already running.

        Idempotent: an existing emulator is reused and will not be stopped by
        :meth:`stop` unless ``force=True``.
        """
        existing = self.running_serial()
        if existing:
            logger.info("Reusing running emulator %s", existing)
            self._serial = existing
            self._started_by_us = False
            return existing

        resolved = self.resolve_avd(avd_name)
        known = {item.serial for item in self.adb.devices()}
        args = self._build_args(resolved)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        self._log_path = _log_dir() / f"{resolved}-{stamp}.log"

        logger.info("Starting emulator AVD=%s: %s", resolved, " ".join(args))
        try:
            handle = self._log_path.open("wb")
        except OSError as exc:
            raise EmulatorStartError(f"Could not open emulator log file: {exc}") from exc
        try:
            self._process = subprocess.Popen(
                args,
                stdout=handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                cwd=str(Path(self.binary).parent),
                creationflags=_detached_flags(),
                close_fds=True,
            )
        except OSError as exc:
            handle.close()
            raise EmulatorStartError(f"Could not launch the emulator: {exc}") from exc
        finally:
            # The child keeps its own descriptor; the parent does not need ours.
            handle.close()

        self._started_by_us = True
        self.adb.start_server()
        if not wait:
            return ""
        return self.wait_until_ready(known_serials=known)

    def _build_args(self, avd: str) -> list[str]:
        args = [self.binary, "-avd", avd, "-no-boot-anim", "-no-snapshot-save"]
        if settings.emulator_headless:
            args.append("-no-window")
        if settings.emulator_cold_boot:
            args.append("-no-snapshot-load")
        if settings.emulator_wipe_data:
            args.append("-wipe-data")
        gpu = (settings.emulator_gpu_mode or "").strip()
        if gpu:
            args += ["-gpu", gpu]
        args += ["-netdelay", "none", "-netspeed", "full"]
        extra = (settings.emulator_extra_args or "").strip()
        if extra:
            args += extra.split()
        return args

    def wait_until_ready(
        self,
        *,
        timeout: int | None = None,
        known_serials: set[str] | None = None,
    ) -> str:
        """Block until Android has fully booted, then return the serial.

        Readiness requires three signals, not just device presence:
        ``sys.boot_completed``, a stopped boot animation, and a responsive
        package manager (needed before any install can succeed).
        """
        limit = timeout or settings.emulator_boot_timeout_seconds
        deadline = time.monotonic() + limit
        previous = known_serials or set()
        serial = self._serial
        last_state = "waiting for device"

        while time.monotonic() < deadline:
            self._assert_process_alive()

            if serial is None:
                for item in self.adb.devices():
                    if item.is_emulator and (item.serial not in previous or item.is_ready):
                        serial = item.serial
                        break
            if serial is not None:
                device = self.adb.for_serial(serial)
                if not device.is_boot_completed():
                    last_state = "sys.boot_completed != 1"
                elif not device.is_boot_animation_stopped():
                    last_state = "boot animation still running"
                elif not device.is_package_manager_ready():
                    last_state = "package manager not responding"
                else:
                    self._serial = serial
                    self.adb.serial = serial
                    logger.info("Emulator %s is ready.", serial)
                    return serial
            time.sleep(BOOT_POLL_SECONDS)

        raise EmulatorBootTimeoutError(
            f"Emulator did not become ready within {limit}s (last state: {last_state})."
        ).with_output(command="emulator boot", stderr=self._log_tail())

    def _assert_process_alive(self) -> None:
        if self._process is None:
            return
        code = self._process.poll()
        if code is not None:
            raise EmulatorStartError(
                f"The emulator process exited early with code {code}."
            ).with_output(command="emulator", stderr=self._log_tail())

    def _log_tail(self, limit: int = 4000) -> str:
        if self._log_path is None or not self._log_path.is_file():
            return ""
        try:
            return self._log_path.read_text(encoding="utf-8", errors="replace")[-limit:]
        except OSError:
            return ""

    def ensure_ready(self, avd_name: str | None = None) -> str:
        """Reuse a running emulator or boot one, returning a ready serial."""
        if self.preferred_serial:
            serial = self.preferred_serial
            self._serial = serial
            self.adb.serial = serial
            device = self.adb.for_serial(serial)
            # If the preferred device is already online, wait until ready.
            online = {item.serial for item in self.adb.devices()}
            if serial in online:
                if device.is_boot_completed() and device.is_package_manager_ready():
                    return serial
                return self.wait_until_ready()
            # Preferred serial not online yet — start AVD then bind to it.
            return self.start(avd_name)

        existing = self.running_serial()
        if existing:
            self._serial = existing
            self.adb.serial = existing
            device = self.adb.for_serial(existing)
            if device.is_boot_completed() and device.is_package_manager_ready():
                return existing
            return self.wait_until_ready()
        return self.start(avd_name)

    def stop(self, *, force: bool = False) -> bool:
        """Shut down the emulator. Returns True when a shutdown was issued.

        By default only an emulator this manager started is stopped, so a
        developer's manually launched emulator survives. Pass ``force=True``
        to override.
        """
        if self._serial is None:
            return False
        if not self._started_by_us and not force:
            logger.info("Leaving emulator %s running (not started by us).", self._serial)
            return False

        serial = self._serial
        logger.info("Stopping emulator %s", serial)
        result = self.adb.for_serial(serial).emu_kill()
        if not result.ok:
            logger.warning("adb emu kill failed: %s", result.fail_message("emu kill"))

        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if all(item.serial != serial for item in self.adb.devices()):
                self._finalize_stop()
                return True
            time.sleep(STOP_POLL_SECONDS)

        if self._process is not None and self._process.poll() is None:
            logger.warning("Emulator %s did not exit; terminating process.", serial)
            self._process.terminate()
            try:
                self._process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._finalize_stop()
            return True

        raise EmulatorStopError(
            f"Emulator {serial} did not shut down within 45s."
        ).with_output(command="adb emu kill", stderr=self._log_tail())

    def _finalize_stop(self) -> None:
        self._process = None
        self._serial = None
        self._started_by_us = False

    def reset(self, *, wipe_data: bool = False) -> str:
        """Return the device to a clean state.

        ``wipe_data`` performs a factory reset by restarting the AVD with
        ``-wipe-data``, which requires that we own the emulator process.
        """
        if wipe_data:
            avd = self.avd_name
            self.stop(force=True)
            find_emulator.cache_clear()
            resolved = self.resolve_avd(avd)
            known = {item.serial for item in self.adb.devices()}
            args = self._build_args(resolved)
            if "-wipe-data" not in args:
                args.append("-wipe-data")
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            self._log_path = _log_dir() / f"{resolved}-wipe-{stamp}.log"
            with self._log_path.open("wb") as handle:
                self._process = subprocess.Popen(
                    args,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    cwd=str(Path(self.binary).parent),
                    creationflags=_detached_flags(),
                    close_fds=True,
                )
            self._started_by_us = True
            return self.wait_until_ready(known_serials=known)

        serial = self._serial or self.adb.pick_device()
        device = self.adb.for_serial(serial)
        # Dismiss the keyguard and return to the launcher.
        device.shell("input keyevent KEYCODE_WAKEUP", check=False)
        device.shell("wm dismiss-keyguard", check=False)
        device.shell("input keyevent KEYCODE_HOME", check=False)
        return serial

    # -- context manager -----------------------------------------------------

    def __enter__(self) -> "EmulatorManager":
        self.ensure_ready()
        return self

    def __exit__(self, *_exc: object) -> None:
        if settings.emulator_stop_when_done:
            try:
                self.stop()
            except EmulatorStopError:
                logger.warning("Emulator shutdown failed during cleanup", exc_info=True)
