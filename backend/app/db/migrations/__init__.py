"""Versioned SQLAlchemy schema migrations (Phase 11+).

Applied by :func:`app.db.session.init_db` after ``create_all``. Tracks applied
versions in ``schema_migrations`` so additive DDL is idempotent.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

logger = logging.getLogger(__name__)

MigrationFn = Callable[[Connection], None]


def _ensure_migrations_table(conn: Connection) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(64) PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    )


def _applied_versions(conn: Connection) -> set[str]:
    rows = conn.execute(text("SELECT version FROM schema_migrations")).fetchall()
    return {str(row[0]) for row in rows}


def apply_migrations(engine: Engine | None) -> list[str]:
    """Apply pending migrations. Returns list of newly applied version ids."""
    if engine is None:
        return []

    from app.db.migrations.versions import MIGRATIONS

    applied_now: list[str] = []
    with engine.begin() as conn:
        _ensure_migrations_table(conn)
        done = _applied_versions(conn)
        for version, upgrade in MIGRATIONS:
            if version in done:
                continue
            logger.info("Applying DB migration %s", version)
            upgrade(conn)
            conn.execute(
                text("INSERT INTO schema_migrations (version) VALUES (:v)"),
                {"v": version},
            )
            applied_now.append(version)
    if applied_now:
        logger.info("Applied migrations: %s", ", ".join(applied_now))
    return applied_now


def list_migration_versions() -> list[str]:
    from app.db.migrations.versions import MIGRATIONS

    return [version for version, _ in MIGRATIONS]
