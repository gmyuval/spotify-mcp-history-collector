"""Operational models: SyncCheckpoint, JobRun, ImportJob."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.db.base import Base, enum_values, utc_now
from shared.db.enums import ImportStatus, JobStatus, JobType, SyncStatus

if TYPE_CHECKING:
    from shared.db.models.user import User


class SyncCheckpoint(Base):
    """Per-user sync state."""

    __tablename__ = "sync_checkpoints"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    status: Mapped[SyncStatus] = mapped_column(
        SQLEnum(SyncStatus, values_callable=enum_values),
        nullable=False,
        default=SyncStatus.IDLE,
    )

    # Initial sync tracking
    initial_sync_started_at: Mapped[datetime | None] = mapped_column(DateTime)
    initial_sync_completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    initial_sync_earliest_played_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Polling tracking
    last_poll_started_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_poll_completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_poll_latest_played_at: Mapped[datetime | None] = mapped_column(DateTime)

    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="sync_checkpoint")


class JobRun(Base):
    """Job execution history."""

    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_type: Mapped[JobType] = mapped_column(SQLEnum(JobType, values_callable=enum_values), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        SQLEnum(JobStatus, values_callable=enum_values),
        nullable=False,
        default=JobStatus.RUNNING,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Statistics
    records_fetched: Mapped[int] = mapped_column(Integer, default=0)
    records_inserted: Mapped[int] = mapped_column(Integer, default=0)
    records_skipped: Mapped[int] = mapped_column(Integer, default=0)

    error_message: Mapped[str | None] = mapped_column(Text)
    job_metadata: Mapped[str | None] = mapped_column(Text)

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="job_runs")

    __table_args__ = (
        Index("ix_job_runs_user_id", "user_id"),
        Index("ix_job_runs_started_at", "started_at"),
        Index("ix_job_runs_user_started", "user_id", "started_at"),
    )


class ImportJob(Base):
    """ZIP upload/ingestion tracking."""

    __tablename__ = "import_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[ImportStatus] = mapped_column(
        SQLEnum(ImportStatus, values_callable=enum_values),
        nullable=False,
        default=ImportStatus.PENDING,
    )
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    format_detected: Mapped[str | None] = mapped_column(String(100))
    records_ingested: Mapped[int] = mapped_column(Integer, default=0)
    earliest_played_at: Mapped[datetime | None] = mapped_column(DateTime)
    latest_played_at: Mapped[datetime | None] = mapped_column(DateTime)

    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="import_jobs")

    __table_args__ = (
        Index("ix_import_jobs_user_id", "user_id"),
        Index("ix_import_jobs_status", "status"),
        Index("ix_import_jobs_created_at", "created_at"),
    )
