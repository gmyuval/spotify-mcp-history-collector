"""SQLAlchemy declarative base."""

import enum
from datetime import UTC, datetime

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all database models."""


def enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return enum member values for SQLAlchemy Enum values_callable."""
    return [e.value for e in enum_cls]


def utc_now() -> datetime:
    """Return current UTC time as a timezone-aware datetime."""
    return datetime.now(UTC)
