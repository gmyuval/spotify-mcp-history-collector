"""Database enums for Spotify MCP models."""

import enum


class SyncStatus(enum.StrEnum):
    """Sync status for users."""

    IDLE = "idle"
    PAUSED = "paused"
    SYNCING = "syncing"
    ERROR = "error"


class JobType(enum.StrEnum):
    """Types of collector jobs."""

    IMPORT_ZIP = "import_zip"
    INITIAL_SYNC = "initial_sync"
    POLL = "poll"
    ENRICH = "enrich"


class JobStatus(enum.StrEnum):
    """Job execution status."""

    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"


class ImportStatus(enum.StrEnum):
    """Import job status."""

    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    ERROR = "error"


class LogLevel(enum.StrEnum):
    """Log levels."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class TrackSource(enum.StrEnum):
    """Source of track data."""

    SPOTIFY_API = "spotify_api"
    IMPORT_ZIP = "import_zip"
