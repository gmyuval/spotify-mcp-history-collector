"""Collector service configuration loaded from environment variables."""

from pydantic_settings import BaseSettings


class CollectorSettings(BaseSettings):
    """Collector service configuration."""

    # Spotify credentials
    SPOTIFY_CLIENT_ID: str = ""
    SPOTIFY_CLIENT_SECRET: str = ""

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/spotify_mcp"

    # Encryption
    TOKEN_ENCRYPTION_KEY: str = ""

    # Polling
    COLLECTOR_INTERVAL_SECONDS: int = 600
    TOKEN_EXPIRY_BUFFER_SECONDS: int = 60

    # Initial sync
    INITIAL_SYNC_ENABLED: bool = True
    INITIAL_SYNC_MAX_DAYS: int = 30
    INITIAL_SYNC_MAX_REQUESTS: int = 200
    INITIAL_SYNC_CONCURRENCY: int = 2

    # Import
    IMPORT_WATCH_DIR: str = ""
    IMPORT_MAX_ZIP_SIZE_MB: int = 500
    IMPORT_MAX_RECORDS: int = 5_000_000

    model_config = {"env_prefix": ""}
