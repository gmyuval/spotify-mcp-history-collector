"""Tests for MusicRepository."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shared.db.base import Base
from shared.db.models.music import Artist, Track, TrackArtist
from shared.db.models.user import User
from shared.db.operations import MusicRepository
from shared.spotify.models import (
    SpotifyAlbumSimplified,
    SpotifyArtistSimplified,
    SpotifyContext,
    SpotifyExternalIds,
    SpotifyPlayHistoryItem,
    SpotifyTrack,
)


@pytest.fixture
async def async_engine():  # type: ignore[no-untyped-def]
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def async_session(async_engine):  # type: ignore[no-untyped-def]
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest.fixture
async def test_user(async_session: AsyncSession) -> User:
    user = User(spotify_user_id="testuser", display_name="Test User")
    async_session.add(user)
    await async_session.flush()
    return user


def _spotify_track(
    track_id: str = "t1",
    name: str = "Test Track",
    artist_id: str = "a1",
    artist_name: str = "Test Artist",
) -> SpotifyTrack:
    return SpotifyTrack(
        id=track_id,
        name=name,
        duration_ms=200000,
        artists=[SpotifyArtistSimplified(id=artist_id, name=artist_name)],
        album=SpotifyAlbumSimplified(id="album1", name="Test Album"),
        external_ids=SpotifyExternalIds(isrc="USRC17607839"),
    )


class TestUpsertTrack:
    async def test_insert_new_track(self, async_session: AsyncSession) -> None:
        """New track gets inserted."""
        repo = MusicRepository()
        track = _spotify_track()
        db_track = await repo.upsert_track(track, async_session)
        assert db_track.id is not None
        assert db_track.spotify_track_id == "t1"
        assert db_track.name == "Test Track"
        assert db_track.album_name == "Test Album"
        assert db_track.isrc == "USRC17607839"

    async def test_update_existing_track(self, async_session: AsyncSession) -> None:
        """Existing track gets updated on re-upsert."""
        repo = MusicRepository()
        track = _spotify_track()
        db_track = await repo.upsert_track(track, async_session)
        original_id = db_track.id

        updated_track = _spotify_track(name="Updated Track Name")
        db_track2 = await repo.upsert_track(updated_track, async_session)
        assert db_track2.id == original_id
        assert db_track2.name == "Updated Track Name"

    async def test_track_without_spotify_id(self, async_session: AsyncSession) -> None:
        """Track without Spotify ID gets created by name."""
        repo = MusicRepository()
        track = SpotifyTrack(id=None, name="Local Track", duration_ms=180000)
        db_track = await repo.upsert_track(track, async_session)
        assert db_track.id is not None
        assert db_track.spotify_track_id is None
        assert db_track.name == "Local Track"


class TestUpsertArtist:
    async def test_insert_new_artist(self, async_session: AsyncSession) -> None:
        """New artist gets inserted."""
        repo = MusicRepository()
        artist = SpotifyArtistSimplified(id="a1", name="Test Artist")
        db_artist = await repo.upsert_artist(artist, async_session)
        assert db_artist.id is not None
        assert db_artist.spotify_artist_id == "a1"
        assert db_artist.name == "Test Artist"

    async def test_update_existing_artist(self, async_session: AsyncSession) -> None:
        """Existing artist gets name updated."""
        repo = MusicRepository()
        artist = SpotifyArtistSimplified(id="a1", name="Original Name")
        db_artist = await repo.upsert_artist(artist, async_session)
        original_id = db_artist.id

        updated = SpotifyArtistSimplified(id="a1", name="New Name")
        db_artist2 = await repo.upsert_artist(updated, async_session)
        assert db_artist2.id == original_id
        assert db_artist2.name == "New Name"


class TestLinkTrackArtists:
    async def test_creates_links(self, async_session: AsyncSession) -> None:
        """Track-artist links are created with positions."""
        repo = MusicRepository()
        track = _spotify_track()
        db_track = await repo.upsert_track(track, async_session)
        artist = SpotifyArtistSimplified(id="a1", name="Artist 1")
        db_artist = await repo.upsert_artist(artist, async_session)

        await repo.link_track_artists(db_track.id, [db_artist.id], async_session)

        from sqlalchemy import select

        result = await async_session.execute(select(TrackArtist).where(TrackArtist.track_id == db_track.id))
        links = result.scalars().all()
        assert len(links) == 1
        assert links[0].position == 0

    async def test_no_duplicate_links(self, async_session: AsyncSession) -> None:
        """Calling link_track_artists twice doesn't create duplicates."""
        repo = MusicRepository()
        track = _spotify_track()
        db_track = await repo.upsert_track(track, async_session)
        artist = SpotifyArtistSimplified(id="a1", name="Artist 1")
        db_artist = await repo.upsert_artist(artist, async_session)

        await repo.link_track_artists(db_track.id, [db_artist.id], async_session)
        await repo.link_track_artists(db_track.id, [db_artist.id], async_session)

        from sqlalchemy import select

        result = await async_session.execute(select(TrackArtist).where(TrackArtist.track_id == db_track.id))
        links = result.scalars().all()
        assert len(links) == 1


class TestInsertPlay:
    async def test_insert_play(self, async_session: AsyncSession, test_user: User) -> None:
        """Play gets inserted."""
        repo = MusicRepository()
        track = _spotify_track()
        db_track = await repo.upsert_track(track, async_session)

        played_at = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
        play = await repo.insert_play(
            user_id=test_user.id,
            track_id=db_track.id,
            played_at=played_at,
            context_type="playlist",
            context_uri="spotify:playlist:p1",
            session=async_session,
        )
        assert play is not None
        assert play.user_id == test_user.id
        assert play.track_id == db_track.id

    async def test_duplicate_play_returns_none(self, async_session: AsyncSession, test_user: User) -> None:
        """Duplicate play (same user, track, played_at) returns None."""
        repo = MusicRepository()
        track = _spotify_track()
        db_track = await repo.upsert_track(track, async_session)

        played_at = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
        play1 = await repo.insert_play(
            user_id=test_user.id, track_id=db_track.id, played_at=played_at, session=async_session
        )
        play2 = await repo.insert_play(
            user_id=test_user.id, track_id=db_track.id, played_at=played_at, session=async_session
        )
        assert play1 is not None
        assert play2 is None


class TestBatchProcessPlayHistory:
    async def test_batch_process(self, async_session: AsyncSession, test_user: User) -> None:
        """batch_process_play_history inserts new plays and skips duplicates."""
        repo = MusicRepository()
        items = [
            SpotifyPlayHistoryItem(
                track=_spotify_track("t1", "Track 1", "a1", "Artist 1"),
                played_at=datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC),
                context=SpotifyContext(type="playlist", uri="spotify:playlist:p1"),
            ),
            SpotifyPlayHistoryItem(
                track=_spotify_track("t2", "Track 2", "a2", "Artist 2"),
                played_at=datetime(2024, 1, 15, 10, 25, 0, tzinfo=UTC),
            ),
        ]

        inserted, skipped = await repo.batch_process_play_history(items, test_user.id, async_session)
        assert inserted == 2
        assert skipped == 0

        # Second call — same items should be skipped
        inserted2, skipped2 = await repo.batch_process_play_history(items, test_user.id, async_session)
        assert inserted2 == 0
        assert skipped2 == 2

    async def test_process_play_history_item(self, async_session: AsyncSession, test_user: User) -> None:
        """process_play_history_item creates track, artists, links, and play."""
        repo = MusicRepository()
        item = SpotifyPlayHistoryItem(
            track=SpotifyTrack(
                id="t1",
                name="Test Track",
                artists=[
                    SpotifyArtistSimplified(id="a1", name="Artist A"),
                    SpotifyArtistSimplified(id="a2", name="Artist B"),
                ],
                album=SpotifyAlbumSimplified(id="album1", name="Album"),
            ),
            played_at=datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC),
        )

        play = await repo.process_play_history_item(item, test_user.id, async_session)
        assert play is not None

        # Verify track exists
        from sqlalchemy import select

        result = await async_session.execute(select(Track).where(Track.spotify_track_id == "t1"))
        assert result.scalar_one_or_none() is not None

        # Verify artists exist
        result = await async_session.execute(select(Artist).where(Artist.spotify_artist_id == "a1"))
        assert result.scalar_one_or_none() is not None
        result = await async_session.execute(select(Artist).where(Artist.spotify_artist_id == "a2"))
        assert result.scalar_one_or_none() is not None

        # Verify track-artist links
        result = await async_session.execute(select(TrackArtist))
        links = result.scalars().all()
        assert len(links) == 2
