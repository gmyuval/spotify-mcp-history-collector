"""Tests for history tools invoked through the MCP dispatcher."""

from collections.abc import AsyncGenerator, Generator
from datetime import datetime

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
        user = User(spotify_user_id="htuser", display_name="HT")
        session.add(user)
        await session.flush()

        artist = Artist(name="HTA", source=TrackSource.IMPORT_ZIP)
        session.add(artist)
        await session.flush()

        track = Track(name="HTT", local_track_id="local:htt", source=TrackSource.IMPORT_ZIP)
        session.add(track)
        await session.flush()

        session.add(TrackArtist(track_id=track.id, artist_id=artist.id, position=0))
        for d in range(1, 4):
            session.add(
                Play(
                    user_id=user.id,
                    track_id=track.id,
                    played_at=datetime(2026, 1, d, 15, 0),
                    ms_played=180000,
                    source=TrackSource.IMPORT_ZIP,
                )
            )
        await session.flush()
        uid = user.id
        await session.commit()
    return uid


def test_history_top_tracks(client: TestClient, seeded_user: int) -> None:
    resp = client.post(
        "/mcp/call",
        json={"tool": "history.top_tracks", "args": {"user_id": seeded_user, "days": 3650}},
    )
    data = resp.json()
    assert data["success"]
    assert len(data["result"]) == 1
    assert data["result"][0]["track_name"] == "HTT"
    assert data["result"][0]["play_count"] == 3


def test_history_listening_heatmap(client: TestClient, seeded_user: int) -> None:
    resp = client.post(
        "/mcp/call",
        json={"tool": "history.listening_heatmap", "args": {"user_id": seeded_user, "days": 3650}},
    )
    data = resp.json()
    assert data["success"]
    assert data["result"]["total_plays"] == 3


def test_history_repeat_rate(client: TestClient, seeded_user: int) -> None:
    resp = client.post(
        "/mcp/call",
        json={"tool": "history.repeat_rate", "args": {"user_id": seeded_user, "days": 3650}},
    )
    data = resp.json()
    assert data["success"]
    assert data["result"]["repeat_rate"] == 3.0
    assert data["result"]["unique_tracks"] == 1


def test_history_coverage(client: TestClient, seeded_user: int) -> None:
    resp = client.post(
        "/mcp/call",
        json={"tool": "history.coverage", "args": {"user_id": seeded_user, "days": 3650}},
    )
    data = resp.json()
    assert data["success"]
    assert data["result"]["import_source_count"] == 3
    assert data["result"]["api_source_count"] == 0
