"""Tests for HistoryService."""

from collections.abc import AsyncGenerator
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.history.service import HistoryService
from shared.db.base import Base
from shared.db.enums import TrackSource
from shared.db.models.music import Artist, Play, Track, TrackArtist
from shared.db.models.user import User


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
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
async def seeded_session(async_session: AsyncSession) -> AsyncSession:
    user = User(spotify_user_id="svcuser", display_name="Svc")
    async_session.add(user)
    await async_session.flush()

    artist = Artist(name="Test Artist", source=TrackSource.SPOTIFY_API)
    async_session.add(artist)
    await async_session.flush()

    track = Track(name="Test Track", spotify_track_id="T1", source=TrackSource.SPOTIFY_API, duration_ms=240000)
    async_session.add(track)
    await async_session.flush()

    async_session.add(TrackArtist(track_id=track.id, artist_id=artist.id, position=0))
    await async_session.flush()

    for day in range(1, 6):
        async_session.add(
            Play(
                user_id=user.id,
                track_id=track.id,
                played_at=datetime(2026, 1, day, 12, 0),
                ms_played=240000,
                source=TrackSource.SPOTIFY_API,
            )
        )
    await async_session.flush()
    return async_session


async def test_get_top_artists(seeded_session: AsyncSession) -> None:
    svc = HistoryService()
    result = await svc.get_top_artists(1, seeded_session, days=3650)
    assert len(result) == 1
    assert result[0].artist_name == "Test Artist"
    assert result[0].play_count == 5


async def test_get_top_tracks(seeded_session: AsyncSession) -> None:
    svc = HistoryService()
    result = await svc.get_top_tracks(1, seeded_session, days=3650)
    assert len(result) == 1
    assert result[0].track_name == "Test Track"
    assert result[0].play_count == 5


async def test_get_listening_heatmap(seeded_session: AsyncSession) -> None:
    svc = HistoryService()
    heatmap = await svc.get_listening_heatmap(1, seeded_session, days=3650)
    assert heatmap.total_plays == 5
    assert len(heatmap.cells) > 0


async def test_get_repeat_rate(seeded_session: AsyncSession) -> None:
    svc = HistoryService()
    stats = await svc.get_repeat_rate(1, seeded_session, days=3650)
    assert stats.total_plays == 5
    assert stats.unique_tracks == 1
    assert stats.repeat_rate == 5.0


async def test_get_coverage(seeded_session: AsyncSession) -> None:
    svc = HistoryService()
    cov = await svc.get_coverage(1, seeded_session, days=3650)
    assert cov.total_plays == 5
    assert cov.api_source_count == 5
    assert cov.import_source_count == 0
    assert cov.active_days == 5


async def test_get_taste_summary(seeded_session: AsyncSession) -> None:
    svc = HistoryService()
    summary = await svc.get_taste_summary(1, seeded_session, days=3650)
    assert summary.total_plays == 5
    assert summary.unique_tracks == 1
    assert summary.unique_artists == 1
    assert summary.listening_hours > 0
    assert summary.repeat_rate == 5.0
    assert len(summary.top_artists) == 1
    assert len(summary.top_tracks) == 1
    assert summary.coverage.total_plays == 5


async def test_taste_summary_empty(async_session: AsyncSession) -> None:
    svc = HistoryService()
    summary = await svc.get_taste_summary(999, async_session, days=90)
    assert summary.total_plays == 0
    assert summary.repeat_rate == 0.0
    assert summary.peak_weekday is None
    assert summary.peak_hour is None
