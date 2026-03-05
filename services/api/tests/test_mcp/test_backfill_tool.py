"""Tests for memory.backfill_playlist MCP tool."""

from collections.abc import AsyncGenerator, Generator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.dependencies import db_manager
from app.main import app
from app.settings import AppSettings, get_settings
from shared.db.base import Base
from shared.db.models.user import User

TEST_FERNET_KEY = Fernet.generate_key().decode()


def _test_settings() -> AppSettings:
    return AppSettings(
        SPOTIFY_CLIENT_ID="test",
        SPOTIFY_CLIENT_SECRET="test",
        TOKEN_ENCRYPTION_KEY=TEST_FERNET_KEY,
        RATE_LIMIT_MCP_PER_MINUTE=10000,
    )


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
def override_deps(async_engine: AsyncEngine) -> Generator[None]:
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async def _override() -> AsyncGenerator[AsyncSession]:
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[db_manager.dependency] = _override
    app.dependency_overrides[get_settings] = _test_settings
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client(override_deps: None) -> TestClient:
    return TestClient(app)


@pytest.fixture
async def seeded_user(async_engine: AsyncEngine) -> int:
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        user = User(spotify_user_id="backfill_user", display_name="Backfill User")
        session.add(user)
        await session.flush()
        uid = user.id
        await session.commit()
    return uid


@pytest.fixture
async def second_user(async_engine: AsyncEngine) -> int:
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        user = User(spotify_user_id="backfill_user_2", display_name="Backfill User 2")
        session.add(user)
        await session.flush()
        uid = user.id
        await session.commit()
    return uid


def _call(client: TestClient, tool: str, **kwargs: object) -> dict[str, Any]:
    resp = client.post("/mcp/call", json={"tool": tool, **kwargs})
    assert resp.status_code == 200
    return resp.json()  # type: ignore[no-any-return]


def _mock_get_playlist_result(
    playlist_id: str = "pl_backfill",
    name: str = "Test Playlist",
    tracks_source: str = "api",
    track_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build a fake result dict matching what spotify.get_playlist returns."""
    if track_ids is None:
        track_ids = ["t1", "t2", "t3"]
    return {
        "id": playlist_id,
        "name": name,
        "description": "A test playlist",
        "public": True,
        "owner": "Test User",
        "tracks_total": len(track_ids),
        "tracks": [{"id": tid, "name": f"Track {tid}", "artists": [{"name": "Artist"}]} for tid in track_ids],
        "tracks_source": tracks_source,
        "snapshot_id": "snap_test",
        "external_urls": {},
    }


class TestBackfillPlaylist:
    def test_backfill_success(self, client: TestClient, seeded_user: int) -> None:
        """Backfill creates a memory playlist with tracks from Spotify."""
        mock_result = _mock_get_playlist_result()

        with patch(
            "app.mcp.tools.playlist_tools.PlaylistToolHandlers.get_playlist",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            data = _call(
                client,
                "memory.backfill_playlist",
                user_id=seeded_user,
                playlist_id="pl_backfill",
                intent_tags=["rock", "classic"],
            )

        assert data["success"] is True
        result = data["result"]
        assert result["playlist_id"] == "pl_backfill"
        assert result["name"] == "Test Playlist"
        assert result["stored_track_count"] == 3
        assert result["tracks_source"] == "api"
        assert result["already_existed"] is False

    def test_backfill_idempotent(self, client: TestClient, seeded_user: int) -> None:
        """Calling backfill twice for the same playlist returns existing record."""
        mock_result = _mock_get_playlist_result()

        with patch(
            "app.mcp.tools.playlist_tools.PlaylistToolHandlers.get_playlist",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            # First call
            data1 = _call(
                client,
                "memory.backfill_playlist",
                user_id=seeded_user,
                playlist_id="pl_idem",
            )
            assert data1["success"] is True
            assert data1["result"]["already_existed"] is False

            # Second call — same playlist_id
            data2 = _call(
                client,
                "memory.backfill_playlist",
                user_id=seeded_user,
                playlist_id="pl_idem",
            )
            assert data2["success"] is True
            assert data2["result"]["already_existed"] is True
            assert data2["result"]["stored_track_count"] == 3

    def test_backfill_embed_source(self, client: TestClient, seeded_user: int) -> None:
        """Backfill reports tracks_source='embed' when tracks come from embed fallback."""
        mock_result = _mock_get_playlist_result(
            playlist_id="pl_embed_bf",
            tracks_source="embed",
        )

        with patch(
            "app.mcp.tools.playlist_tools.PlaylistToolHandlers.get_playlist",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            data = _call(
                client,
                "memory.backfill_playlist",
                user_id=seeded_user,
                playlist_id="pl_embed_bf",
            )

        assert data["success"] is True
        assert data["result"]["tracks_source"] == "embed"

    def test_backfill_empty_playlist(self, client: TestClient, seeded_user: int) -> None:
        """Backfill works for a playlist with zero tracks."""
        mock_result = _mock_get_playlist_result(
            playlist_id="pl_empty",
            track_ids=[],
        )

        with patch(
            "app.mcp.tools.playlist_tools.PlaylistToolHandlers.get_playlist",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            data = _call(
                client,
                "memory.backfill_playlist",
                user_id=seeded_user,
                playlist_id="pl_empty",
            )

        assert data["success"] is True
        assert data["result"]["stored_track_count"] == 0

    def test_backfill_invalid_user_id(self, client: TestClient) -> None:
        """Backfill rejects non-integer user_id."""
        data = _call(
            client,
            "memory.backfill_playlist",
            user_id="not_an_int",
            playlist_id="pl_test",
        )
        assert data["success"] is False

    def test_backfill_idempotency_key(self, client: TestClient, seeded_user: int) -> None:
        """Idempotency key prevents duplicate backfills."""
        mock_result = _mock_get_playlist_result(playlist_id="pl_key1")

        with patch(
            "app.mcp.tools.playlist_tools.PlaylistToolHandlers.get_playlist",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            data1 = _call(
                client,
                "memory.backfill_playlist",
                user_id=seeded_user,
                playlist_id="pl_key1",
                idempotency_key="key-123",
            )
            assert data1["success"] is True
            assert data1["result"]["already_existed"] is False

        # Second call with different playlist_id but same idempotency_key
        mock_result2 = _mock_get_playlist_result(playlist_id="pl_key2")
        with patch(
            "app.mcp.tools.playlist_tools.PlaylistToolHandlers.get_playlist",
            new_callable=AsyncMock,
            return_value=mock_result2,
        ):
            data2 = _call(
                client,
                "memory.backfill_playlist",
                user_id=seeded_user,
                playlist_id="pl_key2",
                idempotency_key="key-123",
            )
            assert data2["success"] is True
            assert data2["result"]["already_existed"] is True
            assert data2["result"]["playlist_id"] == "pl_key1"  # Returns original


class TestBackfillCrossUserIsolation:
    """Ensure backfill idempotency lookups are scoped per user."""

    def test_idempotency_key_not_leaked_cross_user(
        self, client: TestClient, seeded_user: int, second_user: int
    ) -> None:
        """User B querying with own idempotency_key doesn't see user A's playlist."""
        mock_a = _mock_get_playlist_result(playlist_id="pl_iso_a")

        with patch(
            "app.mcp.tools.playlist_tools.PlaylistToolHandlers.get_playlist",
            new_callable=AsyncMock,
            return_value=mock_a,
        ):
            data_a = _call(
                client,
                "memory.backfill_playlist",
                user_id=seeded_user,
                playlist_id="pl_iso_a",
                idempotency_key="key-user-a",
            )
            assert data_a["success"] is True
            assert data_a["result"]["already_existed"] is False

        # User B re-calls with user A's idempotency_key — should NOT see it
        data_b = _call(
            client,
            "memory.backfill_playlist",
            user_id=second_user,
            playlist_id="pl_iso_a",
            idempotency_key="key-user-a",
        )
        # The idempotency lookup is user-scoped, so it won't match.
        # But the DB has a global unique constraint on idempotency_key,
        # so the insert will fail — this is correct: idempotency keys
        # must be globally unique to prevent cross-user collisions.
        assert data_b["success"] is False


class TestBackfillWithTrackIds:
    """Tests for the manual track_ids override path (private playlist workaround)."""

    def test_track_ids_skips_spotify_fetch(self, client: TestClient, seeded_user: int) -> None:
        """When track_ids is provided, Spotify fetch is skipped and source is 'manual'."""
        with patch(
            "app.mcp.tools.playlist_tools.PlaylistToolHandlers.get_playlist",
            new_callable=AsyncMock,
            side_effect=Exception("should not be called"),
        ):
            # Metadata fetch will also raise — name must be provided explicitly
            data = _call(
                client,
                "memory.backfill_playlist",
                user_id=seeded_user,
                playlist_id="pl_manual",
                track_ids=["spotify:track:aaa", "spotify:track:bbb"],
                name="Private Playlist",
            )

        assert data["success"] is True
        result = data["result"]
        assert result["tracks_source"] == "manual"
        assert result["stored_track_count"] == 2
        assert result["playlist_id"] == "pl_manual"
        assert result["name"] == "Private Playlist"
        assert result["already_existed"] is False

    def test_track_ids_uses_metadata_name_when_available(self, client: TestClient, seeded_user: int) -> None:
        """When metadata fetch succeeds, name comes from Spotify (no name override needed)."""
        mock_result = _mock_get_playlist_result(
            playlist_id="pl_manual_meta",
            name="Fetched Name",
            track_ids=["t1"],  # These tracks should be ignored — manual_track_ids take priority
        )
        with patch(
            "app.mcp.tools.playlist_tools.PlaylistToolHandlers.get_playlist",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            data = _call(
                client,
                "memory.backfill_playlist",
                user_id=seeded_user,
                playlist_id="pl_manual_meta",
                track_ids=["manual_t1", "manual_t2", "manual_t3"],
                # No name override — should come from metadata
            )

        assert data["success"] is True
        result = data["result"]
        assert result["name"] == "Fetched Name"
        assert result["tracks_source"] == "manual"
        assert result["stored_track_count"] == 3  # manual count, not metadata count

    def test_track_ids_requires_name_when_metadata_fails(self, client: TestClient, seeded_user: int) -> None:
        """If metadata fetch fails and no name override, raises an error."""
        with patch(
            "app.mcp.tools.playlist_tools.PlaylistToolHandlers.get_playlist",
            new_callable=AsyncMock,
            side_effect=Exception("403 Forbidden"),
        ):
            data = _call(
                client,
                "memory.backfill_playlist",
                user_id=seeded_user,
                playlist_id="pl_manual_no_name",
                track_ids=["t1"],
                # No name — should fail
            )

        assert data["success"] is False
        assert "name" in data.get("error", "").lower() or "name" in str(data).lower()

    def test_track_ids_invalid_type_returns_error(self, client: TestClient, seeded_user: int) -> None:
        """Passing track_ids as a non-array raises a validation error."""
        data = _call(
            client,
            "memory.backfill_playlist",
            user_id=seeded_user,
            playlist_id="pl_bad_ids",
            track_ids="not-a-list",
            name="Whatever",
        )
        assert data["success"] is False

    def test_track_ids_empty_list_stores_zero_tracks(self, client: TestClient, seeded_user: int) -> None:
        """Passing an empty track_ids list enters the manual path with 0 tracks stored."""
        # [] is not None, so it enters the manual override path.
        # Metadata fetch succeeds, providing the name.
        mock_result = _mock_get_playlist_result(playlist_id="pl_empty_ids", track_ids=["t1"])
        with patch(
            "app.mcp.tools.playlist_tools.PlaylistToolHandlers.get_playlist",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            data = _call(
                client,
                "memory.backfill_playlist",
                user_id=seeded_user,
                playlist_id="pl_empty_ids",
                track_ids=[],
            )
        assert data["success"] is True
        result = data["result"]
        assert result["tracks_source"] == "manual"
        assert result["stored_track_count"] == 0


class TestBackfillToolRegistered:
    def test_registered(self, client: TestClient) -> None:
        """memory.backfill_playlist appears in the tool catalog."""
        resp = client.get("/mcp/tools")
        names = {t["name"] for t in resp.json()}
        assert "memory.backfill_playlist" in names
