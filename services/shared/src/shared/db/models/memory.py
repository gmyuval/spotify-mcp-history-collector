"""MCP Memory models: TasteProfile, PreferenceEvent, and Playlist Ledger."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Enum, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import Base, enum_values, utc_now
from shared.db.enums import (
    PlaylistEventType,
    PlaylistSnapshotSource,
    PreferenceEventSource,
    PreferenceEventType,
)

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


# ── Playlist Ledger ──────────────────────────────────────────────────


class MemoryPlaylist(Base):
    """Assistant-tracked playlist with metadata and intent context.

    The playlist_id is the Spotify playlist ID (string PK).
    The ledger is the canonical record even when Spotify read-back fails.
    """

    __tablename__ = "memory_playlists"

    playlist_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    intent_tags: Mapped[list[object]] = mapped_column(_JsonB, nullable=False, default=list)
    seed_context: Mapped[dict[str, object]] = mapped_column(_JsonB, nullable=False, default=dict)
    latest_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("playlist_snapshots.snapshot_id", ondelete="SET NULL", use_alter=True), nullable=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class PlaylistSnapshot(Base):
    """Point-in-time snapshot of a playlist's track list.

    Snapshots are created at playlist creation and periodically after N
    mutations for fast reconstruction.
    """

    __tablename__ = "playlist_snapshots"

    snapshot_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    playlist_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("memory_playlists.playlist_id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    track_ids: Mapped[list[object]] = mapped_column(_JsonB, nullable=False)
    source: Mapped[str] = mapped_column(
        Enum(PlaylistSnapshotSource, values_callable=enum_values, name="playlist_snapshot_source"),
        nullable=False,
    )


class PlaylistEvent(Base):
    """Append-only mutation ledger for playlist changes.

    Each event records a single mutation (add/remove/reorder/meta update)
    with its payload. Events are replayed on top of snapshots for reconstruction.
    """

    __tablename__ = "playlist_events"
    __table_args__ = (Index("ix_playlist_events_playlist_timestamp", "playlist_id", "timestamp"),)

    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    playlist_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("memory_playlists.playlist_id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    type: Mapped[str] = mapped_column(
        Enum(PlaylistEventType, values_callable=enum_values, name="playlist_event_type"),
        nullable=False,
    )
    payload_json: Mapped[dict[str, object]] = mapped_column(_JsonB, nullable=False)
    client_event_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, unique=True)
