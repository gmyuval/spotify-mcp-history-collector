"""Tests for SpotifyCacheService."""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.cache.service import SpotifyCacheService
from shared.db.base import Base
from shared.db.models.cache import SpotifyEntityCache
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
async def session(async_engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess
        await sess.commit()


@pytest.fixture
async def user_id(session: AsyncSession) -> int:
    user = User(spotify_user_id="cacheuser", display_name="Cache Test")
    session.add(user)
    await session.flush()
    return user.id


# ------------------------------------------------------------------
# Entity cache tests
# ------------------------------------------------------------------


class TestEntityCache:
    """Tests for track/artist/album TTL-based entity caching."""

    async def test_get_entity_cache_miss(self, session: AsyncSession) -> None:
        cache = SpotifyCacheService(cache_ttl_hours=24)
        result = await cache.get_entity("track", "nonexistent", session)
        assert result is None

    async def test_put_and_get_entity(self, session: AsyncSession) -> None:
        cache = SpotifyCacheService(cache_ttl_hours=24)
        data = {"id": "t1", "name": "Test Track", "artists": [{"id": "a1", "name": "Artist"}]}

        await cache.put_entity("track", "t1", data, session)
        result = await cache.get_entity("track", "t1", session)

        assert result is not None
        assert result["id"] == "t1"
        assert result["name"] == "Test Track"

    async def test_entity_cache_ttl_expired(self, session: AsyncSession) -> None:
        cache = SpotifyCacheService(cache_ttl_hours=1)

        # Insert an entity with a fetched_at in the past
        entry = SpotifyEntityCache(
            entity_type="track",
            spotify_id="old_track",
            data_json='{"id": "old_track", "name": "Old"}',
            fetched_at=datetime.now(UTC) - timedelta(hours=2),
        )
        session.add(entry)
        await session.flush()

        result = await cache.get_entity("track", "old_track", session)
        assert result is None  # Expired

    async def test_entity_cache_ttl_not_expired(self, session: AsyncSession) -> None:
        cache = SpotifyCacheService(cache_ttl_hours=24)

        entry = SpotifyEntityCache(
            entity_type="artist",
            spotify_id="fresh_artist",
            data_json='{"id": "fresh_artist", "name": "Fresh"}',
            fetched_at=datetime.now(UTC) - timedelta(hours=1),
        )
        session.add(entry)
        await session.flush()

        result = await cache.get_entity("artist", "fresh_artist", session)
        assert result is not None
        assert result["name"] == "Fresh"

    async def test_put_entity_upserts(self, session: AsyncSession) -> None:
        cache = SpotifyCacheService(cache_ttl_hours=24)

        await cache.put_entity("track", "t1", {"name": "v1"}, session)
        await cache.put_entity("track", "t1", {"name": "v2"}, session)

        result = await cache.get_entity("track", "t1", session)
        assert result is not None
        assert result["name"] == "v2"

    async def test_different_entity_types_are_independent(self, session: AsyncSession) -> None:
        cache = SpotifyCacheService(cache_ttl_hours=24)

        await cache.put_entity("track", "x1", {"type": "track"}, session)
        await cache.put_entity("artist", "x1", {"type": "artist"}, session)

        track = await cache.get_entity("track", "x1", session)
        artist = await cache.get_entity("artist", "x1", session)

        assert track is not None
        assert track["type"] == "track"
        assert artist is not None
        assert artist["type"] == "artist"


# ------------------------------------------------------------------
# Playlist cache tests
# ------------------------------------------------------------------


class TestPlaylistCache:
    """Tests for playlist caching with snapshot_id invalidation."""

    async def test_get_cached_playlists_empty(self, session: AsyncSession, user_id: int) -> None:
        cache = SpotifyCacheService(cache_ttl_hours=24)
        result = await cache.get_cached_playlists(user_id, session)
        assert result is None

    async def test_put_and_get_playlist_list(self, session: AsyncSession, user_id: int) -> None:
        cache = SpotifyCacheService(cache_ttl_hours=24)
        playlists = [
            {"id": "pl1", "name": "Rock", "public": True, "tracks_total": 10, "owner": "Me", "snapshot_id": "snap1"},
            {"id": "pl2", "name": "Jazz", "public": False, "tracks_total": 5, "owner": "Me", "snapshot_id": "snap2"},
        ]

        await cache.put_playlist_list(user_id, playlists, session)
        result = await cache.get_cached_playlists(user_id, session)

        assert result is not None
        assert len(result) == 2
        names = {p["name"] for p in result}
        assert names == {"Rock", "Jazz"}

    async def test_get_cached_playlist_snapshot_ids(self, session: AsyncSession, user_id: int) -> None:
        cache = SpotifyCacheService(cache_ttl_hours=24)
        playlists = [
            {"id": "pl1", "name": "A", "snapshot_id": "snap_a"},
            {"id": "pl2", "name": "B", "snapshot_id": "snap_b"},
        ]
        await cache.put_playlist_list(user_id, playlists, session)

        snapshots = await cache.get_cached_playlist_snapshot_ids(user_id, session)
        assert snapshots == {"pl1": "snap_a", "pl2": "snap_b"}

    async def test_put_playlist_with_tracks(self, session: AsyncSession, user_id: int) -> None:
        cache = SpotifyCacheService(cache_ttl_hours=24)
        playlist_data = {
            "id": "pl1",
            "name": "My Playlist",
            "description": "Test",
            "public": True,
            "owner": "TestUser",
            "tracks_total": 2,
            "snapshot_id": "snap1",
            "external_urls": {"spotify": "https://open.spotify.com/playlist/pl1"},
        }
        tracks_data = [
            {"id": "t1", "name": "Track 1", "artists": [{"id": "a1", "name": "Art1"}], "added_at": "2026-01-01"},
            {"id": "t2", "name": "Track 2", "artists": [{"id": "a2", "name": "Art2"}], "added_at": "2026-01-02"},
        ]

        await cache.put_playlist(user_id, playlist_data, tracks_data, session)
        result = await cache.get_cached_playlist(user_id, "pl1", session)

        assert result is not None
        assert result["name"] == "My Playlist"
        assert result["snapshot_id"] == "snap1"
        assert len(result["tracks"]) == 2
        assert result["tracks"][0]["name"] == "Track 1"
        assert result["tracks"][1]["name"] == "Track 2"

    async def test_put_playlist_upserts(self, session: AsyncSession, user_id: int) -> None:
        cache = SpotifyCacheService(cache_ttl_hours=24)

        # First insert
        await cache.put_playlist(
            user_id,
            {"id": "pl1", "name": "v1", "snapshot_id": "s1", "external_urls": {}},
            [{"id": "t1", "name": "T1", "artists": []}],
            session,
        )

        # Upsert with new data
        await cache.put_playlist(
            user_id,
            {"id": "pl1", "name": "v2", "snapshot_id": "s2", "external_urls": {}},
            [{"id": "t2", "name": "T2", "artists": []}, {"id": "t3", "name": "T3", "artists": []}],
            session,
        )

        result = await cache.get_cached_playlist(user_id, "pl1", session)
        assert result is not None
        assert result["name"] == "v2"
        assert result["snapshot_id"] == "s2"
        assert len(result["tracks"]) == 2

    async def test_invalidate_playlist(self, session: AsyncSession, user_id: int) -> None:
        cache = SpotifyCacheService(cache_ttl_hours=24)
        await cache.put_playlist(
            user_id,
            {"id": "pl1", "name": "Test", "snapshot_id": "s1", "external_urls": {}},
            [],
            session,
        )

        await cache.invalidate_playlist(user_id, "pl1", session)
        result = await cache.get_cached_playlist(user_id, "pl1", session)
        assert result is None

    async def test_invalidate_all_playlists(self, session: AsyncSession, user_id: int) -> None:
        cache = SpotifyCacheService(cache_ttl_hours=24)
        await cache.put_playlist_list(
            user_id,
            [
                {"id": "pl1", "name": "A", "snapshot_id": "s1"},
                {"id": "pl2", "name": "B", "snapshot_id": "s2"},
            ],
            session,
        )

        await cache.invalidate_all_playlists(user_id, session)
        result = await cache.get_cached_playlists(user_id, session)
        assert result is None

    async def test_invalidate_nonexistent_playlist_is_noop(self, session: AsyncSession, user_id: int) -> None:
        cache = SpotifyCacheService(cache_ttl_hours=24)
        # Should not raise
        await cache.invalidate_playlist(user_id, "nonexistent", session)
