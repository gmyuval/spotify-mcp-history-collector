"""Shared configuration."""

from shared.config.constants import DEFAULT_DATABASE_URL
from shared.config.database import DatabaseSettings

__all__ = [
    "DEFAULT_DATABASE_URL",
    "DatabaseSettings",
]
