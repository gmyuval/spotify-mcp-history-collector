"""Spotify API cache models: CachedPlaylist, CachedPlaylistTrack, SpotifyEntityCache."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.db.base import Base, utc_now


class CachedPlaylist(Base):
    """Cached Spotify playlist metadata.

    Uses snapshot_id for invalidation — if Spotify's snapshot_id differs
    from the cached value, the playlist has changed and must be re-fetched.
    """

    __tablename__ = "cached_playlists"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    spotify_playlist_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[str | None] = mapped_column(String(255))
    owner_display_name: Mapped[str | None] = mapped_column(String(500))
    public: Mapped[bool | None] = mapped_column(Boolean)
    collaborative: Mapped[bool | None] = mapped_column(Boolean)
    snapshot_id: Mapped[str | None] = mapped_column(String(255))
    total_tracks: Mapped[int | None] = mapped_column(Integer)
    external_url: Mapped[str | None] = mapped_column(String(500))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    # Relationships
    tracks: Mapped[list[CachedPlaylistTrack]] = relationship(
        "CachedPlaylistTrack", back_populates="playlist", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("spotify_playlist_id", "user_id", name="uq_cached_playlist_spotify_user"),
        Index("ix_cached_playlists_user_spotify", "user_id", "spotify_playlist_id"),
    )


class CachedPlaylistTrack(Base):
    """Tracks within a cached playlist."""

    __tablename__ = "cached_playlist_tracks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cached_playlist_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cached_playlists.id", ondelete="CASCADE"), nullable=False, index=True
    )
    spotify_track_id: Mapped[str | None] = mapped_column(String(255))
    track_name: Mapped[str] = mapped_column(String(500), nullable=False)
    artists_json: Mapped[str | None] = mapped_column(Text)
    added_at: Mapped[str | None] = mapped_column(String(50))
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationships
    playlist: Mapped[CachedPlaylist] = relationship("CachedPlaylist", back_populates="tracks")


class SpotifyEntityCache(Base):
    """Generic TTL-based cache for tracks, artists, and albums.

    Stores the full Spotify API response as JSON so it can be
    re-serialized on cache hits without any API call.
    """

    __tablename__ = "spotify_entity_cache"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    spotify_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (UniqueConstraint("entity_type", "spotify_id", name="uq_entity_cache_type_id"),)
