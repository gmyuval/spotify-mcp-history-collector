"""User and authentication models."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.db.base import Base, utc_now

if TYPE_CHECKING:
    from shared.db.models.music import Play
    from shared.db.models.operations import ImportJob, JobRun, SyncCheckpoint


class User(Base):
    """Spotify user profiles."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    spotify_user_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    country: Mapped[str | None] = mapped_column(String(10))
    product: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    # Relationships
    token: Mapped[SpotifyToken | None] = relationship("SpotifyToken", back_populates="user", uselist=False)
    plays: Mapped[list[Play]] = relationship("Play", back_populates="user")
    sync_checkpoint: Mapped[SyncCheckpoint | None] = relationship(
        "SyncCheckpoint", back_populates="user", uselist=False
    )
    job_runs: Mapped[list[JobRun]] = relationship("JobRun", back_populates="user")
    import_jobs: Mapped[list[ImportJob]] = relationship("ImportJob", back_populates="user")


class SpotifyToken(Base):
    """Encrypted refresh tokens and access tokens."""

    __tablename__ = "spotify_tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    encrypted_refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    access_token: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scope: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="token")

    __table_args__ = (Index("ix_spotify_tokens_user_id", "user_id", unique=True),)
