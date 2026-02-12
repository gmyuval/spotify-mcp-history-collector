"""Tests for history REST endpoints."""

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
        user = User(spotify_user_id="ruser", display_name="R")
        session.add(user)
        await session.flush()

        artist = Artist(name="RA", source=TrackSource.SPOTIFY_API)
        session.add(artist)
        await session.flush()

        track = Track(name="RT", spotify_track_id="RT1", source=TrackSource.SPOTIFY_API)
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


def test_top_artists(client: TestClient, seeded_user: int) -> None:
    resp = client.get(f"/history/users/{seeded_user}/top-artists?days=3650")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["artist_name"] == "RA"


def test_top_tracks(client: TestClient, seeded_user: int) -> None:
    resp = client.get(f"/history/users/{seeded_user}/top-tracks?days=3650")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["track_name"] == "RT"


def test_heatmap(client: TestClient, seeded_user: int) -> None:
    resp = client.get(f"/history/users/{seeded_user}/heatmap?days=3650")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_plays"] == 1
    assert len(data["cells"]) == 1


def test_repeat_rate(client: TestClient, seeded_user: int) -> None:
    resp = client.get(f"/history/users/{seeded_user}/repeat-rate?days=3650")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_plays"] == 1
    assert data["unique_tracks"] == 1


def test_coverage(client: TestClient, seeded_user: int) -> None:
    resp = client.get(f"/history/users/{seeded_user}/coverage?days=3650")
    assert resp.status_code == 200
    data = resp.json()
    assert data["api_source_count"] == 1


def test_taste_summary(client: TestClient, seeded_user: int) -> None:
    resp = client.get(f"/history/users/{seeded_user}/taste-summary?days=3650")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_plays"] == 1
    assert len(data["top_artists"]) == 1


def test_nonexistent_user_404(client: TestClient) -> None:
    resp = client.get("/history/users/9999/top-artists")
    assert resp.status_code == 404
