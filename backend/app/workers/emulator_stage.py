from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.core.config import settings
from app.jobs.models import JobStage
from app.modules.exploration.adb import AndroidADB
from app.modules.exploration.apk_manager import APKManager
from app.modules.exploration.emulator import EmulatorManager
from app.modules.exploration.errors import ExplorationError
from app.modules.exploration.launcher import AppLauncher, LaunchOutcome
from app.modules.exploration.target import LaunchTarget, target_from_analysis, target_from_apk
from app.schemas.exploration import DeviceInfo

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[JobStage], None]


@dataclass
class DeviceStageResult:
    """Outcome of the Phase 1 device stage: boot, install, launch."""

    status: str = "failed"
    device: DeviceInfo | None = None
    target: LaunchTarget | None = None
    installed_now: bool = False
    already_installed: bool = False
    launch: LaunchOutcome | None = None
    emulator_serial: str | None = None
    emulator_started_by_us: bool = False
    duration_ms: int = 0
    warnings: list[str] = field(default_factory=list)
    error: dict[str, str] | None = None

    @property
    def ok(self) -> bool:
        return self.status == "completed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "device": self.device.model_dump() if self.device else None,
            "target": (
                {
                    "package_name": self.target.package_name,
                    "activity": self.target.activity,
                    "source": self.target.source,
                }
                if self.target
                else None
            ),
            "installed_now": self.installed_now,
            "already_installed": self.already_installed,
            "launch": (
                {
                    "component": self.launch.component,
                    "activity": self.launch.activity,
                    "method": self.launch.method,
                    "foreground": self.launch.foreground,
                    "duration_ms": self.launch.duration_ms,
                }
                if self.launch
                else None
            ),
            "emulator_serial": self.emulator_serial,
            "duration_ms": self.duration_ms,
            "warnings": self.warnings,
            "error": self.error,
        }


def resolve_target(
    apk_path: str | Path,
    *,
    analysis: Any = None,
    package_name: str | None = None,
    activity: str | None = None,
) -> LaunchTarget:
    """Prefer the existing APK JSON extraction, then explicit args, then reparse.

    On-device package-manager resolution is the last resort and happens later,
    inside :meth:`AppLauncher.launch`.
    """
    if package_name:
        return LaunchTarget(package_name=package_name, activity=activity, source="explicit")
    if analysis is not None:
        target = target_from_analysis(analysis)
        if target is not None:
            if activity and not target.activity:
                target.activity = activity
            return target
        logger.warning("Analysis payload carried no package name; reparsing the APK.")
    return target_from_apk(apk_path)


def run_device_stage(
    apk_path: str | Path,
    *,
    analysis: Any = None,
    package_name: str | None = None,
    activity: str | None = None,
    avd_name: str | None = None,
    progress: ProgressCallback | None = None,
    force_reinstall: bool = False,
    stop_emulator: bool | None = None,
    uninstall_after: bool = False,
    keep_app_running: bool = False,
) -> DeviceStageResult:
    """Boot the emulator, install the APK and launch it.

    Returns a structured result; failures are captured (with the underlying
    stdout/stderr) rather than raised, so the caller can still return the static
    analysis. Nothing is ever ignored silently: every failure is logged.
    """
    started = time.perf_counter()
    result = DeviceStageResult()
    emulator = EmulatorManager(avd_name=avd_name)
    launcher: AppLauncher | None = None

    def announce(stage: JobStage) -> None:
        if progress is not None:
            try:
                progress(stage)
            except Exception:  # progress reporting must never fail the stage
                logger.warning("Progress callback failed for %s", stage, exc_info=True)

    try:
        path = Path(apk_path)
        if not path.is_file():
            raise ExplorationError("INVALID_FILE", f"APK not found at {path}.")

        result.target = resolve_target(
            path, analysis=analysis, package_name=package_name, activity=activity
        )
        if not result.target.activity:
            result.warnings.append(
                "No launcher activity came from static analysis; it will be resolved on-device."
            )

        announce(JobStage.EMULATOR_BOOT)
        serial = emulator.ensure_ready()
        result.emulator_serial = serial
        result.emulator_started_by_us = emulator.started_by_us

        adb = AndroidADB(serial=serial)
        result.device = adb.describe()

        apk_manager = APKManager(adb)
        launcher = AppLauncher(adb)

        announce(JobStage.APK_INSTALL)
        result.already_installed = apk_manager.is_installed(result.target.package_name)
        result.installed_now = apk_manager.ensure_installed(
            path,
            result.target.package_name,
            force_reinstall=force_reinstall,
        )

        announce(JobStage.APP_LAUNCH)
        result.launch = launcher.launch(result.target.package_name, result.target.activity)
        result.warnings.extend(result.launch.warnings)
        result.status = "completed"

    except ExplorationError as exc:
        result.error = exc.details()
        logger.error(
            "Device stage failed [%s]: %s | stdout=%s | stderr=%s",
            exc.code,
            exc.message,
            (exc.stdout or "")[-500:],
            (exc.stderr or "")[-500:],
        )
    except Exception as exc:
        result.error = {"code": "DEVICE_STAGE_ERROR", "message": str(exc)}
        logger.exception("Unexpected failure in the device stage")

    finally:
        _teardown(
            emulator=emulator,
            launcher=launcher,
            result=result,
            stop_emulator=stop_emulator,
            uninstall_after=uninstall_after,
            keep_app_running=keep_app_running,
        )
        result.duration_ms = int((time.perf_counter() - started) * 1000)

    return result


def _teardown(
    *,
    emulator: EmulatorManager,
    launcher: AppLauncher | None,
    result: DeviceStageResult,
    stop_emulator: bool | None,
    uninstall_after: bool,
    keep_app_running: bool,
) -> None:
    """Best-effort cleanup. Failures here are logged, never masked as stage errors."""
    package = result.target.package_name if result.target else None

    if launcher is not None and package and not keep_app_running:
        try:
            launcher.force_stop(package)
        except Exception:
            logger.warning("Could not force-stop %s", package, exc_info=True)

    if uninstall_after and package and result.installed_now and result.emulator_serial:
        try:
            APKManager(AndroidADB(serial=result.emulator_serial)).uninstall(package)
        except Exception:
            logger.warning("Could not uninstall %s", package, exc_info=True)

    should_stop = settings.emulator_stop_when_done if stop_emulator is None else stop_emulator
    if should_stop:
        try:
            emulator.stop()
        except Exception:
            logger.warning("Could not stop the emulator", exc_info=True)
