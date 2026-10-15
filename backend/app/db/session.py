from __future__ import annotations

import logging

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings

logger = logging.getLogger(__name__)

engine: Engine | None = None
SessionLocal: sessionmaker[Session] | None = None


def _sqlalchemy_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and "+psycopg" not in url and "+psycopg2" not in url:
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def init_engine() -> Engine | None:
    global engine, SessionLocal
    url = (settings.database_url or "").strip()
    if not url:
        logger.info("DATABASE_URL is not set; analysis history will not be persisted.")
        engine = None
        SessionLocal = None
        return None
    engine = create_engine(
        _sqlalchemy_url(url),
        poolclass=NullPool,
        connect_args={"prepare_threshold": None},
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return engine


def init_db() -> None:
    from app.db.migrations import apply_migrations
    from app.db.models import Base

    if engine is None:
        return
    Base.metadata.create_all(bind=engine)
    # Best-effort additive columns for Phase 7 HITL on existing deployments.
    for stmt in (
        "ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS intervention JSONB",
        "ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS exploration_checkpoint JSONB",
        "ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS user_id VARCHAR(36)",
        "ALTER TABLE analyses ADD COLUMN IF NOT EXISTS user_id VARCHAR(36)",
        "CREATE INDEX IF NOT EXISTS ix_analysis_jobs_user_id ON analysis_jobs (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_analyses_user_id ON analyses (user_id)",
    ):
        try:
            with engine.begin() as conn:
                conn.execute(text(stmt))
        except Exception:
            logger.debug("Optional schema alter skipped: %s", stmt, exc_info=True)
    try:
        apply_migrations(engine)
    except Exception:
        logger.exception("Phase 11 schema migrations failed")
    logger.info("PostgreSQL schema is ready.")


def get_session() -> Session:
    if SessionLocal is None:
        raise RuntimeError("Database is not configured.")
    return SessionLocal()


def database_ready() -> bool:
    if engine is None:
        return False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.warning("PostgreSQL health check failed", exc_info=True)
        return False


init_engine()
