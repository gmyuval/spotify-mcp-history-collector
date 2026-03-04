"""Tests for memory.search, memory.export_user_data, memory.delete_user_data."""

from collections.abc import AsyncGenerator, Generator
from typing import Any

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
        user = User(spotify_user_id="datauser", display_name="Data User")
        session.add(user)
        await session.flush()
        uid = user.id
        await session.commit()
    return uid


@pytest.fixture
async def second_user(async_engine: AsyncEngine) -> int:
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        user = User(spotify_user_id="datauser2", display_name="Data User 2")
        session.add(user)
        await session.flush()
        uid = user.id
        await session.commit()
    return uid


def _call(client: TestClient, tool: str, **kwargs: object) -> dict[str, Any]:
    resp = client.post("/mcp/call", json={"tool": tool, **kwargs})
    assert resp.status_code == 200
    return resp.json()  # type: ignore[no-any-return]


def _seed_profile(client: TestClient, user_id: int) -> None:
    """Create a taste profile for the user."""
    _call(
        client,
        "memory.update_profile",
        user_id=user_id,
        patch={"core_genres": ["symphonic metal", "power metal"], "avoid": ["pop"]},
        reason="Initial taste setup",
    )


def _seed_event(client: TestClient, user_id: int) -> None:
    """Append a preference event for the user."""
    _call(
        client,
        "memory.append_preference_event",
        user_id=user_id,
        type="rule",
        payload={"raw_text": "max 3 tracks per artist in symphonic metal playlists"},
        source="user",
    )


def _seed_playlist(client: TestClient, user_id: int, playlist_id: str = "pl_search_test") -> None:
    """Create a playlist in the memory ledger."""
    _call(
        client,
        "memory.log_playlist_create",
        user_id=user_id,
        playlist_id=playlist_id,
        name="Symphonic Metal Mix",
        description="An upbeat symphonic metal playlist with contemplative breaks",
        track_ids=["track1", "track2", "track3"],
        intent_tags='["symphonic metal", "upbeat", "breathers"]',
        seed_context='{"days": 60}',
    )


def _seed_mutation(client: TestClient, user_id: int, playlist_id: str = "pl_search_test") -> None:
    """Add a mutation to a playlist."""
    _call(
        client,
        "memory.log_playlist_mutation",
        user_id=user_id,
        playlist_id=playlist_id,
        mutation_type="ADD_TRACKS",
        payload='{"track_ids": ["track4", "track5"]}',
    )


# ── memory.search ──────────────────────────────────────────────────


def test_search_finds_playlist_by_name(client: TestClient, seeded_user: int) -> None:
    """Search finds playlists by name fragment."""
    _seed_playlist(client, seeded_user)
    data = _call(client, "memory.search", user_id=seeded_user, query="Symphonic")
    assert data["success"]
    results = data["result"]["results"]
    assert len(results) >= 1
    pl_results = [r for r in results if r["kind"] == "playlist"]
    assert len(pl_results) >= 1
    assert pl_results[0]["id"] == "pl_search_test"
    assert pl_results[0]["score"] == 1.0


def test_search_finds_playlist_by_description(client: TestClient, seeded_user: int) -> None:
    """Search finds playlists by description fragment."""
    _seed_playlist(client, seeded_user)
    data = _call(client, "memory.search", user_id=seeded_user, query="contemplative breaks")
    assert data["success"]
    results = data["result"]["results"]
    pl_results = [r for r in results if r["kind"] == "playlist"]
    assert len(pl_results) >= 1
    assert pl_results[0]["id"] == "pl_search_test"


def test_search_finds_playlist_by_intent_tag(client: TestClient, seeded_user: int) -> None:
    """Search finds playlists by intent tag value."""
    _seed_playlist(client, seeded_user)
    data = _call(client, "memory.search", user_id=seeded_user, query="breathers")
    assert data["success"]
    results = data["result"]["results"]
    pl_results = [r for r in results if r["kind"] == "playlist"]
    assert len(pl_results) >= 1


def test_search_finds_preference_event(client: TestClient, seeded_user: int) -> None:
    """Search finds preference events by payload content."""
    _seed_event(client, seeded_user)
    data = _call(client, "memory.search", user_id=seeded_user, query="max 3 tracks")
    assert data["success"]
    results = data["result"]["results"]
    ev_results = [r for r in results if r["kind"] == "preference_event"]
    assert len(ev_results) >= 1
    assert "rule" in ev_results[0]["snippet"]


def test_search_finds_profile(client: TestClient, seeded_user: int) -> None:
    """Search finds taste profile by content."""
    _seed_profile(client, seeded_user)
    data = _call(client, "memory.search", user_id=seeded_user, query="symphonic metal")
    assert data["success"]
    results = data["result"]["results"]
    prof_results = [r for r in results if r["kind"] == "profile"]
    assert len(prof_results) >= 1
    assert prof_results[0]["score"] == 0.3


def test_search_deduplicates_playlist(client: TestClient, seeded_user: int) -> None:
    """Playlist matching in name and description appears only once with highest score."""
    _seed_playlist(client, seeded_user)
    # "symphonic" appears in both name and description
    data = _call(client, "memory.search", user_id=seeded_user, query="symphonic")
    assert data["success"]
    results = data["result"]["results"]
    pl_results = [r for r in results if r["kind"] == "playlist" and r["id"] == "pl_search_test"]
    assert len(pl_results) == 1
    # Name match has highest score (1.0)
    assert pl_results[0]["score"] == 1.0


def test_search_empty_results(client: TestClient, seeded_user: int) -> None:
    """Search for non-matching query returns empty list."""
    _seed_playlist(client, seeded_user)
    data = _call(client, "memory.search", user_id=seeded_user, query="jazz fusion")
    assert data["success"]
    assert data["result"]["results"] == []


def test_search_respects_limit(client: TestClient, seeded_user: int) -> None:
    """Limit parameter caps results."""
    # Create multiple playlists
    for i in range(5):
        _call(
            client,
            "memory.log_playlist_create",
            user_id=seeded_user,
            playlist_id=f"pl_limit_{i}",
            name=f"Metal Playlist {i}",
            track_ids=[f"track_{i}"],
        )
    data = _call(client, "memory.search", user_id=seeded_user, query="Metal", limit=2)
    assert data["success"]
    assert len(data["result"]["results"]) == 2


def test_search_user_isolation(client: TestClient, seeded_user: int, second_user: int) -> None:
    """User A cannot find user B's data."""
    _seed_playlist(client, seeded_user)
    _seed_profile(client, seeded_user)

    # Second user should find nothing
    data = _call(client, "memory.search", user_id=second_user, query="symphonic")
    assert data["success"]
    assert data["result"]["results"] == []


def test_search_validation_empty_query(client: TestClient, seeded_user: int) -> None:
    """Empty query returns error."""
    data = _call(client, "memory.search", user_id=seeded_user, query="")
    assert not data["success"]
    assert "query must be a non-empty string" in data["error"]


def test_search_validation_invalid_user_id(client: TestClient) -> None:
    """Invalid user_id returns error."""
    data = _call(client, "memory.search", user_id=-1, query="test")
    assert not data["success"]
    assert "user_id must be a positive integer" in data["error"]


def test_search_default_limit(client: TestClient, seeded_user: int) -> None:
    """Omitting limit uses default (25)."""
    data = _call(client, "memory.search", user_id=seeded_user, query="anything")
    assert data["success"]
    # Just verify it doesn't error — result will be empty since no data matches


# ── memory.export_user_data ────────────────────────────────────────


def test_export_complete_data(client: TestClient, seeded_user: int) -> None:
    """Export returns all stored memory data."""
    _seed_profile(client, seeded_user)
    _seed_event(client, seeded_user)
    _seed_playlist(client, seeded_user)
    _seed_mutation(client, seeded_user)

    data = _call(client, "memory.export_user_data", user_id=seeded_user)
    assert data["success"]
    result = data["result"]
    assert result["user_id"] == seeded_user
    assert "exported_at" in result

    d = result["data"]

    # Profile exists
    assert d["profile"] is not None
    assert d["profile"]["version"] >= 1
    assert "symphonic metal" in str(d["profile"]["profile_json"])

    # Preference events (update_profile with reason creates a note + explicit event)
    assert len(d["preference_events"]) >= 1

    # Playlists
    assert len(d["playlists"]) == 1
    assert d["playlists"][0]["playlist_id"] == "pl_search_test"
    assert d["playlists"][0]["name"] == "Symphonic Metal Mix"

    # Snapshots (at least the create snapshot)
    assert len(d["snapshots"]) >= 1
    assert d["snapshots"][0]["playlist_id"] == "pl_search_test"

    # Playlist events (from mutation)
    assert len(d["playlist_events"]) >= 1
    assert d["playlist_events"][0]["type"] == "ADD_TRACKS"


def test_export_empty_user(client: TestClient, seeded_user: int) -> None:
    """Export for user with no data returns empty collections."""
    data = _call(client, "memory.export_user_data", user_id=seeded_user)
    assert data["success"]
    d = data["result"]["data"]
    assert d["profile"] is None
    assert d["preference_events"] == []
    assert d["playlists"] == []
    assert d["snapshots"] == []
    assert d["playlist_events"] == []


def test_export_user_isolation(client: TestClient, seeded_user: int, second_user: int) -> None:
    """Export only returns data for the requesting user."""
    _seed_profile(client, seeded_user)
    _seed_playlist(client, seeded_user)

    # Second user export should be empty
    data = _call(client, "memory.export_user_data", user_id=second_user)
    assert data["success"]
    d = data["result"]["data"]
    assert d["profile"] is None
    assert d["playlists"] == []


def test_export_validation_error(client: TestClient) -> None:
    """Invalid user_id returns error."""
    data = _call(client, "memory.export_user_data", user_id=-1)
    assert not data["success"]
    assert "user_id must be a positive integer" in data["error"]


# ── memory.delete_user_data ────────────────────────────────────────


def test_delete_all_data(client: TestClient, seeded_user: int) -> None:
    """Delete removes all memory data for the user."""
    _seed_profile(client, seeded_user)
    _seed_event(client, seeded_user)
    _seed_playlist(client, seeded_user)
    _seed_mutation(client, seeded_user)

    # Delete
    data = _call(client, "memory.delete_user_data", user_id=seeded_user, confirm=True)
    assert data["success"]
    assert data["result"]["deleted"] is True
    assert "deleted_at" in data["result"]

    # Verify everything is gone
    profile = _call(client, "memory.get_profile", user_id=seeded_user)
    assert profile["result"]["version"] == 0

    playlists = _call(client, "memory.get_playlists", user_id=seeded_user)
    assert playlists["result"]["items"] == []

    export = _call(client, "memory.export_user_data", user_id=seeded_user)
    d = export["result"]["data"]
    assert d["profile"] is None
    assert d["preference_events"] == []
    assert d["playlists"] == []
    assert d["snapshots"] == []
    assert d["playlist_events"] == []


def test_delete_requires_confirm(client: TestClient, seeded_user: int) -> None:
    """Delete without confirm=true raises error."""
    data = _call(client, "memory.delete_user_data", user_id=seeded_user, confirm=False)
    assert not data["success"]
    assert "confirm must be true" in data["error"]


def test_delete_missing_confirm(client: TestClient, seeded_user: int) -> None:
    """Delete without confirm parameter raises error."""
    resp = client.post(
        "/mcp/call",
        json={"tool": "memory.delete_user_data", "user_id": seeded_user},
    )
    data = resp.json()
    assert not data["success"]
    assert "confirm must be true" in data["error"]


def test_delete_empty_user(client: TestClient, seeded_user: int) -> None:
    """Deleting user with no data succeeds (idempotent)."""
    data = _call(client, "memory.delete_user_data", user_id=seeded_user, confirm=True)
    assert data["success"]
    assert data["result"]["deleted"] is True


def test_delete_user_isolation(client: TestClient, seeded_user: int, second_user: int) -> None:
    """Deleting user A's data doesn't affect user B."""
    _seed_profile(client, seeded_user)
    _seed_playlist(client, seeded_user)
    _seed_profile(client, second_user)

    # Create playlist for second user too
    _call(
        client,
        "memory.log_playlist_create",
        user_id=second_user,
        playlist_id="pl_user2",
        name="User 2 Playlist",
        track_ids=["t1"],
    )

    # Delete first user's data
    _call(client, "memory.delete_user_data", user_id=seeded_user, confirm=True)

    # First user's data is gone
    export_a = _call(client, "memory.export_user_data", user_id=seeded_user)
    assert export_a["result"]["data"]["profile"] is None
    assert export_a["result"]["data"]["playlists"] == []

    # Second user's data is untouched
    profile_b = _call(client, "memory.get_profile", user_id=second_user)
    assert profile_b["result"]["version"] == 1

    playlists_b = _call(client, "memory.get_playlists", user_id=second_user)
    assert len(playlists_b["result"]["items"]) == 1


def test_delete_then_export(client: TestClient, seeded_user: int) -> None:
    """After delete, export returns empty data."""
    _seed_profile(client, seeded_user)
    _seed_event(client, seeded_user)
    _seed_playlist(client, seeded_user)

    _call(client, "memory.delete_user_data", user_id=seeded_user, confirm=True)

    data = _call(client, "memory.export_user_data", user_id=seeded_user)
    assert data["success"]
    d = data["result"]["data"]
    assert d["profile"] is None
    assert d["preference_events"] == []
    assert d["playlists"] == []
    assert d["snapshots"] == []
    assert d["playlist_events"] == []


def test_delete_validation_error(client: TestClient) -> None:
    """Invalid user_id returns error."""
    data = _call(client, "memory.delete_user_data", user_id=-1, confirm=True)
    assert not data["success"]
    assert "user_id must be a positive integer" in data["error"]
