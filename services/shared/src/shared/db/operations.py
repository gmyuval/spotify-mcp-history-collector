"""Database operations for music data — bridges Spotify models to DB models."""

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.enums import TrackSource
from shared.db.models.music import Artist, Play, Track, TrackArtist
from shared.spotify.models import (
    SpotifyArtistSimplified,
    SpotifyPlayHistoryItem,
    SpotifyTrack,
)

logger = logging.getLogger(__name__)


class MusicRepository:
    """Upserts tracks, artists, plays from Spotify API responses into the DB."""

    async def upsert_track(
        self,
        spotify_track: SpotifyTrack,
        session: AsyncSession,
    ) -> Track:
        """Insert or update a track from a Spotify API response.

        Matches by spotify_track_id. Updates name, duration, album info on match.
        """
        if not spotify_track.id:
            # Local tracks without Spotify IDs — find by name or create
            result = await session.execute(select(Track).where(Track.name == spotify_track.name).limit(1))
            existing = result.scalar_one_or_none()
            if existing:
                return existing
            track = Track(
                name=spotify_track.name,
                duration_ms=spotify_track.duration_ms,
                source=TrackSource.SPOTIFY_API,
            )
            session.add(track)
            await session.flush()
            return track

        result = await session.execute(select(Track).where(Track.spotify_track_id == spotify_track.id))
        existing = result.scalar_one_or_none()

        album_name = spotify_track.album.name if spotify_track.album else None
        album_spotify_id = spotify_track.album.id if spotify_track.album else None
        isrc = spotify_track.external_ids.isrc if spotify_track.external_ids else None

        if existing:
            existing.name = spotify_track.name
            existing.duration_ms = spotify_track.duration_ms
            existing.album_name = album_name
            existing.album_spotify_id = album_spotify_id
            existing.isrc = isrc
            return existing

        track = Track(
            spotify_track_id=spotify_track.id,
            name=spotify_track.name,
            duration_ms=spotify_track.duration_ms,
            album_name=album_name,
            album_spotify_id=album_spotify_id,
            isrc=isrc,
            source=TrackSource.SPOTIFY_API,
        )
        session.add(track)
        await session.flush()
        return track

    async def upsert_artist(
        self,
        spotify_artist: SpotifyArtistSimplified,
        session: AsyncSession,
    ) -> Artist:
        """Insert or update an artist from a Spotify API response.

        Matches by spotify_artist_id. Updates name on match.
        """
        if not spotify_artist.id:
            result = await session.execute(select(Artist).where(Artist.name == spotify_artist.name).limit(1))
            existing = result.scalar_one_or_none()
            if existing:
                return existing
            artist = Artist(
                name=spotify_artist.name,
                source=TrackSource.SPOTIFY_API,
            )
            session.add(artist)
            await session.flush()
            return artist

        result = await session.execute(select(Artist).where(Artist.spotify_artist_id == spotify_artist.id))
        existing = result.scalar_one_or_none()

        if existing:
            existing.name = spotify_artist.name
            return existing

        artist = Artist(
            spotify_artist_id=spotify_artist.id,
            name=spotify_artist.name,
            source=TrackSource.SPOTIFY_API,
        )
        session.add(artist)
        await session.flush()
        return artist

    async def link_track_artists(
        self,
        track_id: int,
        artist_ids: list[int],
        session: AsyncSession,
    ) -> None:
        """Ensure TrackArtist links exist for the given track and artist IDs."""
        for position, artist_id in enumerate(artist_ids):
            result = await session.execute(
                select(TrackArtist).where(
                    TrackArtist.track_id == track_id,
                    TrackArtist.artist_id == artist_id,
                )
            )
            existing = result.scalar_one_or_none()
            if not existing:
                session.add(
                    TrackArtist(
                        track_id=track_id,
                        artist_id=artist_id,
                        position=position,
                    )
                )
        await session.flush()

    async def insert_play(
        self,
        user_id: int,
        track_id: int,
        played_at: datetime,
        context_type: str | None = None,
        context_uri: str | None = None,
        *,
        session: AsyncSession,
    ) -> Play | None:
        """Insert a play record, returning None if it already exists (dedup)."""
        # Check for existing play (dedup by unique constraint)
        result = await session.execute(
            select(Play).where(
                Play.user_id == user_id,
                Play.played_at == played_at,
                Play.track_id == track_id,
            )
        )
        if result.scalar_one_or_none():
            return None

        play = Play(
            user_id=user_id,
            track_id=track_id,
            played_at=played_at,
            context_type=context_type,
            context_uri=context_uri,
            source=TrackSource.SPOTIFY_API,
        )
        session.add(play)
        await session.flush()
        return play

    async def process_play_history_item(
        self,
        item: SpotifyPlayHistoryItem,
        user_id: int,
        session: AsyncSession,
    ) -> Play | None:
        """Process a single play history item: upsert track + artists, insert play.

        Returns the Play record if inserted, None if it was a duplicate.
        """
        # 1. Upsert track
        db_track = await self.upsert_track(item.track, session)

        # 2. Upsert each artist
        artist_ids: list[int] = []
        for spotify_artist in item.track.artists:
            db_artist = await self.upsert_artist(spotify_artist, session)
            artist_ids.append(db_artist.id)

        # 3. Link track <-> artists
        if artist_ids:
            await self.link_track_artists(db_track.id, artist_ids, session)

        # 4. Insert play
        context_type = item.context.type if item.context else None
        context_uri = item.context.uri if item.context else None

        return await self.insert_play(
            user_id=user_id,
            track_id=db_track.id,
            played_at=item.played_at,
            context_type=context_type,
            context_uri=context_uri,
            session=session,
        )

    async def batch_process_play_history(
        self,
        items: list[SpotifyPlayHistoryItem],
        user_id: int,
        session: AsyncSession,
    ) -> tuple[int, int]:
        """Process a batch of play history items.

        Returns (inserted_count, skipped_count).
        """
        inserted = 0
        skipped = 0
        for item in items:
            play = await self.process_play_history_item(item, user_id, session)
            if play is not None:
                inserted += 1
            else:
                skipped += 1
        return inserted, skipped
