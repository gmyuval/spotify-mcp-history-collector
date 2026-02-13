"""Frontend settings loaded from environment variables."""

import functools
from typing import Literal

from pydantic_settings import BaseSettings


class FrontendSettings(BaseSettings):
    """Frontend service configuration."""

    API_BASE_URL: str = "http://api:8000"
    FRONTEND_AUTH_MODE: Literal["token", "basic", ""] = "token"
    ADMIN_TOKEN: str = ""
    ADMIN_USERNAME: str = ""
    ADMIN_PASSWORD: str = ""

    model_config = {"env_prefix": ""}


@functools.lru_cache(maxsize=1)
def get_settings() -> FrontendSettings:
    """Return cached frontend settings singleton."""
    return FrontendSettings()
