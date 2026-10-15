"""Phase 11 persistence helpers for screenshot runs, screenshots, and HITL."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import select

from app.db.models import HumanIntervention, Screenshot, ScreenshotRun
from app.db.session import SessionLocal, engine

logger = logging.getLogger(__name__)

# Public DB statuses for human_interventions (Phase 11 contract).
HITL_DB_STATUSES = frozenset({"waiting", "continued", "skipped", "stopped", "timeout"})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _db_ready() -> bool:
    return engine is not None and SessionLocal is not None


def map_hitl_status_to_db(status: Any, *, decision: Any = None) -> str:
    """Map in-memory HITL enums/strings onto Phase 11 DB statuses."""
    raw = getattr(status, "value", status)
    text = str(raw or "").strip().lower()
    if text in {"resolved", "continue", "continued"}:
        return "continued"
    if text in HITL_DB_STATUSES:
        return text
    decision_raw = getattr(decision, "value", decision)
    decision_text = str(decision_raw or "").strip().lower()
    if decision_text == "continue":
        return "continued"
    if decision_text in {"skip", "skipped"}:
        return "skipped"
    if decision_text in {"stop", "stopped"}:
        return "stopped"
    if decision_text == "timeout":
        return "timeout"
    return "waiting"


def start_screenshot_run(
    *,
    run_id: str,
    app_id: str,
    job_id: str,
    status: str = "running",
) -> ScreenshotRun | None:
    """Create or refresh a screenshot run row. No-op when DB is unavailable."""
    if not _db_ready():
        return None
    assert SessionLocal is not None
    session = SessionLocal()
    try:
        row = session.get(ScreenshotRun, run_id)
        if row is None:
            row = ScreenshotRun(
                run_id=run_id,
                app_id=app_id,
                job_id=job_id,
                status=status,
                started_at=_utcnow(),
            )
            session.add(row)
        else:
            row.app_id = app_id
            row.job_id = job_id
            if row.status in {"failed", "completed"} and status == "running":
                row.status = "running"
                row.completed_at = None
        session.commit()
        session.refresh(row)
        return row
    except Exception:
        session.rollback()
        logger.exception("Failed to start screenshot_run %s", run_id)
        return None
    finally:
        session.close()


def complete_screenshot_run(
    *,
    run_id: str,
    status: str = "completed",
    total_screenshots: int = 0,
    total_pages: int = 0,
    total_ad_variations: int = 0,
) -> ScreenshotRun | None:
    if not _db_ready():
        return None
    assert SessionLocal is not None
    session = SessionLocal()
    try:
        row = session.get(ScreenshotRun, run_id)
        if row is None:
            logger.warning("complete_screenshot_run: missing run %s", run_id)
            return None
        row.status = status
        row.completed_at = _utcnow()
        row.total_screenshots = int(total_screenshots)
        row.total_pages = int(total_pages)
        row.total_ad_variations = int(total_ad_variations)
        session.commit()
        session.refresh(row)
        return row
    except Exception:
        session.rollback()
        logger.exception("Failed to complete screenshot_run %s", run_id)
        return None
    finally:
        session.close()


def _parse_created_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return _utcnow()


def persist_screenshots_for_run(
    *,
    run_id: str,
    items: Sequence[Any],
) -> int:
    """Upsert Phase 11 ``screenshots`` rows from ScreenshotMetadata-like objects."""
    if not _db_ready() or not items:
        return 0
    assert SessionLocal is not None
    session = SessionLocal()
    saved = 0
    try:
        if session.get(ScreenshotRun, run_id) is None:
            logger.warning("persist_screenshots_for_run: missing run %s", run_id)
            return 0
        for item in items:
            if isinstance(item, dict):
                data = item
            else:
                data = {
                    "id": getattr(item, "screenshot_id", None),
                    "page": getattr(item, "page", "unknown"),
                    "state_id": getattr(item, "state_id", None),
                    "s3_key": getattr(item, "s3_key", None),
                    "width": getattr(item, "width", None),
                    "height": getattr(item, "height", None),
                    "trigger_action": getattr(item, "triggering_action", None)
                    or getattr(item, "trigger_action", None),
                    "ad_detected": bool(getattr(item, "ad_detected", False)),
                    "ad_type": getattr(item, "ad_type", None),
                    "ad_position": getattr(item, "ad_position", None),
                    "confidence": getattr(item, "confidence", None),
                    "created_at": getattr(item, "created_at", None),
                    "kind": getattr(item, "kind", "state"),
                }
            if str(data.get("kind") or "state") == "hitl":
                continue
            state_id = str(data.get("state_id") or "").strip()
            if not state_id:
                continue
            shot_id = str(data.get("id") or data.get("screenshot_id") or "").strip()
            if not shot_id:
                shot_id = f"{run_id}:{state_id}"[:64]

            existing = session.get(Screenshot, shot_id)
            if existing is None:
                stmt = select(Screenshot).where(
                    Screenshot.run_id == run_id,
                    Screenshot.state_id == state_id,
                )
                existing = session.scalars(stmt).first()

            payload = {
                "run_id": run_id,
                "page": str(data.get("page") or "unknown")[:256],
                "state_id": state_id[:128],
                "s3_key": data.get("s3_key"),
                "width": data.get("width"),
                "height": data.get("height"),
                "trigger_action": (str(data["trigger_action"])[:128] if data.get("trigger_action") else None),
                "ad_detected": bool(data.get("ad_detected")),
                "ad_type": (str(data["ad_type"])[:64] if data.get("ad_type") else None),
                "ad_position": (
                    str(data["ad_position"])[:64] if data.get("ad_position") else None
                ),
                "confidence": (
                    float(data["confidence"])
                    if isinstance(data.get("confidence"), (int, float))
                    else None
                ),
                "created_at": _parse_created_at(data.get("created_at")),
            }
            if existing is None:
                session.add(Screenshot(id=shot_id[:64], **payload))
            else:
                for key, value in payload.items():
                    setattr(existing, key, value)
            saved += 1
        session.commit()
        return saved
    except Exception:
        session.rollback()
        logger.exception("Failed to persist screenshots for run %s", run_id)
        return 0
    finally:
        session.close()


def upsert_human_intervention(
    *,
    intervention_id: str,
    job_id: str,
    run_id: str | None,
    type: str,
    title: str,
    message: str,
    screenshot_s3_key: str | None = None,
    status: str = "waiting",
    created_at: datetime | None = None,
    resolved_at: datetime | None = None,
    resolution: str | None = None,
    timeout_at: datetime | None = None,
    decision: Any = None,
) -> HumanIntervention | None:
    if not _db_ready():
        return None
    assert SessionLocal is not None
    db_status = map_hitl_status_to_db(status, decision=decision)
    session = SessionLocal()
    try:
        # Avoid FK failure if the run row is missing (best-effort soft link).
        linked_run = run_id
        if linked_run and session.get(ScreenshotRun, linked_run) is None:
            linked_run = None

        row = session.get(HumanIntervention, intervention_id)
        if row is None:
            row = HumanIntervention(
                intervention_id=intervention_id,
                job_id=job_id,
                run_id=linked_run,
                type=str(type)[:64],
                title=(title or "Human action required")[:256],
                message=message or "",
                screenshot_s3_key=screenshot_s3_key,
                status=db_status,
                created_at=created_at or _utcnow(),
                resolved_at=resolved_at,
                resolution=resolution,
                timeout_at=timeout_at,
            )
            session.add(row)
        else:
            row.job_id = job_id
            row.run_id = linked_run
            row.type = str(type)[:64]
            row.title = (title or row.title)[:256]
            row.message = message if message is not None else row.message
            if screenshot_s3_key is not None:
                row.screenshot_s3_key = screenshot_s3_key
            row.status = db_status
            if resolved_at is not None:
                row.resolved_at = resolved_at
            if resolution is not None:
                row.resolution = resolution
            if timeout_at is not None:
                row.timeout_at = timeout_at
        session.commit()
        session.refresh(row)
        return row
    except Exception:
        session.rollback()
        logger.exception("Failed to upsert human_intervention %s", intervention_id)
        return None
    finally:
        session.close()


def persist_intervention_from_dataclass(intervention: Any) -> HumanIntervention | None:
    """Persist an in-memory HITL Intervention dataclass."""
    decision = getattr(intervention, "decision", None)
    status = getattr(intervention, "status", "waiting")
    db_status = map_hitl_status_to_db(status, decision=decision)
    resolution = None
    if decision is not None:
        resolution = str(getattr(decision, "value", decision))
    elif db_status != "waiting":
        resolution = db_status
    return upsert_human_intervention(
        intervention_id=str(getattr(intervention, "intervention_id")),
        job_id=str(getattr(intervention, "job_id")),
        run_id=getattr(intervention, "run_id", None),
        type=str(getattr(getattr(intervention, "type", None), "value", getattr(intervention, "type", "unknown"))),
        title=str(getattr(intervention, "title", "") or "Human action required"),
        message=str(getattr(intervention, "message", "") or ""),
        screenshot_s3_key=getattr(intervention, "screenshot_s3_key", None),
        status=db_status,
        created_at=getattr(intervention, "created_at", None),
        resolved_at=getattr(intervention, "resolved_at", None),
        resolution=resolution,
        timeout_at=getattr(intervention, "timeout_at", None),
        decision=decision,
    )


def summarize_publish_metadata(items: Iterable[Any]) -> dict[str, int]:
    """Derive run totals from published screenshot metadata."""
    pages: set[str] = set()
    total = 0
    ads = 0
    for item in items:
        kind = getattr(item, "kind", None)
        if isinstance(item, dict):
            kind = item.get("kind", "state")
            page = str(item.get("page") or "unknown")
            ad = bool(item.get("ad_detected"))
        else:
            if kind == "hitl":
                continue
            page = str(getattr(item, "page", None) or "unknown")
            ad = bool(getattr(item, "ad_detected", False))
        if kind == "hitl":
            continue
        total += 1
        pages.add(page)
        if ad:
            ads += 1
    return {
        "total_screenshots": total,
        "total_pages": len(pages),
        "total_ad_variations": ads,
    }
