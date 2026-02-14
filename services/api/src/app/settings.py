"""Application settings loaded from environment variables."""

import functools

from pydantic_settings import BaseSettings

from app.constants import (
    DEFAULT_OAUTH_STATE_TTL_SECONDS,
    DEFAULT_SPOTIFY_REDIRECT_URI,
    DEFAULT_TOKEN_EXPIRY_BUFFER_SECONDS,
)


class AppSettings(BaseSettings):
    """API service configuration."""

    SPOTIFY_CLIENT_ID: str = ""
    SPOTIFY_CLIENT_SECRET: str = ""
    SPOTIFY_REDIRECT_URI: str = DEFAULT_SPOTIFY_REDIRECT_URI
    TOKEN_ENCRYPTION_KEY: str = ""
    OAUTH_STATE_TTL_SECONDS: int = DEFAULT_OAUTH_STATE_TTL_SECONDS
    TOKEN_EXPIRY_BUFFER_SECONDS: int = DEFAULT_TOKEN_EXPIRY_BUFFER_SECONDS

    # Import uploads
    UPLOAD_DIR: str = "/app/uploads"
    IMPORT_MAX_ZIP_SIZE_MB: int = 500

    # Admin authentication
    ADMIN_AUTH_MODE: str = ""  # "token", "basic", or "" (disabled)
    ADMIN_TOKEN: str = ""  # For token auth mode
    ADMIN_USERNAME: str = ""  # For basic auth mode
    ADMIN_PASSWORD: str = ""  # For basic auth mode

    # CORS
    CORS_ALLOWED_ORIGINS: str = "http://localhost:8001"  # comma-separated origins

    # Rate limiting
    RATE_LIMIT_AUTH_PER_MINUTE: int = 10
    RATE_LIMIT_MCP_PER_MINUTE: int = 60

    # Logging
    LOG_RETENTION_DAYS: int = 30

    model_config = {"env_prefix": ""}


@functools.lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Return cached application settings singleton."""
    return AppSettings()
