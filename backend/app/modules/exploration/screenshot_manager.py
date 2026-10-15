"""Screenshot capture from a running Android device (Phase 3).

Uses ``adb exec-out screencap -p``. Local files land under::

    TEMP_ROOT/screenshots/{package}/{job_id}/

Phase 8 publishes them to S3 (and capture can upload immediately when S3 is configured).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from app.core.config import settings
from app.modules.exploration.adb import AndroidADB
from app.modules.exploration.errors import ScreenshotCaptureError, ScreenshotDecodeError
from app.modules.exploration.image_hasher import ImageHasher, content_sha256
from app.modules.exploration.launcher import AppLauncher

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(ts: datetime) -> str:
    return ts.isoformat()


@dataclass
class CapturedScreenshot:
    """One framebuffer capture with the Phase 3 metadata contract."""

    state_id: str
    local_path: str
    width: int
    height: int
    image_hash: str
    timestamp: str
    activity: str | None = None
    trigger_action: str | None = None
    sha256: str = ""
    byte_size: int = 0
    ahash: str = ""
    dhash: str = ""
    package_name: str | None = None
    s3_key: str | None = None
    s3_url: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload


class ScreenshotManager:
    """Capture, hash and persist device screenshots locally (+ optional S3)."""

    def __init__(
        self,
        adb: AndroidADB,
        *,
        output_dir: str | Path | None = None,
        hasher: ImageHasher | None = None,
        package_name: str | None = None,
        job_id: str | None = None,
        upload_to_s3: bool | None = None,
    ) -> None:
        from app.modules.exploration.screenshot_storage import local_screenshots_dir

        self.adb = adb
        self.hasher = hasher or ImageHasher()
        self.package_name = package_name
        self.job_id = (job_id or "").strip() or "adhoc"
        if output_dir is not None:
            root = Path(output_dir)
        else:
            root = local_screenshots_dir(package_name, self.job_id)
        self.output_dir = root
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.upload_to_s3 = (
            bool(settings.s3_enabled) if upload_to_s3 is None else bool(upload_to_s3)
        )
        self._storage = None
        if self.upload_to_s3:
            try:
                from app.modules.exploration.screenshot_storage import ScreenshotStorage

                self._storage = ScreenshotStorage(
                    app_id=package_name or self.job_id,
                    run_id=self.job_id,
                    enabled=True,
                )
            except Exception:
                logger.warning("Could not init ScreenshotStorage for live upload", exc_info=True)
                self._storage = None

    def capture(
        self,
        *,
        state_id: str | None = None,
        trigger_action: str | None = None,
        activity: str | None = None,
        package_name: str | None = None,
        resolve_activity: bool = True,
    ) -> CapturedScreenshot:
        """Grab a PNG screenshot and write it under ``output_dir``."""
        try:
            png = self.adb.screencap_png()
        except Exception as exc:
            raise ScreenshotCaptureError(f"screencap failed: {exc}") from exc

        if len(png) < 32 or not png.startswith(b"\x89PNG"):
            raise ScreenshotCaptureError(
                "screencap returned data that is not a valid PNG "
                "(common on Windows if CRLF repair failed)."
            )

        resolved_activity = activity
        if resolve_activity and not resolved_activity:
            try:
                resolved_activity = AppLauncher(self.adb).current_component()
            except Exception:
                logger.debug("Could not resolve current activity", exc_info=True)

        try:
            with Image.open(BytesIO(png)) as image:
                width, height = image.size
        except Exception as exc:
            raise ScreenshotDecodeError(f"PNG decode failed after capture: {exc}") from exc

        digest = content_sha256(png)
        perceptual = self.hasher.hash_bytes(png)
        sid = state_id or f"shot-{uuid.uuid4().hex[:12]}"
        stamp = _utcnow()
        file_name = f"{sid}_{stamp.strftime('%Y%m%dT%H%M%S')}.png"
        path = self.output_dir / file_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png)

        pkg = package_name or self.package_name or (
            resolved_activity.split("/", 1)[0] if resolved_activity else None
        )
        shot = CapturedScreenshot(
            state_id=sid,
            local_path=str(path.resolve()),
            width=width,
            height=height,
            image_hash=perceptual.hex,
            timestamp=_iso(stamp),
            activity=resolved_activity,
            trigger_action=trigger_action,
            sha256=digest,
            byte_size=len(png),
            ahash=perceptual.ahash,
            dhash=perceptual.dhash,
            package_name=pkg,
            extras={"algorithm": perceptual.algorithm, "hash_size": perceptual.hash_size},
        )

        if self._storage is not None:
            try:
                from app.modules.exploration.screenshot_storage import page_from_activity

                meta = self._storage.upload_file(
                    path,
                    page=page_from_activity(resolved_activity),
                    state_id=sid,
                    triggering_action=trigger_action,
                    width=width,
                    height=height,
                    kind="state",
                    screenshot_id=sid,
                    created_at=shot.timestamp,
                )
                shot.s3_key = meta.s3_key
                shot.s3_url = meta.s3_url
                if meta.upload_error:
                    shot.extras["upload_error"] = meta.upload_error
                    logger.warning(
                        "Screenshot %s S3 upload deferred: %s",
                        sid,
                        meta.upload_error,
                    )
                else:
                    logger.info("Screenshot %s uploaded to S3 key=%s", sid, meta.s3_key)
            except Exception as exc:
                shot.extras["upload_error"] = f"{type(exc).__name__}: {exc}"
                logger.warning("Screenshot %s live S3 upload failed: %s", sid, type(exc).__name__)

        logger.info(
            "Screenshot %s saved (%sx%s, %s bytes) path=%s activity=%s trigger=%s s3=%s",
            sid,
            width,
            height,
            shot.byte_size,
            path,
            shot.activity,
            trigger_action,
            bool(shot.s3_key),
        )
        return shot

    def hash_file(self, path: str | Path) -> CapturedScreenshot:
        """Build screenshot metadata from an existing local PNG (no device)."""
        path = Path(path)
        data = path.read_bytes()
        perceptual = self.hasher.hash_bytes(data)
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
        sid = f"file-{path.stem[:24]}"
        return CapturedScreenshot(
            state_id=sid,
            local_path=str(path.resolve()),
            width=width,
            height=height,
            image_hash=perceptual.hex,
            timestamp=_iso(_utcnow()),
            sha256=content_sha256(data),
            byte_size=len(data),
            ahash=perceptual.ahash,
            dhash=perceptual.dhash,
            extras={"algorithm": perceptual.algorithm, "source": "local_file"},
        )
