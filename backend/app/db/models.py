from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120))
    company_name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class AnalysisRecord(Base):
    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    package_name: Mapped[str | None] = mapped_column(String(256), index=True, nullable=True)
    file_name: Mapped[str] = mapped_column(String(512))
    file_size: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(32))
    analyzer_version: Mapped[str] = mapped_column(String(32))
    result: Mapped[dict] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class ScreenshotFile(Base):
    __tablename__ = "screenshot_files"
    __table_args__ = (UniqueConstraint("analysis_id", "file_name", name="uq_screenshot_analysis_file"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    analysis_id: Mapped[str] = mapped_column(String(36), ForeignKey("analyses.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    original_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    content_type: Mapped[str] = mapped_column(String(64), default="application/octet-stream")
    width: Mapped[int | None] = mapped_column(nullable=True)
    height: Mapped[int | None] = mapped_column(nullable=True)
    byte_size: Mapped[int] = mapped_column(BigInteger)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class AnalysisJob(Base):
    """Lifecycle record for an asynchronous analyze-and-explore request.

    The synchronous /analyze endpoint does not use this table; it exists so long
    running emulator exploration can be polled instead of held open over HTTP.
    """

    __tablename__ = "analysis_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    stage: Mapped[str] = mapped_column(String(40))
    progress: Mapped[int] = mapped_column(Integer, default=0)
    file_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    package_name: Mapped[str | None] = mapped_column(String(256), index=True, nullable=True)
    exploration_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExplorationScreenshot(Base):
    """Metadata for one emulator screen capture.

    Bytes live in S3 (see ``exploration_s3_prefix``); only metadata is stored here,
    unlike ``screenshot_files`` which embeds small APK assets directly.
    """

    __tablename__ = "exploration_screenshots"
    __table_args__ = (
        UniqueConstraint("job_id", "file_name", name="uq_exploration_job_file"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    state_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    file_name: Mapped[str] = mapped_column(String(255))
    s3_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    activity: Mapped[str | None] = mapped_column(String(512), nullable=True)
    fingerprint: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    content_type: Mapped[str] = mapped_column(String(64), default="image/png")
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    byte_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ad_count: Mapped[int] = mapped_column(Integer, default=0)
    ad_coverage_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
