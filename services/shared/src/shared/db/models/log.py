"""Log model."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import Base, enum_values, utc_now
from shared.db.enums import LogLevel


class Log(Base):
    """Structured log events for UI browsing."""

    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now, index=True)
    service: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    level: Mapped[LogLevel] = mapped_column(SQLEnum(LogLevel, values_callable=enum_values), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    job_run_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("job_runs.id", ondelete="SET NULL"))
    import_job_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("import_jobs.id", ondelete="SET NULL"))
    log_metadata: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_logs_service_level", "service", "level"),
        Index("ix_logs_timestamp_service", "timestamp", "service"),
    )
