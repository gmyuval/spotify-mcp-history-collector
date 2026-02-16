"""Shared database package -- convenience re-exports.

Importing this module registers all models with Base.metadata.
"""

from shared.db.base import Base
from shared.db.enums import ImportStatus, JobStatus, JobType, LogLevel, SyncStatus, TrackSource
from shared.db.models import (
    Artist,
    AudioFeatures,
    CachedPlaylist,
    CachedPlaylistTrack,
    ImportJob,
    JobRun,
    Log,
    Play,
    SpotifyEntityCache,
    SpotifyToken,
    SyncCheckpoint,
    Track,
    TrackArtist,
    User,
)
from shared.db.operations import MusicRepository
from shared.db.session import DatabaseManager

__all__ = [
    # Base
    "Base",
    # Enums
    "ImportStatus",
    "JobStatus",
    "JobType",
    "LogLevel",
    "SyncStatus",
    "TrackSource",
    # Models
    "Artist",
    "AudioFeatures",
    "CachedPlaylist",
    "CachedPlaylistTrack",
    "ImportJob",
    "JobRun",
    "Log",
    "Play",
    "SpotifyEntityCache",
    "SpotifyToken",
    "SyncCheckpoint",
    "Track",
    "TrackArtist",
    "User",
    # Session
    "DatabaseManager",
    # Operations
    "MusicRepository",
]
