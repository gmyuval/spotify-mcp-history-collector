"""Database models for Spotify MCP History Collector.

Complete schema with all 11 tables:
- users, spotify_tokens, tracks, artists, track_artists, plays, audio_features
- sync_checkpoints, job_runs, import_jobs, logs
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Float,
    Enum as SQLEnum,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
import enum


class Base(DeclarativeBase):
    """Base class for all database models."""
    pass


# Enums
class SyncStatus(str, enum.Enum):
    """Sync status for users."""
    IDLE = "idle"
    PAUSED = "paused"
    SYNCING = "syncing"
    ERROR = "error"


class JobType(str, enum.Enum):
    """Types of collector jobs."""
    IMPORT_ZIP = "import_zip"
    INITIAL_SYNC = "initial_sync"
    POLL = "poll"
    ENRICH = "enrich"


class JobStatus(str, enum.Enum):
    """Job execution status."""
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"


class ImportStatus(str, enum.Enum):
    """Import job status."""
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    ERROR = "error"


class LogLevel(str, enum.Enum):
    """Log levels."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class TrackSource(str, enum.Enum):
    """Source of track data."""
    SPOTIFY_API = "spotify_api"
    IMPORT_ZIP = "import_zip"


# Core tables
class User(Base):
    """Spotify user profiles."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    spotify_user_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(255))
    email: Mapped[Optional[str]] = mapped_column(String(255))
    country: Mapped[Optional[str]] = mapped_column(String(10))
    product: Mapped[Optional[str]] = mapped_column(String(50))  # e.g., "premium"
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    token: Mapped[Optional["SpotifyToken"]] = relationship("SpotifyToken", back_populates="user", uselist=False)
    plays: Mapped[list["Play"]] = relationship("Play", back_populates="user")
    sync_checkpoint: Mapped[Optional["SyncCheckpoint"]] = relationship(
        "SyncCheckpoint", back_populates="user", uselist=False
    )
    job_runs: Mapped[list["JobRun"]] = relationship("JobRun", back_populates="user")
    import_jobs: Mapped[list["ImportJob"]] = relationship("ImportJob", back_populates="user")


class SpotifyToken(Base):
    """Encrypted refresh tokens and access tokens."""
    __tablename__ = "spotify_tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    encrypted_refresh_token: Mapped[str] = mapped_column(Text, nullable=False)  # Fernet encrypted
    access_token: Mapped[Optional[str]] = mapped_column(Text)  # Stored in memory, can be null
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    scope: Mapped[Optional[str]] = mapped_column(Text)  # Space-separated scopes
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="token")

    __table_args__ = (Index("ix_spotify_tokens_user_id", "user_id", unique=True),)


class Track(Base):
    """Track metadata (Spotify IDs + local IDs from imports)."""
    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    spotify_track_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True, index=True)
    local_track_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    album_name: Mapped[Optional[str]] = mapped_column(String(500))
    album_spotify_id: Mapped[Optional[str]] = mapped_column(String(255))
    isrc: Mapped[Optional[str]] = mapped_column(String(50))
    source: Mapped[TrackSource] = mapped_column(SQLEnum(TrackSource), nullable=False, default=TrackSource.SPOTIFY_API)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    artists: Mapped[list["Artist"]] = relationship("Artist", secondary="track_artists", back_populates="tracks")
    plays: Mapped[list["Play"]] = relationship("Play", back_populates="track")
    audio_features: Mapped[Optional["AudioFeatures"]] = relationship(
        "AudioFeatures", back_populates="track", uselist=False
    )


class Artist(Base):
    """Artist metadata (Spotify IDs + local IDs from imports)."""
    __tablename__ = "artists"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    spotify_artist_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True, index=True)
    local_artist_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    genres: Mapped[Optional[str]] = mapped_column(Text)  # JSON array as string
    source: Mapped[TrackSource] = mapped_column(SQLEnum(TrackSource), nullable=False, default=TrackSource.SPOTIFY_API)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    tracks: Mapped[list["Track"]] = relationship("Track", secondary="track_artists", back_populates="artists")


class TrackArtist(Base):
    """Many-to-many relationship between tracks and artists."""
    __tablename__ = "track_artists"

    track_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True)
    artist_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # Order of artists on track

    __table_args__ = (Index("ix_track_artists_track_id", "track_id"), Index("ix_track_artists_artist_id", "artist_id"))


class Play(Base):
    """Individual play events (unique on user_id, played_at, track_id)."""
    __tablename__ = "plays"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    track_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False)
    played_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    ms_played: Mapped[Optional[int]] = mapped_column(Integer)  # From ZIP imports
    context_type: Mapped[Optional[str]] = mapped_column(String(50))  # playlist, album, artist, etc.
    context_uri: Mapped[Optional[str]] = mapped_column(String(255))
    source: Mapped[TrackSource] = mapped_column(SQLEnum(TrackSource), nullable=False, default=TrackSource.SPOTIFY_API)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="plays")
    track: Mapped["Track"] = relationship("Track", back_populates="plays")

    __table_args__ = (
        UniqueConstraint("user_id", "played_at", "track_id", name="uq_plays_user_played_track"),
        Index("ix_plays_user_id", "user_id"),
        Index("ix_plays_track_id", "track_id"),
        Index("ix_plays_user_played_at", "user_id", "played_at"),
    )


class AudioFeatures(Base):
    """Optional enrichment (danceability, energy, etc.)."""
    __tablename__ = "audio_features"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    track_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    danceability: Mapped[Optional[float]] = mapped_column(Float)
    energy: Mapped[Optional[float]] = mapped_column(Float)
    key: Mapped[Optional[int]] = mapped_column(Integer)
    loudness: Mapped[Optional[float]] = mapped_column(Float)
    mode: Mapped[Optional[int]] = mapped_column(Integer)
    speechiness: Mapped[Optional[float]] = mapped_column(Float)
    acousticness: Mapped[Optional[float]] = mapped_column(Float)
    instrumentalness: Mapped[Optional[float]] = mapped_column(Float)
    liveness: Mapped[Optional[float]] = mapped_column(Float)
    valence: Mapped[Optional[float]] = mapped_column(Float)
    tempo: Mapped[Optional[float]] = mapped_column(Float)
    time_signature: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    track: Mapped["Track"] = relationship("Track", back_populates="audio_features")


# Operational tables
class SyncCheckpoint(Base):
    """Per-user sync state."""
    __tablename__ = "sync_checkpoints"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    status: Mapped[SyncStatus] = mapped_column(SQLEnum(SyncStatus), nullable=False, default=SyncStatus.IDLE)

    # Initial sync tracking
    initial_sync_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    initial_sync_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    initial_sync_earliest_played_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Polling tracking
    last_poll_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_poll_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_poll_latest_played_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="sync_checkpoint")


class JobRun(Base):
    """Job execution history."""
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_type: Mapped[JobType] = mapped_column(SQLEnum(JobType), nullable=False)
    status: Mapped[JobStatus] = mapped_column(SQLEnum(JobStatus), nullable=False, default=JobStatus.RUNNING)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Statistics
    records_fetched: Mapped[int] = mapped_column(Integer, default=0)
    records_inserted: Mapped[int] = mapped_column(Integer, default=0)
    records_skipped: Mapped[int] = mapped_column(Integer, default=0)

    error_message: Mapped[Optional[str]] = mapped_column(Text)
    job_metadata: Mapped[Optional[str]] = mapped_column(Text)  # JSON metadata

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="job_runs")

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
    status: Mapped[ImportStatus] = mapped_column(SQLEnum(ImportStatus), nullable=False, default=ImportStatus.PENDING)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    format_detected: Mapped[Optional[str]] = mapped_column(String(100))  # e.g., "endsong", "streaming_history"
    records_ingested: Mapped[int] = mapped_column(Integer, default=0)
    earliest_played_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    latest_played_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="import_jobs")

    __table_args__ = (
        Index("ix_import_jobs_user_id", "user_id"),
        Index("ix_import_jobs_status", "status"),
        Index("ix_import_jobs_created_at", "created_at"),
    )


class Log(Base):
    """Structured log events for UI browsing."""
    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    service: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # api, collector, frontend
    level: Mapped[LogLevel] = mapped_column(SQLEnum(LogLevel), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    job_run_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("job_runs.id", ondelete="SET NULL"))
    import_job_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("import_jobs.id", ondelete="SET NULL"))
    log_metadata: Mapped[Optional[str]] = mapped_column(Text)  # JSON metadata

    __table_args__ = (
        Index("ix_logs_service_level", "service", "level"),
        Index("ix_logs_timestamp_service", "timestamp", "service"),
    )
