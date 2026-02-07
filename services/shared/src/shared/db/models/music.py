"""Music catalog models: Track, Artist, TrackArtist, Play, AudioFeatures."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.db.base import Base
from shared.db.enums import TrackSource

if TYPE_CHECKING:
    from shared.db.models.user import User


class Track(Base):
    """Track metadata (Spotify IDs + local IDs from imports)."""

    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    spotify_track_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    local_track_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    album_name: Mapped[str | None] = mapped_column(String(500))
    album_spotify_id: Mapped[str | None] = mapped_column(String(255))
    isrc: Mapped[str | None] = mapped_column(String(50))
    source: Mapped[TrackSource] = mapped_column(SQLEnum(TrackSource), nullable=False, default=TrackSource.SPOTIFY_API)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    artists: Mapped[list[Artist]] = relationship("Artist", secondary="track_artists", back_populates="tracks")
    plays: Mapped[list[Play]] = relationship("Play", back_populates="track")
    audio_features: Mapped[AudioFeatures | None] = relationship("AudioFeatures", back_populates="track", uselist=False)


class Artist(Base):
    """Artist metadata (Spotify IDs + local IDs from imports)."""

    __tablename__ = "artists"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    spotify_artist_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    local_artist_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    genres: Mapped[str | None] = mapped_column(Text)
    source: Mapped[TrackSource] = mapped_column(SQLEnum(TrackSource), nullable=False, default=TrackSource.SPOTIFY_API)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    tracks: Mapped[list[Track]] = relationship("Track", secondary="track_artists", back_populates="artists")


class TrackArtist(Base):
    """Many-to-many relationship between tracks and artists."""

    __tablename__ = "track_artists"

    track_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True)
    artist_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (Index("ix_track_artists_track_id", "track_id"), Index("ix_track_artists_artist_id", "artist_id"))


class Play(Base):
    """Individual play events (unique on user_id, played_at, track_id)."""

    __tablename__ = "plays"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    track_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False)
    played_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    ms_played: Mapped[int | None] = mapped_column(Integer)
    context_type: Mapped[str | None] = mapped_column(String(50))
    context_uri: Mapped[str | None] = mapped_column(String(255))
    source: Mapped[TrackSource] = mapped_column(SQLEnum(TrackSource), nullable=False, default=TrackSource.SPOTIFY_API)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="plays")
    track: Mapped[Track] = relationship("Track", back_populates="plays")

    __table_args__ = (
        UniqueConstraint("user_id", "played_at", "track_id", name="uq_plays_user_played_track"),
        Index("ix_plays_user_id", "user_id"),
        Index("ix_plays_track_id", "track_id"),
        Index("ix_plays_user_played_at", "user_id", "played_at"),
    )


class AudioFeatures(Base):
    """Optional enrichment (danceability, energy, etc.)."""

    __tablename__ = "audio_features"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    track_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    danceability: Mapped[float | None] = mapped_column(Float)
    energy: Mapped[float | None] = mapped_column(Float)
    key: Mapped[int | None] = mapped_column(Integer)
    loudness: Mapped[float | None] = mapped_column(Float)
    mode: Mapped[int | None] = mapped_column(Integer)
    speechiness: Mapped[float | None] = mapped_column(Float)
    acousticness: Mapped[float | None] = mapped_column(Float)
    instrumentalness: Mapped[float | None] = mapped_column(Float)
    liveness: Mapped[float | None] = mapped_column(Float)
    valence: Mapped[float | None] = mapped_column(Float)
    tempo: Mapped[float | None] = mapped_column(Float)
    time_signature: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    track: Mapped[Track] = relationship("Track", back_populates="audio_features")
