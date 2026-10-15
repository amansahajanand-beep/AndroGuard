from __future__ import annotations

import logging
import re
from pathlib import Path

from app.core.config import settings
from app.modules.exploration.adb import AndroidADB, CommandResult
from app.modules.exploration.errors import (
    ApkInstallError,
    ApkUninstallError,
    PackageNotFoundError,
)

logger = logging.getLogger(__name__)

_INSTALL_FAILURE = re.compile(r"(Failure|Error)\s*\[?([A-Z_0-9]+)?\]?", re.IGNORECASE)
_VERSION_NAME = re.compile(r"versionName=(\S+)")


class APKManager:
    """Installs and removes packages on a connected device."""

    def __init__(self, adb: AndroidADB) -> None:
        self.adb = adb

    # -- queries -------------------------------------------------------------

    def list_packages(self, *, third_party_only: bool = False) -> list[str]:
        flag = "-3" if third_party_only else ""
        result = self.adb.shell(f"pm list packages {flag}".strip(), timeout=60)
        names: list[str] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("package:"):
                names.append(line[len("package:") :].strip())
        return names

    def is_installed(self, package_name: str) -> bool:
        """Exact-match installation check.

        Uses `pm path`, which avoids the substring false positives that
        `pm list packages <name>` produces.
        """
        if not package_name:
            return False
        result = self.adb.shell(f"pm path {package_name}", timeout=30, check=False)
        if result.ok and "package:" in result.stdout:
            return True
        # Some images return exit 0 with empty output; fall back to an exact scan.
        listing = self.adb.shell(
            f"pm list packages {package_name}", timeout=30, check=False
        )
        if not listing.ok:
            return False
        return any(
            line.strip() == f"package:{package_name}"
            for line in listing.stdout.splitlines()
        )

    def version_name(self, package_name: str) -> str | None:
        result = self.adb.shell(f"dumpsys package {package_name}", timeout=45, check=False)
        if not result.ok:
            return None
        match = _VERSION_NAME.search(result.stdout)
        return match.group(1) if match else None

    def require_installed(self, package_name: str) -> None:
        if not self.is_installed(package_name):
            raise PackageNotFoundError(
                f"Package '{package_name}' is not installed on {self.adb.serial or 'the device'}."
            )

    # -- mutations -----------------------------------------------------------

    def install(
        self,
        apk_path: str | Path,
        *,
        reinstall: bool = True,
        grant_permissions: bool = True,
        allow_test: bool = True,
        allow_downgrade: bool = True,
        timeout: int | None = None,
    ) -> CommandResult:
        """Install an APK, raising with captured output on failure."""
        path = Path(apk_path)
        if not path.is_file():
            raise ApkInstallError(f"APK not found at {path}.")

        args = ["install"]
        if reinstall:
            args.append("-r")
        if allow_test:
            args.append("-t")
        if grant_permissions:
            args.append("-g")
        if allow_downgrade:
            args.append("-d")
        args.append(str(path))

        result = self.adb.run(
            args,
            timeout=timeout or settings.apk_install_timeout_seconds,
            check=False,
        )
        self._assert_install_ok(result, path)
        logger.info("Installed %s in %sms", path.name, result.duration_ms)
        return result

    def _assert_install_ok(self, result: CommandResult, path: Path) -> None:
        """`adb install` can exit 0 while reporting Failure, so inspect the text."""
        combined = result.output
        succeeded = result.ok and "success" in combined.lower()
        if succeeded:
            return
        match = _INSTALL_FAILURE.search(combined)
        reason = match.group(2) if match and match.group(2) else None
        hint = _INSTALL_HINTS.get(reason or "", "")
        message = f"Installing {path.name} failed"
        if reason:
            message += f" [{reason}]"
        if hint:
            message += f". {hint}"
        raise ApkInstallError(message).with_output(
            command=result.command, stdout=result.stdout, stderr=result.stderr
        )

    def ensure_installed(
        self,
        apk_path: str | Path,
        package_name: str | None = None,
        *,
        force_reinstall: bool = False,
    ) -> bool:
        """Install only when needed. Returns True if an install was performed."""
        if package_name and not force_reinstall and self.is_installed(package_name):
            logger.info("Package %s is already installed; skipping install.", package_name)
            return False
        self.install(apk_path)
        if package_name:
            self.require_installed(package_name)
        return True

    def uninstall(self, package_name: str, *, keep_data: bool = False) -> CommandResult:
        args = ["uninstall"]
        if keep_data:
            args.append("-k")
        args.append(package_name)
        result = self.adb.run(args, timeout=120, check=False)
        if not (result.ok and "success" in result.output.lower()):
            raise ApkUninstallError(
                f"Uninstalling {package_name} failed."
            ).with_output(command=result.command, stdout=result.stdout, stderr=result.stderr)
        return result

    def clear_data(self, package_name: str) -> CommandResult:
        """Reset the app to a first-run state without reinstalling."""
        result = self.adb.shell(f"pm clear {package_name}", timeout=90, check=False)
        if not (result.ok and "success" in result.output.lower()):
            raise ApkInstallError(
                f"Clearing data for {package_name} failed."
            ).with_output(command=result.command, stdout=result.stdout, stderr=result.stderr)
        return result


_INSTALL_HINTS = {
    "INSTALL_FAILED_NO_MATCHING_ABIS": "The APK has native libraries incompatible with the emulator ABI; use an x86_64 system image.",
    "INSTALL_FAILED_OLDER_SDK": "The APK's minSdkVersion is higher than the emulator's Android version.",
    "INSTALL_FAILED_INSUFFICIENT_STORAGE": "The emulator is out of disk space; increase the AVD data partition.",
    "INSTALL_FAILED_UPDATE_INCOMPATIBLE": "A build with a different signature is installed; uninstall it first.",
    "INSTALL_FAILED_VERSION_DOWNGRADE": "A newer version is installed; uninstall it or install with -d.",
    "INSTALL_PARSE_FAILED_NO_CERTIFICATES": "The APK is unsigned.",
    "INSTALL_FAILED_INVALID_APK": "The APK is malformed, or it is a split/AAB rather than a standalone APK.",
}
