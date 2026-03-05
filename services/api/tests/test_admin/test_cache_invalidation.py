"""Tests for admin cache invalidation endpoints."""

from collections.abc import AsyncGenerator, Generator

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
        ADMIN_AUTH_MODE="",  # Disabled for testing
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
        user = User(spotify_user_id="cache_user", display_name="Cache User")
        session.add(user)
        await session.flush()
        uid = user.id
        await session.commit()
    return uid


def test_invalidate_playlist_cache_single(client: TestClient, seeded_user: int) -> None:
    """Invalidate a single playlist cache returns success."""
    resp = client.post(
        "/admin/cache/playlists/invalidate",
        json={"user_id": seeded_user, "playlist_id": "pl_test"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "pl_test" in data["message"]


def test_invalidate_playlist_cache_all(client: TestClient, seeded_user: int) -> None:
    """Invalidate all playlist caches for a user returns success."""
    resp = client.post(
        "/admin/cache/playlists/invalidate",
        json={"user_id": seeded_user},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "All playlist caches" in data["message"]


def test_invalidate_all_caches(client: TestClient, seeded_user: int) -> None:
    """Invalidate all caches for a user returns success."""
    resp = client.post(
        "/admin/cache/all/invalidate",
        json={"user_id": seeded_user},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "All playlist caches invalidated" in data["message"]


def test_invalidate_cache_user_not_found(client: TestClient) -> None:
    """Invalidation fails for non-existent user."""
    resp = client.post(
        "/admin/cache/playlists/invalidate",
        json={"user_id": 99999, "playlist_id": "pl_test"},
    )
    assert resp.status_code == 404


def test_invalidate_all_caches_user_not_found(client: TestClient) -> None:
    """Invalidation fails for non-existent user."""
    resp = client.post(
        "/admin/cache/all/invalidate",
        json={"user_id": 99999},
    )
    assert resp.status_code == 404


def test_invalidate_no_auth(async_engine: AsyncEngine) -> None:
    """Invalidation requires admin authentication when enabled."""

    def _auth_settings() -> AppSettings:
        return AppSettings(
            SPOTIFY_CLIENT_ID="test",
            SPOTIFY_CLIENT_SECRET="test",
            TOKEN_ENCRYPTION_KEY=TEST_FERNET_KEY,
            ADMIN_AUTH_MODE="token",
            ADMIN_TOKEN="secret-token",
        )

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
    app.dependency_overrides[get_settings] = _auth_settings
    try:
        c = TestClient(app)
        resp = c.post(
            "/admin/cache/playlists/invalidate",
            json={"user_id": 1, "playlist_id": "pl_test"},
        )
        assert resp.status_code in (401, 403)
    finally:
        app.dependency_overrides.clear()
