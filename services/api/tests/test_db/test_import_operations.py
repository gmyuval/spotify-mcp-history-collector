"""Tests for MusicRepository ZIP import methods."""

from collections.abc import AsyncGenerator
from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from shared.db.base import Base
from shared.db.enums import TrackSource
from shared.db.models.music import Artist, Play, Track
from shared.db.models.user import User
from shared.db.operations import MusicRepository
from shared.zip_import.models import NormalizedPlayRecord


@pytest.fixture
async def async_engine() -> AsyncGenerator[AsyncEngine]:
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def async_session(async_engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest.fixture
async def test_user(async_session: AsyncSession) -> User:
    user = User(spotify_user_id="testuser", display_name="Test User")
    async_session.add(user)
    await async_session.flush()
    return user


def _make_record(
    track_name: str = "Track",
    artist_name: str = "Artist",
    album_name: str | None = "Album",
    ms_played: int = 180000,
    played_at: datetime | None = None,
    spotify_track_uri: str | None = None,
) -> NormalizedPlayRecord:
    return NormalizedPlayRecord(
        track_name=track_name,
        artist_name=artist_name,
        album_name=album_name,
        ms_played=ms_played,
        played_at=played_at or datetime(2023, 6, 15, 10, 30),
        spotify_track_uri=spotify_track_uri,
    )


async def test_upsert_track_from_import_creates_new(async_session: AsyncSession) -> None:
    """Creates a new track with local_track_id."""
    repo = MusicRepository()
    record = _make_record()
    track = await repo.upsert_track_from_import(
        track_name=record.track_name,
        album_name=record.album_name,
        spotify_track_id=record.spotify_track_id,
        local_track_id=record.local_track_id,
        session=async_session,
    )
    assert track.name == "Track"
    assert track.local_track_id == record.local_track_id
    assert track.source == TrackSource.IMPORT_ZIP


async def test_upsert_track_from_import_matches_spotify_id(async_session: AsyncSession) -> None:
    """Matches by spotify_track_id, fills in local_track_id."""
    repo = MusicRepository()
    # Pre-create a track from API
    existing = Track(spotify_track_id="ABC123", name="API Track", source=TrackSource.SPOTIFY_API)
    async_session.add(existing)
    await async_session.flush()

    record = _make_record(spotify_track_uri="spotify:track:ABC123")
    track = await repo.upsert_track_from_import(
        track_name=record.track_name,
        album_name=record.album_name,
        spotify_track_id=record.spotify_track_id,
        local_track_id=record.local_track_id,
        session=async_session,
    )
    assert track.id == existing.id
    assert track.local_track_id == record.local_track_id
    # Name should NOT be overwritten (API data is higher quality)
    assert track.name == "API Track"


async def test_upsert_track_from_import_matches_local_id(async_session: AsyncSession) -> None:
    """Matches by local_track_id, fills in spotify_track_id."""
    repo = MusicRepository()
    record = _make_record()
    existing = Track(local_track_id=record.local_track_id, name="Existing", source=TrackSource.IMPORT_ZIP)
    async_session.add(existing)
    await async_session.flush()

    record_with_uri = _make_record(spotify_track_uri="spotify:track:NEW123")
    track = await repo.upsert_track_from_import(
        track_name=record_with_uri.track_name,
        album_name=record_with_uri.album_name,
        spotify_track_id=record_with_uri.spotify_track_id,
        local_track_id=record_with_uri.local_track_id,
        session=async_session,
    )
    assert track.id == existing.id
    assert track.spotify_track_id == "NEW123"


async def test_upsert_artist_from_import_creates_new(async_session: AsyncSession) -> None:
    """Creates a new artist with local_artist_id."""
    repo = MusicRepository()
    record = _make_record()
    artist = await repo.upsert_artist_from_import(
        artist_name=record.artist_name,
        local_artist_id=record.local_artist_id,
        session=async_session,
    )
    assert artist.name == "Artist"
    assert artist.local_artist_id == record.local_artist_id
    assert artist.source == TrackSource.IMPORT_ZIP


async def test_upsert_artist_from_import_matches_by_name(async_session: AsyncSession) -> None:
    """Matches existing artist by name, fills in local_artist_id."""
    repo = MusicRepository()
    existing = Artist(name="Artist", source=TrackSource.SPOTIFY_API)
    async_session.add(existing)
    await async_session.flush()

    record = _make_record()
    artist = await repo.upsert_artist_from_import(
        artist_name=record.artist_name,
        local_artist_id=record.local_artist_id,
        session=async_session,
    )
    assert artist.id == existing.id
    assert artist.local_artist_id == record.local_artist_id


async def test_insert_play_from_import(async_session: AsyncSession, test_user: User) -> None:
    """Inserts a play with ms_played and IMPORT_ZIP source."""
    repo = MusicRepository()
    track = Track(name="Track", local_track_id="local:abc", source=TrackSource.IMPORT_ZIP)
    async_session.add(track)
    await async_session.flush()

    play = await repo.insert_play_from_import(
        user_id=test_user.id,
        track_id=track.id,
        played_at=datetime(2023, 6, 15, 10, 30),
        ms_played=180000,
        session=async_session,
    )
    assert play is not None
    assert play.ms_played == 180000
    assert play.source == TrackSource.IMPORT_ZIP


async def test_insert_play_from_import_dedup(async_session: AsyncSession, test_user: User) -> None:
    """Duplicate play returns None."""
    repo = MusicRepository()
    track = Track(name="Track", local_track_id="local:abc", source=TrackSource.IMPORT_ZIP)
    async_session.add(track)
    await async_session.flush()

    played_at = datetime(2023, 6, 15, 10, 30)
    first = await repo.insert_play_from_import(
        user_id=test_user.id, track_id=track.id, played_at=played_at, ms_played=180000, session=async_session
    )
    second = await repo.insert_play_from_import(
        user_id=test_user.id, track_id=track.id, played_at=played_at, ms_played=180000, session=async_session
    )
    assert first is not None
    assert second is None


async def test_batch_process_import_records(async_session: AsyncSession, test_user: User) -> None:
    """Batch processes records, returns correct counts."""
    repo = MusicRepository()
    records = [
        _make_record(track_name="Track A", artist_name="Artist A", played_at=datetime(2023, 6, 15, 10, 0)),
        _make_record(track_name="Track B", artist_name="Artist B", played_at=datetime(2023, 6, 15, 11, 0)),
        _make_record(track_name="Track A", artist_name="Artist A", played_at=datetime(2023, 6, 15, 10, 0)),  # dupe
    ]
    inserted, skipped = await repo.batch_process_import_records(records, test_user.id, async_session)
    assert inserted == 2
    assert skipped == 1

    result = await async_session.execute(select(Play).where(Play.user_id == test_user.id))
    assert len(result.scalars().all()) == 2
