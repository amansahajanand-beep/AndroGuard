"""UI hierarchy via uiautomator2, used before the plain ``uiautomator dump``.

``adb shell uiautomator dump`` waits for the app to go idle and fails with
"could not get idle state" on screens with constant animation (ads, Lottie,
video). The explorer then sees an empty screen and looks stuck. uiautomator2's
``dump_hierarchy`` does not wait for idle, so it keeps working there.

The output is normalised to the classic ``<node .../>`` format so the existing
parser is unchanged. Any failure raises, and the caller falls back to the adb dump.
After ``max_failures`` consecutive failures the dumper turns itself off so a
broken setup does not add delay to every step.
"""

from __future__ import annotations

import logging
import os
import xml.etree.ElementTree as ET
from typing import Any, Callable

logger = logging.getLogger(__name__)


class U2Unavailable(RuntimeError):
    pass


def normalize_u2_xml(xml_text: str) -> str:
    """Rewrite uiautomator2 XML (class name as tag) into ``<hierarchy><node/></hierarchy>``."""
    root = ET.fromstring((xml_text or "").strip())
    for element in root.iter():
        if element is root:
            continue
        if element.tag != "node":
            element.attrib.setdefault("class", element.tag)
            element.tag = "node"
    if root.tag != "hierarchy":
        root.tag = "hierarchy"
    return ET.tostring(root, encoding="unicode")


class U2Dumper:
    def __init__(
        self,
        serial: str | None,
        *,
        adb_binary: str | None = None,
        connect: Callable[[str | None], Any] | None = None,
        max_failures: int = 3,
    ) -> None:
        self.serial = serial
        self.adb_binary = adb_binary
        self._connect = connect
        self._device: Any = None
        self._failures = 0
        self.max_failures = max_failures
        self.disabled = False

    def _device_handle(self) -> Any:
        if self._device is not None:
            return self._device
        if self._connect is not None:
            self._device = self._connect(self.serial)
            return self._device
        try:
            if self.adb_binary:
                # Make adbutils use the same adb as the rest of the explorer (avoids server restarts).
                os.environ.setdefault("ADBUTILS_ADB_PATH", self.adb_binary)
            import uiautomator2
        except ImportError as exc:
            raise U2Unavailable("uiautomator2 is not installed") from exc
        self._device = uiautomator2.connect(self.serial) if self.serial else uiautomator2.connect()
        return self._device

    def dump_xml(self) -> str:
        """Return the hierarchy as classic uiautomator XML. Raises on any failure."""
        if self.disabled:
            raise U2Unavailable("uiautomator2 dumper disabled after repeated failures")
        try:
            raw = self._device_handle().dump_hierarchy(compressed=False, pretty=False)
            xml = normalize_u2_xml(raw)
        except Exception as exc:  # noqa: BLE001 - any failure means "use the adb dump instead"
            self._device = None
            self._failures += 1
            if self._failures >= self.max_failures:
                self.disabled = True
                logger.warning(
                    "uiautomator2 failed %s times in a row (%s); using adb uiautomator dump only.",
                    self._failures,
                    type(exc).__name__,
                )
            raise
        self._failures = 0
        return xml
