"""Explorer frontend settings loaded from environment variables."""

import functools

from pydantic_settings import BaseSettings


class ExplorerSettings(BaseSettings):
    """Explorer service configuration."""

    API_BASE_URL: str = "http://api:8000"
    API_PUBLIC_URL: str = "http://localhost:8000"
    EXPLORER_BASE_URL: str = "http://localhost:8002"

    # Shared secret for internal API calls (exchange-google endpoint)
    INTERNAL_API_KEY: str = ""

    model_config = {"env_prefix": ""}


@functools.lru_cache(maxsize=1)
def get_settings() -> ExplorerSettings:
    """Return cached explorer settings singleton."""
    return ExplorerSettings()
