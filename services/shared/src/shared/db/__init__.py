"""Shared database package -- convenience re-exports.

Importing this module registers all models with Base.metadata.
"""

from shared.db.base import Base
from shared.db.enums import ImportStatus, JobStatus, JobType, LogLevel, SyncStatus, TrackSource
from shared.db.models import (
    AppSetting,
    Artist,
    AudioFeatures,
    CachedPlaylist,
    CachedPlaylistTrack,
    ImportJob,
    JobRun,
    Log,
    Permission,
    Play,
    Role,
    RolePermission,
    SpotifyEntityCache,
    SpotifyToken,
    SyncCheckpoint,
    Track,
    TrackArtist,
    User,
    UserRole,
)
from shared.db.operations import MusicRepository
from shared.db.search import text_match
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
    "AppSetting",
    "Artist",
    "AudioFeatures",
    "CachedPlaylist",
    "CachedPlaylistTrack",
    "ImportJob",
    "JobRun",
    "Log",
    "Permission",
    "Play",
    "Role",
    "RolePermission",
    "SpotifyEntityCache",
    "SpotifyToken",
    "SyncCheckpoint",
    "Track",
    "TrackArtist",
    "User",
    "UserRole",
    # Session
    "DatabaseManager",
    # Operations
    "MusicRepository",
    # Search
    "text_match",
]
