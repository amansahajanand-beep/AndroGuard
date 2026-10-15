"""Phase 12I — Android device session context for one job.

One active job owns one ADB serial / emulator session. UIController and
exploration operate against this context; they do not schedule workers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class AndroidDeviceSession:
    """Isolated device context for a single analysis job attempt."""

    job_id: str
    worker_id: str
    device_id: str
    adb_serial: str
    emulator_id: str | None = None
    package_name: str | None = None
    avd_name: str | None = None
    created_at: datetime = field(default_factory=_utcnow)
    temp_dir: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "worker_id": self.worker_id,
            "device_id": self.device_id,
            "adb_serial": self.adb_serial,
            "emulator_id": self.emulator_id,
            "package_name": self.package_name,
            "avd_name": self.avd_name,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "temp_dir": self.temp_dir,
        }
