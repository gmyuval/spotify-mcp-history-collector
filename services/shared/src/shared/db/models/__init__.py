"""Re-export all model classes."""

from shared.db.models.cache import CachedPlaylist, CachedPlaylistTrack, SpotifyEntityCache
from shared.db.models.log import Log
from shared.db.models.memory import MemoryPlaylist, PlaylistEvent, PlaylistSnapshot, PreferenceEvent, TasteProfile
from shared.db.models.music import Artist, AudioFeatures, Play, Track, TrackArtist
from shared.db.models.operations import ImportJob, JobRun, SyncCheckpoint
from shared.db.models.rbac import Permission, Role, RolePermission, UserRole
from shared.db.models.settings import AppSetting
from shared.db.models.user import SpotifyToken, User

__all__ = [
    "AppSetting",
    "Artist",
    "AudioFeatures",
    "CachedPlaylist",
    "CachedPlaylistTrack",
    "ImportJob",
    "JobRun",
    "Log",
    "MemoryPlaylist",
    "Permission",
    "Play",
    "PlaylistEvent",
    "PlaylistSnapshot",
    "PreferenceEvent",
    "Role",
    "RolePermission",
    "SpotifyEntityCache",
    "SpotifyToken",
    "SyncCheckpoint",
    "TasteProfile",
    "Track",
    "TrackArtist",
    "User",
    "UserRole",
]
