"""Tests for MCP dispatcher endpoints."""

from collections.abc import AsyncGenerator, Generator
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.dependencies import db_manager
from app.main import app
from app.settings import AppSettings, get_settings
from shared.db.base import Base
from shared.db.enums import TrackSource
from shared.db.models.music import Artist, Play, Track, TrackArtist
from shared.db.models.user import User

TEST_FERNET_KEY = Fernet.generate_key().decode()


def _test_settings() -> AppSettings:
    return AppSettings(
        SPOTIFY_CLIENT_ID="test",
        SPOTIFY_CLIENT_SECRET="test",
        TOKEN_ENCRYPTION_KEY=TEST_FERNET_KEY,
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
        user = User(spotify_user_id="mcpuser", display_name="MCP")
        session.add(user)
        await session.flush()

        artist = Artist(name="MA", source=TrackSource.SPOTIFY_API)
        session.add(artist)
        await session.flush()

        track = Track(name="MT", spotify_track_id="MT1", source=TrackSource.SPOTIFY_API)
        session.add(track)
        await session.flush()

        session.add(TrackArtist(track_id=track.id, artist_id=artist.id, position=0))
        session.add(
            Play(
                user_id=user.id,
                track_id=track.id,
                played_at=datetime(2026, 2, 1, 12, 0),
                ms_played=200000,
                source=TrackSource.SPOTIFY_API,
            )
        )
        await session.flush()
        uid = user.id
        await session.commit()
    return uid


def test_list_tools(client: TestClient) -> None:
    resp = client.get("/mcp/tools")
    assert resp.status_code == 200
    tools = resp.json()
    assert isinstance(tools, list)
    assert len(tools) >= 21  # 6 history + 11 spotify + 4 ops
    names = {t["name"] for t in tools}
    assert "history.taste_summary" in names
    assert "ops.sync_status" in names
    assert "ops.list_users" in names
    assert "spotify.search" in names


def test_call_unknown_tool(client: TestClient) -> None:
    resp = client.post("/mcp/call", json={"tool": "nonexistent.tool", "arguments": {}})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "Unknown tool" in data["error"]


def test_call_history_top_artists(client: TestClient, seeded_user: int) -> None:
    resp = client.post(
        "/mcp/call",
        json={"tool": "history.top_artists", "arguments": {"user_id": seeded_user, "days": 3650}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert isinstance(data["result"], list)
    assert len(data["result"]) == 1
    assert data["result"][0]["artist_name"] == "MA"


def test_call_history_taste_summary(client: TestClient, seeded_user: int) -> None:
    resp = client.post(
        "/mcp/call",
        json={"tool": "history.taste_summary", "arguments": {"user_id": seeded_user, "days": 3650}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["result"]["total_plays"] == 1


def test_call_ops_sync_status_no_checkpoint(client: TestClient, seeded_user: int) -> None:
    resp = client.post(
        "/mcp/call",
        json={"tool": "ops.sync_status", "arguments": {"user_id": seeded_user}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["result"]["status"] == "no_checkpoint"


def test_call_list_users(client: TestClient, seeded_user: int) -> None:
    """ops.list_users requires no arguments."""
    resp = client.post("/mcp/call", json={"tool": "ops.list_users"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert isinstance(data["result"], list)
    assert len(data["result"]) == 1
    assert data["result"][0]["user_id"] == seeded_user


def test_call_flat_args(client: TestClient, seeded_user: int) -> None:
    """ChatGPT may send args at the top level instead of nested."""
    resp = client.post(
        "/mcp/call",
        json={"tool": "history.top_artists", "user_id": seeded_user, "days": 3650},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert isinstance(data["result"], list)
    assert len(data["result"]) == 1


def test_call_legacy_args_field(client: TestClient, seeded_user: int) -> None:
    """Legacy 'args' field name still works for backward compatibility."""
    resp = client.post(
        "/mcp/call",
        json={"tool": "history.top_artists", "args": {"user_id": seeded_user, "days": 3650}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert len(data["result"]) == 1


def test_call_explicit_arguments_win(client: TestClient, seeded_user: int) -> None:
    """When both flat and nested args are present, explicit arguments win."""
    resp = client.post(
        "/mcp/call",
        json={"tool": "history.top_artists", "arguments": {"user_id": seeded_user, "days": 3650}, "days": 1},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    # days=3650 from explicit arguments should win over days=1 from flat
    assert len(data["result"]) == 1


def test_call_tool_exception_includes_message(client: TestClient, seeded_user: int) -> None:
    """When a tool raises an unhandled exception, the error message is forwarded to the client."""
    with patch(
        "app.mcp.tools.spotify_tools.SpotifyToolHandlers._get_client",
        new_callable=AsyncMock,
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get_track = AsyncMock(side_effect=RuntimeError("Something specific went wrong"))
        mock_get_client.return_value = mock_client

        resp = client.post(
            "/mcp/call",
            json={"tool": "spotify.get_track", "user_id": seeded_user, "track_id": "t1"},
        )
        data = resp.json()
        assert data["success"] is False
        assert "RuntimeError" in data["error"]
        assert "Something specific went wrong" in data["error"]


def test_call_tool_exception_redacts_sensitive_data(client: TestClient, seeded_user: int) -> None:
    """Sensitive data (tokens, emails, IPs) in exception messages is redacted."""
    with patch(
        "app.mcp.tools.spotify_tools.SpotifyToolHandlers._get_client",
        new_callable=AsyncMock,
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get_track = AsyncMock(
            side_effect=RuntimeError(
                "Auth failed: Bearer BQD1234_abcXYZ.token_here for user@example.com from 192.168.1.100"
            )
        )
        mock_get_client.return_value = mock_client

        resp = client.post(
            "/mcp/call",
            json={"tool": "spotify.get_track", "user_id": seeded_user, "track_id": "t1"},
        )
        data = resp.json()
        assert data["success"] is False
        assert "RuntimeError" in data["error"]
        # Sensitive data should be redacted
        assert "BQD1234" not in data["error"]
        assert "Bearer [redacted]" in data["error"]
        assert "user@example.com" not in data["error"]
        assert "[redacted email]" in data["error"]
        assert "192.168.1.100" not in data["error"]
        assert "[redacted ip]" in data["error"]
