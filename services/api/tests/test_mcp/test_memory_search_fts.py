"""Integration tests for memory.search PostgreSQL full-text search.

These tests verify that ``to_tsvector``/``plainto_tsquery`` work correctly
for the ``memory.search`` tool.  They require a running PostgreSQL instance
(e.g. via ``docker-compose up -d postgres``) and are **skipped** by default.

Run::

    docker-compose up -d postgres
    pytest -m integration --override-ini="addopts=" -v
"""

import asyncio
from collections.abc import AsyncGenerator, Generator
from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.dependencies import db_manager
from app.main import app
from app.settings import AppSettings, get_settings
from shared.db.base import Base
from shared.db.models.memory import (
    MemoryPlaylist,
    PlaylistEvent,
    PlaylistSnapshot,
    PreferenceEvent,
    TasteProfile,
)
from shared.db.models.user import User

POSTGRES_URL = "postgresql+asyncpg://postgres:postgres@localhost:5434/spotify_mcp"
TEST_FERNET_KEY = Fernet.generate_key().decode()
_FTS_USER_SID = "fts_integration_test_user"

pytestmark = [pytest.mark.integration]


def _test_settings() -> AppSettings:
    return AppSettings(
        SPOTIFY_CLIENT_ID="test",
        SPOTIFY_CLIENT_SECRET="test",
        TOKEN_ENCRYPTION_KEY=TEST_FERNET_KEY,
        RATE_LIMIT_MCP_PER_MINUTE=10000,
    )


def _run_async(coro: Any) -> Any:
    """Run an async coroutine in a fresh event loop (avoids loop conflicts)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _ensure_tables(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _setup_user(engine: AsyncEngine) -> int:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    # Clean up any leftover from a previous interrupted run
    async with factory() as session:
        prev = (await session.execute(select(User).where(User.spotify_user_id == _FTS_USER_SID))).scalar_one_or_none()
        if prev is not None:
            await _delete_user_memory(session, prev.id)
            await session.delete(prev)
            await session.commit()
    # Create fresh user
    async with factory() as session:
        user = User(spotify_user_id=_FTS_USER_SID, display_name="FTS Test User")
        session.add(user)
        await session.flush()
        uid: int = user.id
        await session.commit()
    return uid


async def _teardown_user(engine: AsyncEngine, uid: int) -> None:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        await _delete_user_memory(session, uid)
        user_obj = await session.get(User, uid)
        if user_obj:
            await session.delete(user_obj)
        await session.commit()


async def _delete_user_memory(session: AsyncSession, user_id: int) -> None:
    """Delete all memory data for a user (respects FK order)."""
    id_result = await session.execute(select(MemoryPlaylist.playlist_id).where(MemoryPlaylist.user_id == user_id))
    pids = [row[0] for row in id_result.all()]
    if pids:
        await session.execute(delete(PlaylistEvent).where(PlaylistEvent.playlist_id.in_(pids)))
        await session.execute(
            update(MemoryPlaylist).where(MemoryPlaylist.user_id == user_id).values(latest_snapshot_id=None)
        )
        await session.execute(delete(PlaylistSnapshot).where(PlaylistSnapshot.playlist_id.in_(pids)))
        await session.execute(delete(MemoryPlaylist).where(MemoryPlaylist.user_id == user_id))
    await session.execute(delete(PreferenceEvent).where(PreferenceEvent.user_id == user_id))
    await session.execute(delete(TasteProfile).where(TasteProfile.user_id == user_id))


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def pg_engine() -> Generator[AsyncEngine]:
    """Create NullPool async engine for PostgreSQL; skip if unavailable."""
    engine = create_async_engine(POSTGRES_URL, echo=False, poolclass=NullPool)
    try:
        _run_async(_ensure_tables(engine))
    except OperationalError, InterfaceError, OSError:
        _run_async(engine.dispose())
        pytest.skip("PostgreSQL not available at localhost:5434")
    yield engine
    _run_async(engine.dispose())


@pytest.fixture
def override_deps(pg_engine: AsyncEngine) -> Generator[None]:
    factory = async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)

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
def fts_user(pg_engine: AsyncEngine) -> Generator[int]:
    """Create a dedicated test user; tear down all their data afterwards."""
    uid: int = _run_async(_setup_user(pg_engine))
    yield uid
    _run_async(_teardown_user(pg_engine, uid))


# ── Helpers ─────────────────────────────────────────────────────────


def _call(client: TestClient, tool: str, **kwargs: object) -> dict[str, object]:
    resp = client.post("/mcp/call", json={"tool": tool, **kwargs})
    assert resp.status_code == 200
    return resp.json()  # type: ignore[no-any-return]


def _seed_playlist(client: TestClient, user_id: int) -> None:
    _call(
        client,
        "memory.log_playlist_create",
        user_id=user_id,
        playlist_id="fts_pl",
        name="Symphonic Metal Mix",
        description="An upbeat symphonic metal playlist with contemplative breaks",
        track_ids=["t1", "t2", "t3"],
        intent_tags='["symphonic metal", "upbeat", "breathers"]',
        seed_context='{"days": 60}',
    )


def _seed_profile(client: TestClient, user_id: int) -> None:
    _call(
        client,
        "memory.update_profile",
        user_id=user_id,
        patch={"core_genres": ["symphonic metal", "power metal"], "avoid": ["pop"]},
        reason="FTS test setup",
    )


def _seed_event(client: TestClient, user_id: int) -> None:
    _call(
        client,
        "memory.append_preference_event",
        user_id=user_id,
        type="rule",
        payload={"raw_text": "max 3 tracks per artist in symphonic metal playlists"},
        source="user",
    )


def _search(client: TestClient, user_id: int, query: str) -> list[dict[str, object]]:
    data = _call(client, "memory.search", user_id=user_id, query=query)
    assert data["success"], data.get("error")
    result = data["result"]
    assert isinstance(result, dict)
    return result["results"]  # type: ignore[no-any-return]


# ── Tests ───────────────────────────────────────────────────────────


def test_fts_stemming_singular_plural(client: TestClient, fts_user: int) -> None:
    """FTS stemming: 'playlist' matches 'playlists' in event payload."""
    _seed_event(client, fts_user)
    results = _search(client, fts_user, "playlist")
    ev_results = [r for r in results if r["kind"] == "preference_event"]
    assert len(ev_results) >= 1, "stemming should match 'playlists' when searching 'playlist'"


def test_fts_stemming_verb_form(client: TestClient, fts_user: int) -> None:
    """FTS stemming: 'break' matches 'breaks' in description."""
    _seed_playlist(client, fts_user)
    results = _search(client, fts_user, "break")
    pl_results = [r for r in results if r["kind"] == "playlist"]
    assert len(pl_results) >= 1, "stemming should match 'breaks' when searching 'break'"


def test_fts_multiword_query(client: TestClient, fts_user: int) -> None:
    """Multi-word query matches documents containing all words (in any order)."""
    _seed_playlist(client, fts_user)
    results = _search(client, fts_user, "upbeat metal")
    pl_results = [r for r in results if r["kind"] == "playlist"]
    assert len(pl_results) >= 1, "'upbeat metal' should match description containing both words"


def test_fts_all_search_targets(client: TestClient, fts_user: int) -> None:
    """FTS finds results in all search targets: name, description, tags, events, profile."""
    _seed_playlist(client, fts_user)
    _seed_profile(client, fts_user)
    _seed_event(client, fts_user)

    results = _search(client, fts_user, "symphonic")
    kinds = {r["kind"] for r in results}
    assert "playlist" in kinds, "should match playlist name"
    assert "preference_event" in kinds, "should match event payload"
    assert "profile" in kinds, "should match profile content"


def test_fts_deduplication(client: TestClient, fts_user: int) -> None:
    """Playlist matching name + description appears once with highest score."""
    _seed_playlist(client, fts_user)
    results = _search(client, fts_user, "symphonic")
    pl_results = [r for r in results if r["kind"] == "playlist" and r["id"] == "fts_pl"]
    assert len(pl_results) == 1
    assert pl_results[0]["score"] == 1.0


def test_fts_empty_results(client: TestClient, fts_user: int) -> None:
    """No matches returns empty list."""
    _seed_playlist(client, fts_user)
    results = _search(client, fts_user, "jazz fusion")
    assert results == []


def test_fts_no_substring_matching(client: TestClient, fts_user: int) -> None:
    """FTS does word-boundary matching, not substring — 'symph' should NOT match 'symphonic'.

    This is a key behavioral difference from ILIKE (which would match).
    """
    _seed_playlist(client, fts_user)
    results = _search(client, fts_user, "symph")
    # FTS tokenizes at word boundaries, so partial prefix doesn't match
    assert results == [], "FTS should not do substring matching"
