from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

from app.modules.exploration.adb import AndroidADB, CommandResult
from app.modules.exploration.errors import (
    ActivityNotFoundError,
    AppLaunchError,
)

logger = logging.getLogger(__name__)

_RESOLVE_COMPONENT = re.compile(r"^\s*([A-Za-z0-9_.]+)/(\S+)\s*$", re.MULTILINE)
_FOCUS_COMPONENT = re.compile(r"([A-Za-z0-9_.]+)/([A-Za-z0-9_.$]+)")
_AM_ERROR = re.compile(r"(Error:|Exception|Activity not started|does not exist)", re.IGNORECASE)
_ACTIVITY_NAME = re.compile(
    r"([A-Za-z0-9_.]+(?:\.[A-Za-z0-9_]+)*Activity)\b"
)

# Prefer real app UI over splash / fake-home shells.
_CONTENT_ACTIVITY_HINTS = (
    ".ui.activities.main.MainActivity",
    ".activities.main.MainActivity",
    ".main.MainActivity",
    ".ui.main.MainActivity",
    ".MainActivity",
    "MainActivity",
)
_AVOID_ACTIVITY_TOKENS = (
    "splash",
    "launcherhome",
    "defaultapp",
    "intro",
    "permission",
    "overlay",
    "callend",
)


@dataclass
class LaunchOutcome:
    package_name: str
    activity: str | None
    component: str | None
    method: str
    foreground: bool
    duration_ms: int
    warnings: list[str]


class AppLauncher:
    """Starts, inspects and stops the application under analysis."""

    def __init__(self, adb: AndroidADB) -> None:
        self.adb = adb

    # -- activity resolution -------------------------------------------------

    def resolve_launch_activity(self, package_name: str) -> str | None:
        """Ask the device's package manager for the launcher activity.

        This is the fallback used when the static APK analysis did not yield a
        MAIN/LAUNCHER activity.
        """
        result = self.adb.shell(
            "cmd package resolve-activity --brief -c android.intent.category.LAUNCHER "
            f"-a android.intent.action.MAIN {package_name}",
            timeout=30,
            check=False,
        )
        activity = self._parse_component(result, package_name)
        if activity:
            return activity

        # Older images lack `cmd package`; fall back to parsing the intent dump.
        dump = self.adb.shell(
            "dumpsys package "
            f"{package_name} | grep -A 3 android.intent.action.MAIN",
            timeout=45,
            check=False,
        )
        activity = self._parse_component(dump, package_name)
        if activity:
            return activity

        monkey = self.adb.shell(
            f"pm dump {package_name}", timeout=60, check=False
        )
        return self._parse_component(monkey, package_name)

    def _parse_component(self, result: CommandResult, package_name: str) -> str | None:
        if not result.ok:
            return None
        for match in _RESOLVE_COMPONENT.finditer(result.stdout):
            pkg, activity = match.group(1), match.group(2)
            if pkg == package_name and activity and activity != "null":
                return activity
        return None

    def component_for(self, package_name: str, activity: str) -> str:
        """Build a `pkg/activity` component, accepting relative or absolute names."""
        if activity.startswith("."):
            return f"{package_name}/{activity}"
        if activity.startswith(f"{package_name}."):
            return f"{package_name}/{activity}"
        if "." not in activity:
            return f"{package_name}/.{activity}"
        return f"{package_name}/{activity}"

    # -- launching -----------------------------------------------------------

    def launch(
        self,
        package_name: str,
        activity: str | None = None,
        *,
        wait_for_foreground: bool = True,
        timeout: int = 60,
    ) -> LaunchOutcome:
        """Launch the app, preferring an explicit activity and falling back to monkey."""
        started = time.perf_counter()
        warnings: list[str] = []
        resolved = activity

        if not resolved:
            resolved = self.resolve_launch_activity(package_name)
            if resolved:
                warnings.append(
                    "Launch activity was resolved on-device because static analysis "
                    "did not provide one."
                )

        method = "am_start"
        component: str | None = None
        if resolved:
            component = self.component_for(package_name, resolved)
            result = self.adb.shell(
                f"am start -W -n {component} "
                "-a android.intent.action.MAIN -c android.intent.category.LAUNCHER",
                timeout=timeout,
                check=False,
            )
            if not self._am_start_ok(result):
                warnings.append(
                    f"am start on {component} failed; retrying with monkey. "
                    f"Output: {result.output.strip()[:200]}"
                )
                self._monkey_launch(package_name, timeout=timeout)
                method = "monkey"
        else:
            # No activity anywhere: monkey asks the launcher to open the app.
            method = "monkey"
            warnings.append(
                "No launcher activity was found; used monkey to start the app."
            )
            self._monkey_launch(package_name, timeout=timeout)

        foreground = False
        if wait_for_foreground:
            foreground = self.wait_until_foreground(package_name, timeout=timeout)
            if not foreground:
                raise AppLaunchError(
                    f"'{package_name}' did not reach the foreground within {timeout}s. "
                    f"Current focus: {self.current_component() or 'unknown'}."
                ).with_output(command=f"am start {component or package_name}")

        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "Launched %s via %s in %sms (foreground=%s)",
            package_name,
            method,
            duration_ms,
            foreground,
        )
        return LaunchOutcome(
            package_name=package_name,
            activity=resolved,
            component=component,
            method=method,
            foreground=foreground,
            duration_ms=duration_ms,
            warnings=warnings,
        )

    def _am_start_ok(self, result: CommandResult) -> bool:
        if not result.ok:
            return False
        return not _AM_ERROR.search(result.output)

    def _monkey_launch(self, package_name: str, *, timeout: int = 60) -> None:
        result = self.adb.shell(
            f"monkey -p {package_name} -c android.intent.category.LAUNCHER 1",
            timeout=timeout,
            check=False,
        )
        text = result.output.lower()
        if not result.ok or "no activities found" in text or "error" in text:
            raise ActivityNotFoundError(
                f"No launchable activity found for '{package_name}'."
            ).with_output(command=result.command, stdout=result.stdout, stderr=result.stderr)

    # -- inspection ----------------------------------------------------------

    def current_component(self) -> str | None:
        """Best-effort read of the focused `package/activity`."""
        for command in (
            "dumpsys window displays | grep -E 'mCurrentFocus|mFocusedApp'",
            "dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'",
            "dumpsys activity activities | grep -E 'ResumedActivity|mResumedActivity'",
        ):
            result = self.adb.shell(command, timeout=30, check=False)
            if not result.ok or not result.stdout.strip():
                continue
            match = _FOCUS_COMPONENT.search(result.stdout)
            if match:
                return f"{match.group(1)}/{match.group(2)}"
        return None

    def current_package(self) -> str | None:
        component = self.current_component()
        return component.split("/", 1)[0] if component else None

    def is_foreground(self, package_name: str) -> bool:
        return self.current_package() == package_name

    def is_running(self, package_name: str) -> bool:
        result = self.adb.shell(f"pidof {package_name}", timeout=20, check=False)
        if result.ok and result.stdout.strip():
            return True
        ps = self.adb.shell(f"ps -A | grep {package_name}", timeout=30, check=False)
        return bool(ps.ok and package_name in ps.stdout)

    def wait_until_foreground(self, package_name: str, *, timeout: int = 60) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.is_foreground(package_name):
                return True
            # A splash screen may hand off to another process; a live pid is enough.
            if self.is_running(package_name) and self.current_package() is None:
                return True
            time.sleep(1)
        return False

    # -- teardown ------------------------------------------------------------

    def force_stop(self, package_name: str) -> CommandResult:
        result = self.adb.shell(f"am force-stop {package_name}", timeout=45, check=False)
        if not result.ok:
            logger.warning(
                "force-stop of %s failed: %s", package_name, result.fail_message("force-stop")
            )
        return result

    def go_home(self) -> CommandResult:
        return self.adb.shell("input keyevent KEYCODE_HOME", timeout=30, check=False)

    # -- home-role / content launch -----------------------------------------

    def home_role_holders(self) -> list[str]:
        result = self.adb.shell(
            "cmd role get-role-holders android.app.role.HOME",
            timeout=30,
            check=False,
        )
        if not result.ok:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def ensure_system_home(self, *, avoid_package: str | None = None) -> None:
        """Make sure the target app is not the device Home launcher.

        Apps that hijack HOME (``LauncherHomeActivity``) leave exploration stuck
        on a non-interactive shell. Restore Nexus / Launcher3 instead.
        """
        holders = self.home_role_holders()
        if avoid_package and avoid_package in holders:
            self.adb.shell(
                f"cmd role remove-role-holder android.app.role.HOME {avoid_package}",
                timeout=30,
                check=False,
            )
            logger.info("Removed HOME role from %s (holders were %s)", avoid_package, holders)

        for candidate in (
            "com.google.android.apps.nexuslauncher/"
            "com.google.android.apps.nexuslauncher.NexusLauncherActivity",
            "com.android.launcher3/com.android.launcher3.Launcher",
            "com.android.launcher3/.Launcher",
        ):
            set_home = self.adb.shell(
                f"cmd package set-home-activity {candidate}",
                timeout=30,
                check=False,
            )
            if set_home.ok and "Error" not in set_home.output:
                pkg = candidate.split("/", 1)[0]
                self.adb.shell(
                    f"cmd role add-role-holder android.app.role.HOME {pkg}",
                    timeout=30,
                    check=False,
                )
                logger.info("System home set to %s", candidate)
                break

        self.go_home()
        time.sleep(0.6)

    def list_package_activities(self, package_name: str) -> list[str]:
        """Best-effort activity class names from dumpsys package."""
        result = self.adb.shell(f"dumpsys package {package_name}", timeout=60, check=False)
        if not result.ok:
            return []
        found: list[str] = []
        seen: set[str] = set()
        for match in _ACTIVITY_NAME.finditer(result.stdout):
            name = match.group(1)
            if not name.startswith(package_name):
                continue
            if name in seen:
                continue
            seen.add(name)
            found.append(name)
        return found

    def resolve_content_activity(self, package_name: str) -> str | None:
        """Pick a real content Activity (Main…), never Splash / LauncherHome."""
        activities = self.list_package_activities(package_name)

        def _bad(name: str) -> bool:
            lowered = name.lower()
            return any(token in lowered for token in _AVOID_ACTIVITY_TOKENS)

        for activity in activities:
            if "mainactivity" in activity.lower() and not _bad(activity):
                return activity

        for hint in (
            ".ui.activities.main.MainActivity",
            ".activities.main.MainActivity",
            ".main.MainActivity",
            ".MainActivity",
        ):
            absolute = f"{package_name}{hint}"
            if absolute in activities:
                return hint

        for activity in activities:
            if not _bad(activity):
                return activity

        # Last resort for apps whose dumpsys listing is incomplete.
        return ".ui.activities.main.MainActivity"

    def content_activity_candidates(
        self, package_name: str, preferred: str | None = None
    ) -> list[str]:
        ordered: list[str] = []
        # Prefer the real MAIN/LAUNCHER activity first — hardcoded MainActivity
        # paths often do not exist and caused open/kill loops.
        launcher = self.resolve_launch_activity(package_name)
        content = self.resolve_content_activity(package_name)

        def _avoid(name: str | None) -> bool:
            if not name:
                return True
            lowered = name.lower()
            return any(token in lowered for token in _AVOID_ACTIVITY_TOKENS)

        for item in (
            content,
            launcher,
            preferred,  # preferred last if it is splash/default — avoid Splash→Ad loops
            ".ui.activities.main.MainActivity",
            ".ui.activity.MainActivity",
            ".MainActivity",
        ):
            if not item or item in ordered:
                continue
            # Never put splash / default-app / launcher-home first.
            if _avoid(item) and item is preferred:
                continue
            if _avoid(item) and item in (
                ".ui.activities.main.MainActivity",
                ".ui.activity.MainActivity",
                ".MainActivity",
            ):
                continue
            # Skip known-bad relative guesses when dumpsys already gave a launcher.
            if item.startswith(".") and "MainActivity" in item and launcher:
                activities = self.list_package_activities(package_name)
                absolute = f"{package_name}{item}" if item.startswith(".") else item
                if absolute not in activities and not any(
                    a.endswith(item.lstrip(".")) for a in activities
                ):
                    continue
            ordered.append(item)
        # Last resort: allow preferred even if splash-like so resume still has a target.
        if preferred and preferred not in ordered:
            ordered.append(preferred)
        return ordered

    def resume_app(
        self,
        package_name: str,
        activity: str | None = None,
        *,
        timeout: int = 60,
    ) -> LaunchOutcome:
        """Bring the app to the foreground *without* force-stop / Home spam.

        Used mid-exploration when we briefly left to the system launcher.
        """
        started = time.perf_counter()
        warnings: list[str] = []
        if self.is_foreground(package_name):
            current = self.current_component()
            return LaunchOutcome(
                package_name=package_name,
                activity=activity,
                component=current,
                method="already_foreground",
                foreground=True,
                duration_ms=0,
                warnings=warnings,
            )

        candidates = self.content_activity_candidates(package_name, activity)
        resolved: str | None = None
        component: str | None = None
        for candidate in candidates:
            component = self.component_for(package_name, candidate)
            result = self.adb.shell(
                f"am start -W -n {component}",
                timeout=timeout,
                check=False,
            )
            if not self._am_start_ok(result):
                warnings.append(f"resume am start failed for {component}")
                continue
            if self.wait_until_foreground(package_name, timeout=min(20, timeout)):
                resolved = candidate
                break

        if not resolved:
            warnings.append("resume candidates failed; using MAIN/LAUNCHER launch")
            return self.launch(package_name, activity, wait_for_foreground=True, timeout=timeout)

        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "Resumed %s -> %s in %sms (focus=%s)",
            package_name,
            resolved,
            duration_ms,
            self.current_component(),
        )
        return LaunchOutcome(
            package_name=package_name,
            activity=resolved,
            component=component,
            method="am_start_resume",
            foreground=True,
            duration_ms=duration_ms,
            warnings=warnings,
        )

    def prepare_and_launch(
        self,
        package_name: str,
        activity: str | None = None,
        *,
        prefer_content: bool = True,
        cold_start: bool = True,
        timeout: int = 60,
    ) -> LaunchOutcome:
        """Launch the app for exploration.

        ``cold_start=True`` (session start): may clear HOME role + force-stop once.
        Mid-run recovery should call :meth:`resume_app` instead.
        """
        if not cold_start:
            return self.resume_app(package_name, activity, timeout=timeout)

        # Only strip HOME role if *this* package hijacked it — avoid Home key spam.
        holders = self.home_role_holders()
        if package_name in holders:
            self.ensure_system_home(avoid_package=package_name)
        self.force_stop(package_name)
        time.sleep(0.5)

        started = time.perf_counter()
        warnings: list[str] = []
        candidates = (
            self.content_activity_candidates(package_name, activity)
            if prefer_content
            else [activity or self.resolve_launch_activity(package_name)]
        )
        candidates = [c for c in candidates if c]

        last_error = ""
        resolved: str | None = None
        component: str | None = None
        for candidate in candidates:
            component = self.component_for(package_name, candidate)
            result = self.adb.shell(
                f"am start -W -n {component}",
                timeout=timeout,
                check=False,
            )
            if not self._am_start_ok(result):
                last_error = result.output.strip()[:200]
                warnings.append(f"am start failed for {component}: {last_error}")
                continue
            if not self.wait_until_foreground(package_name, timeout=min(30, timeout)):
                last_error = f"not foreground after {component}"
                continue
            current = (self.current_component() or "").lower()
            if "launcherhome" in current:
                warnings.append(f"{component} opened LauncherHome; trying next candidate")
                continue
            resolved = candidate
            break

        if not resolved:
            warnings.append(f"content launch exhausted; fallback MAIN/LAUNCHER ({last_error})")
            return self.launch(
                package_name,
                activity,
                wait_for_foreground=True,
                timeout=timeout,
            )

        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "Prepared+launched %s -> %s in %sms (focus=%s)",
            package_name,
            resolved,
            duration_ms,
            self.current_component(),
        )
        return LaunchOutcome(
            package_name=package_name,
            activity=resolved,
            component=component,
            method="am_start_content",
            foreground=True,
            duration_ms=duration_ms,
            warnings=warnings,
        )
