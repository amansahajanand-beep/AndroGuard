"""Phase 11 PostgreSQL persistence tests (models, migrations, status mapping)."""

from __future__ import annotations

from types import SimpleNamespace

from app.db.migrations import list_migration_versions
from app.db.models import (
    AnalysisJob,
    ExplorationScreenshot,
    HumanIntervention,
    Screenshot,
    ScreenshotFile,
    ScreenshotRun,
)
from app.db.phase11_repository import (
    HITL_DB_STATUSES,
    map_hitl_status_to_db,
    summarize_publish_metadata,
)
from app.modules.hitl.intervention_types import (
    HumanDecision,
    InterventionStatus,
)


def test_phase11_tables_do_not_replace_legacy_screenshot_tables() -> None:
    assert ScreenshotFile.__tablename__ == "screenshot_files"
    assert ExplorationScreenshot.__tablename__ == "exploration_screenshots"
    assert ScreenshotRun.__tablename__ == "screenshot_runs"
    assert Screenshot.__tablename__ == "screenshots"
    assert HumanIntervention.__tablename__ == "human_interventions"
    assert AnalysisJob.__tablename__ == "analysis_jobs"


def test_phase11_migration_is_registered() -> None:
    versions = list_migration_versions()
    assert "001_phase11_screenshot_persistence" in versions


def test_hitl_status_mapping_uses_continued() -> None:
    assert map_hitl_status_to_db(InterventionStatus.WAITING) == "waiting"
    assert map_hitl_status_to_db(InterventionStatus.RESOLVED) == "continued"
    assert map_hitl_status_to_db(
        InterventionStatus.RESOLVED, decision=HumanDecision.CONTINUE
    ) == "continued"
    assert map_hitl_status_to_db(InterventionStatus.SKIPPED) == "skipped"
    assert map_hitl_status_to_db(InterventionStatus.STOPPED) == "stopped"
    assert map_hitl_status_to_db(InterventionStatus.TIMEOUT) == "timeout"
    assert HITL_DB_STATUSES == {
        "waiting",
        "continued",
        "skipped",
        "stopped",
        "timeout",
    }


def test_summarize_publish_metadata_skips_hitl() -> None:
    items = [
        SimpleNamespace(kind="state", page="Home", ad_detected=True),
        SimpleNamespace(kind="state", page="Home", ad_detected=False),
        SimpleNamespace(kind="state", page="Settings", ad_detected=True),
        SimpleNamespace(kind="hitl", page="hitl", ad_detected=False),
    ]
    totals = summarize_publish_metadata(items)
    assert totals == {
        "total_screenshots": 3,
        "total_pages": 2,
        "total_ad_variations": 2,
    }


def test_screenshot_run_columns_match_contract() -> None:
    cols = set(ScreenshotRun.__table__.c.keys())
    assert {
        "run_id",
        "app_id",
        "job_id",
        "started_at",
        "completed_at",
        "status",
        "total_screenshots",
        "total_pages",
        "total_ad_variations",
    } <= cols


def test_screenshots_columns_match_contract() -> None:
    cols = set(Screenshot.__table__.c.keys())
    assert {
        "id",
        "run_id",
        "page",
        "state_id",
        "s3_key",
        "width",
        "height",
        "trigger_action",
        "ad_detected",
        "ad_type",
        "ad_position",
        "confidence",
        "created_at",
    } <= cols


def test_human_interventions_columns_match_contract() -> None:
    cols = set(HumanIntervention.__table__.c.keys())
    assert {
        "intervention_id",
        "job_id",
        "run_id",
        "type",
        "title",
        "message",
        "screenshot_s3_key",
        "status",
        "created_at",
        "resolved_at",
        "resolution",
        "timeout_at",
    } <= cols


def test_persist_helpers_noop_without_database(monkeypatch) -> None:
    from app.db import phase11_repository as repo

    monkeypatch.setattr(repo, "engine", None)
    monkeypatch.setattr(repo, "SessionLocal", None)
    assert repo.start_screenshot_run(run_id="r1", app_id="app", job_id="j1") is None
    assert repo.complete_screenshot_run(run_id="r1") is None
    assert repo.persist_screenshots_for_run(run_id="r1", items=[]) == 0
    assert (
        repo.upsert_human_intervention(
            intervention_id="h1",
            job_id="j1",
            run_id="r1",
            type="permission",
            title="t",
            message="m",
        )
        is None
    )
