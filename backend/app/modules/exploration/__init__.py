"""Dynamic analysis: run the APK on an Android emulator and capture UI state.

Distinct from ``app.modules.screenshots``, which extracts static image assets from
the APK archive. Nothing here requires Android Studio; the device is driven purely
through adb and UIAutomator.
"""

from app.modules.exploration.adb import (
    AdbDevice,
    adb_available,
    capability_report,
    describe_device,
    find_adb,
    is_booted,
    list_devices,
    pick_device,
    run_adb,
    shell,
)

__all__ = [
    "AdbDevice",
    "adb_available",
    "capability_report",
    "describe_device",
    "find_adb",
    "is_booted",
    "list_devices",
    "pick_device",
    "run_adb",
    "shell",
]
