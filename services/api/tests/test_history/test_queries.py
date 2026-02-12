"""Tests for history query builders."""

from collections.abc import AsyncGenerator
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.history.queries import (
    query_coverage,
    query_heatmap,
    query_play_stats,
    query_top_artists,
    query_top_tracks,
)
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
async def seeded_session(async_session: AsyncSession) -> tuple[AsyncSession, int]:
    """Create a user, two artists, two tracks, link them, and insert plays."""
    user = User(spotify_user_id="quser", display_name="Q")
    async_session.add(user)
    await async_session.flush()

    artist_a = Artist(name="Artist A", source=TrackSource.SPOTIFY_API)
    artist_b = Artist(name="Artist B", source=TrackSource.IMPORT_ZIP)
    async_session.add_all([artist_a, artist_b])
    await async_session.flush()

    track_x = Track(name="Track X", spotify_track_id="TX", source=TrackSource.SPOTIFY_API)
    track_y = Track(name="Track Y", local_track_id="local:TY", source=TrackSource.IMPORT_ZIP)
    async_session.add_all([track_x, track_y])
    await async_session.flush()

    async_session.add_all(
        [
            TrackArtist(track_id=track_x.id, artist_id=artist_a.id, position=0),
            TrackArtist(track_id=track_y.id, artist_id=artist_b.id, position=0),
        ]
    )
    await async_session.flush()

    # Plays: 3 for Track X, 2 for Track Y — all recent
    plays = [
        Play(
            user_id=user.id,
            track_id=track_x.id,
            played_at=datetime(2026, 1, 10, 10, 0),
            ms_played=200000,
            source=TrackSource.SPOTIFY_API,
        ),
        Play(
            user_id=user.id,
            track_id=track_x.id,
            played_at=datetime(2026, 1, 11, 14, 30),
            ms_played=210000,
            source=TrackSource.SPOTIFY_API,
        ),
        Play(
            user_id=user.id,
            track_id=track_x.id,
            played_at=datetime(2026, 1, 12, 22, 0),
            ms_played=190000,
            source=TrackSource.SPOTIFY_API,
        ),
        Play(
            user_id=user.id,
            track_id=track_y.id,
            played_at=datetime(2026, 1, 13, 8, 0),
            ms_played=180000,
            source=TrackSource.IMPORT_ZIP,
        ),
        Play(
            user_id=user.id,
            track_id=track_y.id,
            played_at=datetime(2026, 1, 14, 8, 0),
            ms_played=185000,
            source=TrackSource.IMPORT_ZIP,
        ),
    ]
    async_session.add_all(plays)
    await async_session.flush()

    return async_session, user.id


async def test_query_top_artists(seeded_session: tuple[AsyncSession, int]) -> None:
    session, user_id = seeded_session
    rows = await query_top_artists(user_id, session, days=3650, limit=10)
    assert len(rows) == 2
    assert rows[0]["artist_name"] == "Artist A"
    assert rows[0]["play_count"] == 3
    assert rows[1]["artist_name"] == "Artist B"
    assert rows[1]["play_count"] == 2


async def test_query_top_tracks(seeded_session: tuple[AsyncSession, int]) -> None:
    session, user_id = seeded_session
    rows = await query_top_tracks(user_id, session, days=3650, limit=10)
    assert len(rows) == 2
    assert rows[0]["track_name"] == "Track X"
    assert rows[0]["play_count"] == 3
    assert rows[0]["artist_name"] == "Artist A"


async def test_query_play_stats(seeded_session: tuple[AsyncSession, int]) -> None:
    session, user_id = seeded_session
    stats = await query_play_stats(user_id, session, days=3650)
    assert stats["total_plays"] == 5
    assert stats["unique_tracks"] == 2
    assert stats["unique_artists"] == 2
    assert stats["total_ms_played"] == 200000 + 210000 + 190000 + 180000 + 185000


async def test_query_heatmap(seeded_session: tuple[AsyncSession, int]) -> None:
    session, user_id = seeded_session
    cells = await query_heatmap(user_id, session, days=3650)
    assert len(cells) > 0
    total = sum(c["play_count"] for c in cells)
    assert total == 5
    # All weekday values should be 0-6
    for c in cells:
        assert 0 <= c["weekday"] <= 6
        assert 0 <= c["hour"] <= 23


async def test_query_coverage(seeded_session: tuple[AsyncSession, int]) -> None:
    session, user_id = seeded_session
    cov = await query_coverage(user_id, session, days=3650)
    assert cov["total_plays"] == 5
    assert cov["api_source_count"] == 3
    assert cov["import_source_count"] == 2
    assert cov["active_days"] == 5  # 5 different dates
    assert cov["earliest_play"] is not None
    assert cov["latest_play"] is not None


async def test_query_top_artists_cutoff(seeded_session: tuple[AsyncSession, int]) -> None:
    """Plays outside the date window are excluded."""
    session, user_id = seeded_session
    # All seeded plays are from Jan 2026; querying with days=1 from "now" (Feb 2026)
    # means the cutoff is ~Feb 10, so all Jan plays should be excluded.
    rows = await query_top_artists(user_id, session, days=1, limit=10)
    assert rows == []


async def test_query_play_stats_cutoff(seeded_session: tuple[AsyncSession, int]) -> None:
    """Play stats respect the date window."""
    session, user_id = seeded_session
    stats = await query_play_stats(user_id, session, days=1)
    assert stats["total_plays"] == 0
    assert stats["unique_tracks"] == 0


async def test_query_top_artists_empty(async_session: AsyncSession) -> None:
    """No plays → empty result."""
    rows = await query_top_artists(999, async_session, days=90, limit=10)
    assert rows == []


async def test_query_play_stats_empty(async_session: AsyncSession) -> None:
    stats = await query_play_stats(999, async_session, days=90)
    assert stats["total_plays"] == 0
    assert stats["unique_tracks"] == 0
