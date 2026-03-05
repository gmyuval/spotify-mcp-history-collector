"""Admin-configurable settings model."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import Base, utc_now

# JSONB on PostgreSQL, plain JSON on SQLite (tests)
_JsonB = JSONB().with_variant(JSON(), "sqlite")


class AppSetting(Base):
    """Admin-configurable setting stored as a key-value pair.

    Keys are dotted namespaced strings (e.g. ``search.default_limit``).
    Values are stored as JSONB to support int, float, str, list, and dict.
    Defaults live in :class:`~app.admin.settings_service.SettingsService`;
    the DB only stores overrides.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value_json: Mapped[Any] = mapped_column(_JsonB, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
