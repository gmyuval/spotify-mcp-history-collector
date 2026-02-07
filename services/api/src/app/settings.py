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

    model_config = {"env_prefix": ""}


@functools.lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Return cached application settings singleton."""
    return AppSettings()
