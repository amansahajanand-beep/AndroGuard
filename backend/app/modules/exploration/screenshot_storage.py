"""Phase 8: exploration / HITL screenshot metadata + S3 publication.

Reuses :mod:`app.storage.s3` (same client, bucket, credentials). Key layout::

    {S3_PREFIX}/{app_id}/runs/{run_id}/{page}/state_001.png
    {S3_PREFIX}/{app_id}/runs/{run_id}/hitl/hitl_001.png

Upload failures are recorded on metadata and never crash the analysis job.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from app.core.config import settings
from app.storage import s3 as s3_store

logger = logging.getLogger(__name__)

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def sanitize_segment(value: str | None, *, fallback: str = "unknown") -> str:
    text = (value or "").strip()
    if not text:
        return fallback
    # Activity component → short class name.
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    if "." in text and text.count(".") >= 1 and not text.startswith("com."):
        # Keep package-like app ids; strip nested class prefixes for pages.
        pass
    text = text.replace("\\", "/").rstrip("/")
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    cleaned = _SAFE.sub("_", text).strip("._-")
    return cleaned[:120] or fallback


def page_from_activity(activity: str | None, *, label: str | None = None) -> str:
    if label and label.strip() and label.lower() not in {"entry", "after_human"}:
        return sanitize_segment(label, fallback="page")
    if not activity:
        return "unknown"
    short = activity.rsplit("/", 1)[-1] if "/" in activity else activity
    short = short.rsplit(".", 1)[-1]
    return sanitize_segment(short, fallback="page")


def app_id_from_package(package_name: str | None, *, job_id: str | None = None) -> str:
    if package_name:
        return sanitize_segment(package_name, fallback="app")
    if job_id:
        return sanitize_segment(job_id, fallback="app")
    return "app"


def local_screenshots_dir(
    package_name: str | None,
    job_id: str | None,
    *,
    ensure: bool = True,
) -> Path:
    """Local layout: ``TEMP_ROOT/screenshots/{package}/{job_id}/``."""
    app = app_id_from_package(package_name, job_id=job_id)
    run = sanitize_segment(job_id, fallback="adhoc")
    path = Path(settings.temp_root) / "screenshots" / app / run
    if ensure:
        path.mkdir(parents=True, exist_ok=True)
    return path


def local_hitl_dir(
    package_name: str | None,
    job_id: str | None,
    *,
    ensure: bool = True,
) -> Path:
    """Local HITL layout: ``TEMP_ROOT/screenshots/{package}/{job_id}/hitl/``."""
    path = local_screenshots_dir(package_name, job_id, ensure=ensure) / "hitl"
    if ensure:
        path.mkdir(parents=True, exist_ok=True)
    return path


def exploration_state_key(
    *,
    app_id: str,
    run_id: str,
    page: str,
    state_index: int,
    prefix: str | None = None,
) -> str:
    root = (prefix if prefix is not None else settings.s3_prefix).strip("/")
    return (
        f"{root}/{sanitize_segment(app_id)}/runs/{sanitize_segment(run_id)}/"
        f"{sanitize_segment(page, fallback='page')}/state_{state_index:03d}.png"
    )


def hitl_screenshot_key(
    *,
    app_id: str,
    run_id: str,
    hitl_index: int,
    prefix: str | None = None,
) -> str:
    root = (prefix if prefix is not None else settings.s3_prefix).strip("/")
    return (
        f"{root}/{sanitize_segment(app_id)}/runs/{sanitize_segment(run_id)}/"
        f"hitl/hitl_{hitl_index:03d}.png"
    )


@dataclass
class ScreenshotMetadata:
    """Stored metadata for one exploration / HITL screenshot (no base64)."""

    screenshot_id: str
    run_id: str
    page: str
    state_id: str
    local_path: str | None = None
    s3_key: str | None = None
    s3_url: str | None = None
    width: int | None = None
    height: int | None = None
    triggering_action: str | None = None
    ad_detected: bool = False
    ad_type: str | None = None
    ad_position: str | None = None
    confidence: float | None = None
    created_at: str = field(default_factory=lambda: _utcnow().isoformat())
    app_id: str | None = None
    upload_error: str | None = None
    kind: str = "state"  # state | hitl
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def public_dict(self) -> dict[str, Any]:
        """API-safe payload: metadata + URLs only (never image bytes)."""
        return {
            "screenshot_id": self.screenshot_id,
            "run_id": self.run_id,
            "page": self.page,
            "state_id": self.state_id,
            "local_path": self.local_path,
            "s3_key": self.s3_key,
            "s3_url": self.s3_url,
            "width": self.width,
            "height": self.height,
            "triggering_action": self.triggering_action,
            "ad_detected": self.ad_detected,
            "ad_type": self.ad_type,
            "ad_position": self.ad_position,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "upload_error": self.upload_error,
            "kind": self.kind,
        }


@dataclass
class ScreenshotPublishResult:
    uploaded: int = 0
    failed: int = 0
    skipped: int = 0
    metadata: list[ScreenshotMetadata] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "uploaded": self.uploaded,
            "failed": self.failed,
            "skipped": self.skipped,
            "metadata": [item.public_dict() for item in self.metadata],
            "warnings": list(self.warnings),
        }


class ScreenshotStorage:
    """Publish local screenshots to S3 using the shared storage client."""

    def __init__(
        self,
        *,
        app_id: str,
        run_id: str,
        enabled: bool | None = None,
    ) -> None:
        self.app_id = app_id_from_package(app_id, job_id=run_id)
        self.run_id = sanitize_segment(run_id, fallback="run")
        self.enabled = settings.s3_enabled if enabled is None else bool(enabled)
        self._page_counters: dict[str, int] = defaultdict(int)
        self._hitl_counter = 0
        self.records: list[ScreenshotMetadata] = []

    def next_state_key(self, page: str) -> tuple[str, int]:
        self._page_counters[page] += 1
        index = self._page_counters[page]
        return (
            exploration_state_key(
                app_id=self.app_id, run_id=self.run_id, page=page, state_index=index
            ),
            index,
        )

    def next_hitl_key(self) -> tuple[str, int]:
        self._hitl_counter += 1
        index = self._hitl_counter
        return (
            hitl_screenshot_key(app_id=self.app_id, run_id=self.run_id, hitl_index=index),
            index,
        )

    def upload_file(
        self,
        local_path: str | Path,
        *,
        page: str,
        state_id: str,
        triggering_action: str | None = None,
        width: int | None = None,
        height: int | None = None,
        ad_detected: bool = False,
        ad_type: str | None = None,
        ad_position: str | None = None,
        confidence: float | None = None,
        kind: str = "state",
        screenshot_id: str | None = None,
        created_at: str | None = None,
    ) -> ScreenshotMetadata:
        path = Path(local_path)
        page_slug = sanitize_segment(page, fallback="page")
        meta = ScreenshotMetadata(
            screenshot_id=screenshot_id or f"ss_{uuid.uuid4().hex[:12]}",
            run_id=self.run_id,
            page=page_slug,
            state_id=state_id,
            local_path=str(path.resolve()) if path.exists() else str(path),
            width=width,
            height=height,
            triggering_action=triggering_action,
            ad_detected=ad_detected,
            ad_type=ad_type,
            ad_position=ad_position,
            confidence=confidence,
            created_at=created_at or _utcnow().isoformat(),
            app_id=self.app_id,
            kind=kind,
        )

        if not path.is_file():
            meta.upload_error = f"Local screenshot missing: {path}"
            self.records.append(meta)
            return meta

        if not self.enabled:
            meta.upload_error = "S3 is not configured; kept local only."
            self.records.append(meta)
            return meta

        try:
            data = path.read_bytes()
            if kind == "hitl":
                key, _index = self.next_hitl_key()
            else:
                key, _index = self.next_state_key(page_slug)
            s3_key, s3_url = s3_store.upload_object_bytes(key, data, content_type="image/png")
            meta.s3_key = s3_key
            meta.s3_url = s3_url
            if settings.s3_cleanup_local_after_upload:
                try:
                    path.unlink(missing_ok=True)
                    meta.extras["local_cleaned"] = True
                except Exception:
                    logger.warning("Could not clean local screenshot %s", path, exc_info=True)
        except Exception as exc:
            meta.upload_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "Screenshot upload failed screenshot_id=%s state_id=%s err=%s",
                meta.screenshot_id,
                state_id,
                type(exc).__name__,
            )
        self.records.append(meta)
        return meta

    def upload_bytes(
        self,
        data: bytes,
        *,
        page: str = "hitl",
        state_id: str,
        kind: str = "hitl",
        triggering_action: str | None = None,
        width: int | None = None,
        height: int | None = None,
        local_path: str | None = None,
        screenshot_id: str | None = None,
    ) -> ScreenshotMetadata:
        meta = ScreenshotMetadata(
            screenshot_id=screenshot_id or f"ss_{uuid.uuid4().hex[:12]}",
            run_id=self.run_id,
            page=sanitize_segment(page, fallback="hitl"),
            state_id=state_id,
            local_path=local_path,
            width=width,
            height=height,
            triggering_action=triggering_action,
            created_at=_utcnow().isoformat(),
            app_id=self.app_id,
            kind=kind,
        )
        if not self.enabled:
            meta.upload_error = "S3 is not configured; kept local only."
            self.records.append(meta)
            return meta
        try:
            if kind == "hitl":
                key, _ = self.next_hitl_key()
            else:
                key, _ = self.next_state_key(meta.page)
            s3_key, s3_url = s3_store.upload_object_bytes(key, data, content_type="image/png")
            meta.s3_key = s3_key
            meta.s3_url = s3_url
        except Exception as exc:
            meta.upload_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "HITL screenshot upload failed screenshot_id=%s err=%s",
                meta.screenshot_id,
                type(exc).__name__,
            )
        self.records.append(meta)
        return meta


def _ad_fields_from_record(record: Any) -> tuple[bool, str | None, str | None, float | None]:
    ad = getattr(record, "ad_placement", None)
    if ad is None:
        return False, None, None, None
    slot_count = int(getattr(ad, "slot_count", 0) or 0)
    regions = list(getattr(ad, "candidate_regions", ()) or ())
    ad_type = None
    ad_position = None
    confidence = None
    if regions:
        first = regions[0] if isinstance(regions[0], dict) else {}
        ad_type = first.get("ad_type") or first.get("type")
        ad_position = first.get("position")
        conf = first.get("confidence")
        if isinstance(conf, (int, float)):
            confidence = float(conf)
    return slot_count > 0 or bool(regions), ad_type, ad_position, confidence


def publish_exploration_screenshots(
    *,
    run_id: str,
    package_name: str | None,
    states: Sequence[Any],
    storage: ScreenshotStorage | None = None,
) -> ScreenshotPublishResult:
    """Upload explorer state screenshots. Never raises for per-file failures."""
    result = ScreenshotPublishResult()
    store = storage or ScreenshotStorage(
        app_id=package_name or run_id,
        run_id=run_id,
    )
    if not store.enabled:
        result.skipped = len(states)
        result.warnings.append(
            "S3 is not configured (set S3_BUCKET + S3_ACCESS_KEY + S3_SECRET_KEY); "
            "exploration screenshots kept locally under "
            f"screenshots/{store.app_id}/{store.run_id}/."
        )
        for record in states:
            shot = getattr(record, "screenshot", None)
            if shot is None:
                continue
            page = page_from_activity(
                getattr(getattr(record, "visual", None), "activity", None)
                or getattr(shot, "activity", None),
                label=getattr(record, "label", None),
            )
            ad_detected, ad_type, ad_pos, conf = _ad_fields_from_record(record)
            meta = ScreenshotMetadata(
                screenshot_id=f"ss_{uuid.uuid4().hex[:12]}",
                run_id=store.run_id,
                page=page,
                state_id=getattr(record, "state_id", "") or getattr(shot, "state_id", ""),
                local_path=getattr(shot, "local_path", None),
                s3_key=getattr(shot, "s3_key", None),
                s3_url=getattr(shot, "s3_url", None),
                width=getattr(shot, "width", None),
                height=getattr(shot, "height", None),
                triggering_action=getattr(record, "trigger_action", None)
                or getattr(shot, "trigger_action", None),
                ad_detected=ad_detected,
                ad_type=ad_type,
                ad_position=ad_pos,
                confidence=conf,
                created_at=getattr(shot, "timestamp", None) or _utcnow().isoformat(),
                app_id=store.app_id,
                upload_error=None if getattr(shot, "s3_key", None) else "S3 is not configured; kept local only.",
            )
            result.metadata.append(meta)
            store.records.append(meta)
            if meta.s3_key:
                result.uploaded += 1
        return result

    # Readiness is advisory — still attempt put_object (head_bucket often flakes).
    try:
        if not s3_store.s3_ready():
            result.warnings.append(
                "S3 bucket head check failed; still attempting screenshot uploads."
            )
    except Exception as exc:
        result.warnings.append(
            f"S3 readiness check failed ({type(exc).__name__}); still attempting uploads."
        )

    for record in states:
        shot = getattr(record, "screenshot", None)
        if shot is None:
            continue
        local_path = getattr(shot, "local_path", None)
        if not local_path:
            result.failed += 1
            continue
        page = page_from_activity(
            getattr(getattr(record, "visual", None), "activity", None)
            or getattr(shot, "activity", None),
            label=getattr(record, "label", None),
        )
        ad_detected, ad_type, ad_pos, conf = _ad_fields_from_record(record)
        # Prefer already-uploaded key from live capture; refresh if missing.
        existing_key = getattr(shot, "s3_key", None)
        if existing_key:
            meta = ScreenshotMetadata(
                screenshot_id=getattr(shot, "state_id", None) or f"ss_{uuid.uuid4().hex[:12]}",
                run_id=store.run_id,
                page=page,
                state_id=getattr(record, "state_id", "") or getattr(shot, "state_id", ""),
                local_path=local_path,
                s3_key=existing_key,
                s3_url=getattr(shot, "s3_url", None),
                width=getattr(shot, "width", None),
                height=getattr(shot, "height", None),
                triggering_action=getattr(record, "trigger_action", None)
                or getattr(shot, "trigger_action", None),
                ad_detected=ad_detected,
                ad_type=ad_type,
                ad_position=ad_pos,
                confidence=conf,
                created_at=getattr(shot, "timestamp", None) or _utcnow().isoformat(),
                app_id=store.app_id,
                kind="state",
            )
            result.metadata.append(meta)
            store.records.append(meta)
            result.uploaded += 1
            continue

        meta = store.upload_file(
            local_path,
            page=page,
            state_id=getattr(record, "state_id", "") or getattr(shot, "state_id", ""),
            triggering_action=getattr(record, "trigger_action", None)
            or getattr(shot, "trigger_action", None),
            width=getattr(shot, "width", None),
            height=getattr(shot, "height", None),
            ad_detected=ad_detected,
            ad_type=ad_type,
            ad_position=ad_pos,
            confidence=conf,
            kind="state",
            created_at=getattr(shot, "timestamp", None),
        )
        result.metadata.append(meta)
        if meta.s3_key and not meta.upload_error:
            result.uploaded += 1
            # Reflect back onto the in-memory shot for Phase 11 / APIs.
            try:
                shot.s3_key = meta.s3_key
                shot.s3_url = meta.s3_url
            except Exception:
                pass
        else:
            result.failed += 1
            if meta.upload_error:
                result.warnings.append(
                    f"Screenshot {meta.state_id} upload failed: {meta.upload_error}"
                )

    if result.failed and result.uploaded:
        result.warnings.append(
            f"Partial S3 upload: {result.uploaded} ok, {result.failed} failed."
        )
    elif result.failed and not result.uploaded:
        result.warnings.append("All exploration screenshot uploads failed; local files retained.")
    elif result.uploaded:
        logger.info(
            "Published %s exploration screenshots to S3 for run %s",
            result.uploaded,
            run_id,
        )
    return result


def apply_metadata_to_exploration_result(exploration: Any, publish: ScreenshotPublishResult) -> None:
    """Attach s3_key/url + screenshot metadata onto ExplorationResult (no base64)."""
    if exploration is None:
        return
    by_state = {m.state_id: m for m in publish.metadata}
    uploaded = 0
    for info in getattr(exploration, "screenshots", []) or []:
        meta = by_state.get(getattr(info, "state_id", None) or "")
        if meta is None:
            continue
        info.s3_key = meta.s3_key
        info.url = meta.s3_url
        info.screenshot_id = meta.screenshot_id
        info.page = meta.page
        info.triggering_action = meta.triggering_action
        info.ad_detected = meta.ad_detected
        info.ad_type = meta.ad_type
        info.ad_position = meta.ad_position
        info.confidence = meta.confidence
        info.upload_error = meta.upload_error
        if meta.s3_key:
            uploaded += 1
    for state in getattr(exploration, "states", []) or []:
        shot = getattr(state, "screenshot", None)
        if shot is None:
            continue
        meta = by_state.get(
            getattr(state, "state_id", None) or getattr(shot, "state_id", "") or ""
        )
        if meta is None:
            continue
        shot.s3_key = meta.s3_key
        shot.url = meta.s3_url
        shot.screenshot_id = meta.screenshot_id
        shot.page = meta.page
        shot.triggering_action = meta.triggering_action
        shot.ad_detected = meta.ad_detected
        shot.ad_type = meta.ad_type
        shot.ad_position = meta.ad_position
        shot.confidence = meta.confidence
        shot.upload_error = meta.upload_error
    summary = getattr(exploration, "summary", None)
    if summary is not None and hasattr(summary, "screenshots_uploaded"):
        summary.screenshots_uploaded = uploaded
    warnings = list(getattr(exploration, "warnings", None) or [])
    for warning in publish.warnings:
        if warning not in warnings:
            warnings.append(warning)
    exploration.warnings = warnings
    if hasattr(exploration, "screenshot_records"):
        exploration.screenshot_records = [m.public_dict() for m in publish.metadata]
