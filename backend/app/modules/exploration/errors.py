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


class AdbUnavailableError(ExplorationError):
    def __init__(self, message: str = "The adb binary was not found.") -> None:
        super().__init__("ADB_UNAVAILABLE", message, http_status=503)


class NoDeviceError(ExplorationError):
    def __init__(self, message: str = "No Android emulator or device is connected.") -> None:
        super().__init__("NO_DEVICE", message, http_status=503)


class AdbCommandError(ExplorationError):
    def __init__(self, message: str) -> None:
        super().__init__("ADB_COMMAND_FAILED", message)


class AdbTimeoutError(ExplorationError):
    def __init__(self, message: str = "An adb command timed out.") -> None:
        super().__init__("ADB_TIMEOUT", message, http_status=504)


class ApkInstallError(ExplorationError):
    def __init__(self, message: str = "The APK could not be installed on the device.") -> None:
        super().__init__("APK_INSTALL_FAILED", message)


class AppLaunchError(ExplorationError):
    def __init__(self, message: str = "The application could not be launched.") -> None:
        super().__init__("APP_LAUNCH_FAILED", message)
