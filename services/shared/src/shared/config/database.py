"""Database configuration settings."""

from pydantic_settings import BaseSettings

from shared.config.constants import DEFAULT_DATABASE_URL


class DatabaseSettings(BaseSettings):
    """Database connection settings loaded from environment variables."""

    database_url: str = DEFAULT_DATABASE_URL
    echo: bool = False
    use_null_pool: bool = True
    pool_pre_ping: bool = True

    model_config = {"env_prefix": ""}
