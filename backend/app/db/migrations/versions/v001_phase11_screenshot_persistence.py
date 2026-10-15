"""Phase 11: screenshot_runs, screenshots, human_interventions."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

VERSION = "001_phase11_screenshot_persistence"


def upgrade(conn: Connection) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS screenshot_runs (
                run_id VARCHAR(64) PRIMARY KEY,
                app_id VARCHAR(256) NOT NULL,
                job_id VARCHAR(36) NOT NULL REFERENCES analysis_jobs(id) ON DELETE CASCADE,
                started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                completed_at TIMESTAMPTZ NULL,
                status VARCHAR(32) NOT NULL DEFAULT 'running',
                total_screenshots INTEGER NOT NULL DEFAULT 0,
                total_pages INTEGER NOT NULL DEFAULT 0,
                total_ad_variations INTEGER NOT NULL DEFAULT 0
            )
            """
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_screenshot_runs_app_id ON screenshot_runs (app_id)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_screenshot_runs_job_id ON screenshot_runs (job_id)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_screenshot_runs_status ON screenshot_runs (status)"
        )
    )

    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS screenshots (
                id VARCHAR(64) PRIMARY KEY,
                run_id VARCHAR(64) NOT NULL REFERENCES screenshot_runs(run_id) ON DELETE CASCADE,
                page VARCHAR(256) NOT NULL DEFAULT 'unknown',
                state_id VARCHAR(128) NOT NULL,
                s3_key VARCHAR(1024) NULL,
                width INTEGER NULL,
                height INTEGER NULL,
                trigger_action VARCHAR(128) NULL,
                ad_detected BOOLEAN NOT NULL DEFAULT FALSE,
                ad_type VARCHAR(64) NULL,
                ad_position VARCHAR(64) NULL,
                confidence DOUBLE PRECISION NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_screenshots_run_state UNIQUE (run_id, state_id)
            )
            """
        )
    )
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS ix_screenshots_run_id ON screenshots (run_id)")
    )
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS ix_screenshots_page ON screenshots (page)")
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_screenshots_state_id ON screenshots (state_id)"
        )
    )

    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS human_interventions (
                intervention_id VARCHAR(64) PRIMARY KEY,
                job_id VARCHAR(36) NOT NULL REFERENCES analysis_jobs(id) ON DELETE CASCADE,
                run_id VARCHAR(64) NULL REFERENCES screenshot_runs(run_id) ON DELETE SET NULL,
                type VARCHAR(64) NOT NULL,
                title VARCHAR(256) NOT NULL DEFAULT 'Human action required',
                message TEXT NOT NULL DEFAULT '',
                screenshot_s3_key VARCHAR(1024) NULL,
                status VARCHAR(32) NOT NULL DEFAULT 'waiting',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                resolved_at TIMESTAMPTZ NULL,
                resolution VARCHAR(32) NULL,
                timeout_at TIMESTAMPTZ NULL
            )
            """
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_human_interventions_job_id "
            "ON human_interventions (job_id)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_human_interventions_run_id "
            "ON human_interventions (run_id)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_human_interventions_type "
            "ON human_interventions (type)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_human_interventions_status "
            "ON human_interventions (status)"
        )
    )
