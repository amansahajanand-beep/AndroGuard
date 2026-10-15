from __future__ import annotations

import pytest

from app.modules.exploration.adb import AdbDevice, AndroidADB, CommandResult
from app.modules.exploration.apk_manager import APKManager
from app.modules.exploration.errors import (
    ActivityNotFoundError,
    AdbCommandError,
    ApkInstallError,
    NoDeviceError,
    PackageNotFoundError,
)
from app.modules.exploration.launcher import AppLauncher
from app.modules.exploration.target import launcher_activity, target_from_analysis

DEVICES_OUTPUT = """List of devices attached
emulator-5554\tdevice
ZY223KLM\tunauthorized
"""


class FakeRunner:
    """Matches commands by substring and returns canned output."""

    def __init__(self, responses: dict[str, tuple[int, str, str]]) -> None:
        self.responses = responses
        self.calls: list[list[str]] = []

    def __call__(self, args, timeout):  # noqa: ANN001 - matches the Runner protocol
        args = list(args)
        self.calls.append(args)
        joined = " ".join(args)
        for needle, (code, out, err) in self.responses.items():
            if needle in joined:
                return CommandResult(tuple(args), code, out, err, 1)
        return CommandResult(tuple(args), 0, "", "", 1)

    def commands(self) -> str:
        return "\n".join(" ".join(call) for call in self.calls)


def make_adb(responses: dict[str, tuple[int, str, str]], serial: str | None = "emulator-5554"):
    runner = FakeRunner(responses)
    adb = AndroidADB(binary="adb", serial=serial, runner=runner)
    return adb, runner


# --- AndroidADB --------------------------------------------------------------


def test_devices_parses_states_and_ignores_header():
    adb, _ = make_adb({"devices": (0, DEVICES_OUTPUT, "")})
    devices = adb.devices()
    assert devices == [
        AdbDevice("emulator-5554", "device"),
        AdbDevice("ZY223KLM", "unauthorized"),
    ]
    assert [d.serial for d in adb.ready_devices()] == ["emulator-5554"]
    assert devices[0].is_emulator is True


def test_devices_command_omits_serial_flag():
    adb, runner = make_adb({"devices": (0, DEVICES_OUTPUT, "")})
    adb.devices()
    assert "-s emulator-5554" not in runner.commands()


def test_shell_commands_include_serial():
    adb, runner = make_adb({"getprop": (0, "1\n", "")})
    assert adb.is_boot_completed() is True
    assert "-s emulator-5554" in runner.commands()


def test_boot_animation_unknown_counts_as_stopped():
    adb, _ = make_adb({"init.svc.bootanim": (1, "", "error")})
    assert adb.is_boot_animation_stopped() is True


def test_failed_command_raises_with_captured_output():
    adb, _ = make_adb({"boom": (1, "partial stdout", "device offline")})
    with pytest.raises(AdbCommandError) as excinfo:
        adb.run(["boom"])
    error = excinfo.value
    assert "device offline" in error.message
    assert error.stderr == "device offline"
    assert error.stdout == "partial stdout"
    assert error.details()["code"] == "ADB_COMMAND_FAILED"


def test_check_false_returns_failure_without_raising():
    adb, _ = make_adb({"boom": (1, "", "nope")})
    result = adb.run(["boom"], check=False)
    assert result.ok is False
    assert result.returncode == 1


def test_command_result_reports_failure_detail():
    result = CommandResult(("adb", "install"), 1, "", "device offline", 5)
    assert result.ok is False
    assert "device offline" in result.fail_message("install failed")


def test_pick_device_prefers_emulator():
    adb, _ = make_adb({"devices": (0, DEVICES_OUTPUT, "")}, serial=None)
    assert adb.pick_device() == "emulator-5554"


def test_pick_device_rejects_unknown_serial():
    adb, _ = make_adb({"devices": (0, DEVICES_OUTPUT, "")}, serial=None)
    with pytest.raises(NoDeviceError):
        adb.pick_device("emulator-9999")


def test_pick_device_raises_when_nothing_ready():
    adb, _ = make_adb({"devices": (0, "List of devices attached\n", "")}, serial=None)
    with pytest.raises(NoDeviceError):
        adb.pick_device()


# --- APKManager --------------------------------------------------------------


def test_is_installed_true_via_pm_path():
    adb, _ = make_adb({"pm path com.example": (0, "package:/data/app/base.apk\n", "")})
    assert APKManager(adb).is_installed("com.example") is True


def test_is_installed_avoids_substring_false_positive():
    adb, _ = make_adb(
        {
            "pm path com.example": (1, "", ""),
            "pm list packages com.example": (0, "package:com.example.other\n", ""),
        }
    )
    assert APKManager(adb).is_installed("com.example") is False


def test_install_success():
    adb, runner = make_adb({"install": (0, "Success\n", "")})
    manager = APKManager(adb)
    result = manager.install(__file__)  # any existing file works with a fake runner
    assert result.ok
    assert "-r" in runner.commands() and "-g" in runner.commands()


def test_install_failure_with_zero_exit_is_detected():
    # adb historically exits 0 while printing Failure.
    adb, _ = make_adb({"install": (0, "Failure [INSTALL_FAILED_NO_MATCHING_ABIS]", "")})
    with pytest.raises(ApkInstallError) as excinfo:
        APKManager(adb).install(__file__)
    assert "INSTALL_FAILED_NO_MATCHING_ABIS" in str(excinfo.value)
    assert "x86_64" in str(excinfo.value)


def test_install_missing_file_raises():
    adb, _ = make_adb({})
    with pytest.raises(ApkInstallError):
        APKManager(adb).install("does-not-exist.apk")


def test_require_installed_raises_package_not_found():
    adb, _ = make_adb({"pm path": (1, "", ""), "pm list packages": (0, "", "")})
    with pytest.raises(PackageNotFoundError):
        APKManager(adb).require_installed("com.missing")


def test_ensure_installed_skips_when_present():
    adb, runner = make_adb({"pm path com.example": (0, "package:/data/app/base.apk", "")})
    assert APKManager(adb).ensure_installed(__file__, "com.example") is False
    assert "install" not in runner.commands()


# --- AppLauncher -------------------------------------------------------------


def test_resolve_launch_activity_from_cmd_package():
    adb, _ = make_adb(
        {"resolve-activity": (0, "com.example/com.example.MainActivity\n", "")}
    )
    activity = AppLauncher(adb).resolve_launch_activity("com.example")
    assert activity == "com.example.MainActivity"


def test_component_for_handles_relative_and_absolute():
    adb, _ = make_adb({})
    launcher = AppLauncher(adb)
    assert launcher.component_for("com.x", ".Main") == "com.x/.Main"
    assert launcher.component_for("com.x", "com.x.Main") == "com.x/com.x.Main"
    assert launcher.component_for("com.x", "Main") == "com.x/.Main"


def test_launch_succeeds_with_known_activity():
    adb, runner = make_adb(
        {
            "am start": (0, "Status: ok\n", ""),
            "mCurrentFocus": (0, "mCurrentFocus=Window{a u0 com.example/com.example.Main}", ""),
        }
    )
    outcome = AppLauncher(adb).launch("com.example", "com.example.Main")
    assert outcome.foreground is True
    assert outcome.method == "am_start"
    assert "com.example/com.example.Main" in runner.commands()


def test_launch_falls_back_to_monkey_when_am_start_errors():
    adb, runner = make_adb(
        {
            "am start": (0, "Error: Activity not started", ""),
            "monkey": (0, "Events injected: 1", ""),
            "mCurrentFocus": (0, "mCurrentFocus=Window{a u0 com.example/com.example.Main}", ""),
        }
    )
    outcome = AppLauncher(adb).launch("com.example", "com.example.Main")
    assert outcome.method == "monkey"
    assert "monkey" in runner.commands()
    assert any("retrying with monkey" in w for w in outcome.warnings)


def test_launch_raises_activity_not_found():
    adb, _ = make_adb(
        {
            "resolve-activity": (0, "", ""),
            "dumpsys package": (0, "", ""),
            "pm dump": (0, "", ""),
            "monkey": (0, "** No activities found to run", ""),
        }
    )
    with pytest.raises(ActivityNotFoundError):
        AppLauncher(adb).launch("com.example")


def test_current_component_parses_focus():
    adb, _ = make_adb(
        {"mCurrentFocus": (0, "mCurrentFocus=Window{ab u0 com.example/com.example.Main}", "")}
    )
    assert AppLauncher(adb).current_component() == "com.example/com.example.Main"


def test_force_stop_does_not_raise_on_failure():
    adb, _ = make_adb({"force-stop": (1, "", "boom")})
    assert AppLauncher(adb).force_stop("com.example").ok is False


# --- Launch target resolution ------------------------------------------------


LAUNCHER_ACTIVITIES = [
    {
        "name": "com.example.Splash",
        "enabled": True,
        "intent_filters": [{"actions": ["android.intent.action.VIEW"], "categories": []}],
    },
    {
        "name": "com.example.MainActivity",
        "enabled": True,
        "intent_filters": [
            {
                "actions": ["android.intent.action.MAIN"],
                "categories": ["android.intent.category.LAUNCHER"],
            }
        ],
    },
]


def test_launcher_activity_picks_main_launcher():
    assert launcher_activity(LAUNCHER_ACTIVITIES) == "com.example.MainActivity"


def test_launcher_activity_returns_none_without_candidates():
    assert launcher_activity([{"name": "com.example.A", "intent_filters": []}]) is None


def test_launcher_activity_falls_back_to_main_without_launcher_category():
    activities = [
        {
            "name": "com.example.Main",
            "intent_filters": [{"actions": ["android.intent.action.MAIN"], "categories": []}],
        }
    ]
    assert launcher_activity(activities) == "com.example.Main"


def test_target_from_analysis_uses_existing_extraction():
    payload = {
        "data": {
            "apk": {"package_name": "com.example"},
            "manifest": {"package": "com.example"},
            "activities": LAUNCHER_ACTIVITIES,
        }
    }
    target = target_from_analysis(payload)
    assert target is not None
    assert target.package_name == "com.example"
    assert target.activity == "com.example.MainActivity"
    assert target.source == "static_analysis"
    assert target.is_complete is True


def test_target_from_analysis_marks_partial_without_activity():
    payload = {"data": {"apk": {"package_name": "com.example"}, "activities": []}}
    target = target_from_analysis(payload)
    assert target is not None
    assert target.activity is None
    assert target.source == "static_analysis_partial"


def test_target_from_analysis_returns_none_without_package():
    assert target_from_analysis({"data": {"apk": {}, "manifest": {}}}) is None
