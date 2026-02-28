"""MCP Memory models: TasteProfile and PreferenceEvent."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Enum, ForeignKey, Integer, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import Base, enum_values, utc_now
from shared.db.enums import PreferenceEventSource, PreferenceEventType

# JSONB on PostgreSQL, plain JSON on SQLite (tests)
_JsonB = JSONB().with_variant(JSON(), "sqlite")


class TasteProfile(Base):
    """Per-user taste profile — single JSONB document, versioned.

    The profile stores normalized taste data (genres, rules, energy
    preferences, etc.) that the assistant patch-merges on each update.
    """

    __tablename__ = "taste_profiles"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    profile_json: Mapped[dict[str, object]] = mapped_column(_JsonB, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class PreferenceEvent(Base):
    """Append-only log of explicit user preferences and feedback.

    Each event captures *what was said* — the raw feedback — while the
    TasteProfile captures the *normalized durable rule*.
    """

    __tablename__ = "preference_events"

    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    source: Mapped[str] = mapped_column(
        Enum(PreferenceEventSource, values_callable=enum_values, name="preference_event_source"),
        nullable=False,
        default=PreferenceEventSource.ASSISTANT,
    )
    type: Mapped[str] = mapped_column(
        Enum(PreferenceEventType, values_callable=enum_values, name="preference_event_type"),
        nullable=False,
    )
    payload_json: Mapped[dict[str, object]] = mapped_column(_JsonB, nullable=False, default=dict)
