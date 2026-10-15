from __future__ import annotations

from app.core.errors import AppError


class ExplorationError(AppError):
    """Base error for the dynamic exploration stage.

    Exploration is a best-effort enrichment: static APK analysis must still be
    returned when the emulator layer fails. Callers should therefore catch these
    and degrade to ``ExplorationResult.failed(...)`` rather than failing the request.
    """

    def __init__(self, code: str, message: str, http_status: int = 500) -> None:
        super().__init__(code, message, http_status=http_status)
        self.stdout: str | None = None
        self.stderr: str | None = None
        self.command: str | None = None

    def with_output(
        self,
        command: str | None = None,
        stdout: str | None = None,
        stderr: str | None = None,
    ) -> "ExplorationError":
        """Attach captured process output so failures are never silent."""
        self.command = command
        self.stdout = stdout
        self.stderr = stderr
        return self

    def details(self) -> dict[str, str]:
        body: dict[str, str] = {"code": self.code, "message": self.message}
        if self.command:
            body["command"] = self.command
        if self.stdout:
            body["stdout"] = self.stdout[-2000:]
        if self.stderr:
            body["stderr"] = self.stderr[-2000:]
        return body


# --- Tooling availability ----------------------------------------------------


class AdbUnavailableError(ExplorationError):
    def __init__(self, message: str = "The adb binary was not found.") -> None:
        super().__init__("ADB_UNAVAILABLE", message, http_status=503)


class EmulatorUnavailableError(ExplorationError):
    def __init__(self, message: str = "The Android emulator binary was not found.") -> None:
        super().__init__("EMULATOR_UNAVAILABLE", message, http_status=503)


class AvdNotFoundError(ExplorationError):
    def __init__(self, message: str = "The configured AVD does not exist.") -> None:
        super().__init__("AVD_NOT_FOUND", message, http_status=503)


# --- Device lifecycle --------------------------------------------------------


class NoDeviceError(ExplorationError):
    def __init__(self, message: str = "No Android emulator or device is connected.") -> None:
        super().__init__("NO_DEVICE", message, http_status=503)


class EmulatorStartError(ExplorationError):
    def __init__(self, message: str = "The Android emulator failed to start.") -> None:
        super().__init__("EMULATOR_START_FAILED", message)


class EmulatorBootTimeoutError(ExplorationError):
    def __init__(self, message: str = "The Android emulator did not finish booting in time.") -> None:
        super().__init__("EMULATOR_BOOT_TIMEOUT", message, http_status=504)


class EmulatorStopError(ExplorationError):
    def __init__(self, message: str = "The Android emulator could not be stopped.") -> None:
        super().__init__("EMULATOR_STOP_FAILED", message)


# --- adb command execution ---------------------------------------------------


class AdbCommandError(ExplorationError):
    def __init__(self, message: str) -> None:
        super().__init__("ADB_COMMAND_FAILED", message)


class AdbTimeoutError(ExplorationError):
    def __init__(self, message: str = "An adb command timed out.") -> None:
        super().__init__("ADB_TIMEOUT", message, http_status=504)


# --- Application lifecycle ---------------------------------------------------


class ApkInstallError(ExplorationError):
    def __init__(self, message: str = "The APK could not be installed on the device.") -> None:
        super().__init__("APK_INSTALL_FAILED", message)


class ApkUninstallError(ExplorationError):
    def __init__(self, message: str = "The package could not be uninstalled.") -> None:
        super().__init__("APK_UNINSTALL_FAILED", message)


class PackageNotFoundError(ExplorationError):
    def __init__(self, message: str = "The package is not installed on the device.") -> None:
        super().__init__("PACKAGE_NOT_FOUND", message, http_status=404)


class ActivityNotFoundError(ExplorationError):
    def __init__(self, message: str = "No launchable activity was found for the package.") -> None:
        super().__init__("ACTIVITY_NOT_FOUND", message, http_status=404)


class AppLaunchError(ExplorationError):
    def __init__(self, message: str = "The application could not be launched.") -> None:
        super().__init__("APP_LAUNCH_FAILED", message)


# --- UIAutomator / UI interaction --------------------------------------------


class UiDumpError(ExplorationError):
    def __init__(self, message: str = "UIAutomator could not dump the current UI hierarchy.") -> None:
        super().__init__("UI_DUMP_FAILED", message)


class UiParseError(ExplorationError):
    def __init__(self, message: str = "The UIAutomator XML dump could not be parsed.") -> None:
        super().__init__("UI_PARSE_FAILED", message)


class UiActionError(ExplorationError):
    def __init__(self, message: str = "The UI action could not be performed.") -> None:
        super().__init__("UI_ACTION_FAILED", message)


# --- Screenshots / screen-state detection ------------------------------------


class ScreenshotCaptureError(ExplorationError):
    def __init__(self, message: str = "The device screenshot could not be captured.") -> None:
        super().__init__("SCREENSHOT_CAPTURE_FAILED", message)


class ScreenshotDecodeError(ExplorationError):
    def __init__(self, message: str = "The screenshot image could not be decoded.") -> None:
        super().__init__("SCREENSHOT_DECODE_FAILED", message)


class StateDetectionError(ExplorationError):
    def __init__(self, message: str = "Screen state detection failed.") -> None:
        super().__init__("STATE_DETECTION_FAILED", message)


# --- Exploration engine ------------------------------------------------------


class ExplorationLimitError(ExplorationError):
    def __init__(self, message: str = "Exploration stopped after hitting a configured limit.") -> None:
        super().__init__("EXPLORATION_LIMIT", message, http_status=200)


class ExplorationEngineError(ExplorationError):
    def __init__(self, message: str = "The exploration engine failed.") -> None:
        super().__init__("EXPLORATION_ENGINE_FAILED", message)
