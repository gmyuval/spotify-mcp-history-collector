"""Tests for admin user management endpoints."""

from collections.abc import AsyncGenerator, Generator

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.dependencies import db_manager
from app.main import app
from app.settings import AppSettings, get_settings
from shared.db.base import Base
from shared.db.enums import SyncStatus
from shared.db.models.operations import SyncCheckpoint
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
def client(async_engine: AsyncEngine) -> Generator[TestClient]:
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async def _override() -> AsyncGenerator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[db_manager.dependency] = _override
    app.dependency_overrides[get_settings] = _test_settings
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
async def seeded_users(async_engine: AsyncEngine) -> list[int]:
    """Create two users with sync checkpoints."""
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        u1 = User(spotify_user_id="user1", display_name="User One")
        u2 = User(spotify_user_id="user2", display_name="User Two")
        session.add_all([u1, u2])
        await session.flush()

        cp1 = SyncCheckpoint(user_id=u1.id, status=SyncStatus.IDLE)
        cp2 = SyncCheckpoint(user_id=u2.id, status=SyncStatus.PAUSED)
        session.add_all([cp1, cp2])
        await session.commit()
        return [u1.id, u2.id]


def test_list_users(client: TestClient, seeded_users: list[int]) -> None:
    resp = client.get("/admin/users")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2
    assert data["items"][0]["spotify_user_id"] == "user1"
    assert data["items"][0]["sync_status"] == "idle"
    assert data["items"][1]["sync_status"] == "paused"


def test_list_users_pagination(client: TestClient, seeded_users: list[int]) -> None:
    resp = client.get("/admin/users?limit=1&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 1
    assert data["limit"] == 1
    assert data["offset"] == 0


def test_get_user_detail(client: TestClient, seeded_users: list[int]) -> None:
    uid = seeded_users[0]
    resp = client.get(f"/admin/users/{uid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == uid
    assert data["spotify_user_id"] == "user1"
    assert data["sync_status"] == "idle"
    assert data["token_expires_at"] is None


def test_get_user_not_found(client: TestClient) -> None:
    resp = client.get("/admin/users/9999")
    assert resp.status_code == 404


def test_pause_user(client: TestClient, seeded_users: list[int]) -> None:
    uid = seeded_users[0]
    resp = client.post(f"/admin/users/{uid}/pause")
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    detail = client.get(f"/admin/users/{uid}").json()
    assert detail["sync_status"] == "paused"


def test_resume_user(client: TestClient, seeded_users: list[int]) -> None:
    uid = seeded_users[1]  # User 2 is paused
    resp = client.post(f"/admin/users/{uid}/resume")
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    detail = client.get(f"/admin/users/{uid}").json()
    assert detail["sync_status"] == "idle"


def test_trigger_sync(client: TestClient, seeded_users: list[int]) -> None:
    uid = seeded_users[0]
    resp = client.post(f"/admin/users/{uid}/trigger-sync")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "re-sync" in data["message"]


def test_delete_user(client: TestClient, seeded_users: list[int]) -> None:
    uid = seeded_users[0]
    resp = client.delete(f"/admin/users/{uid}")
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    # Verify user is gone
    resp = client.get(f"/admin/users/{uid}")
    assert resp.status_code == 404


def test_delete_user_not_found(client: TestClient) -> None:
    resp = client.delete("/admin/users/9999")
    assert resp.status_code == 404


def test_pause_user_not_found(client: TestClient) -> None:
    resp = client.post("/admin/users/9999/pause")
    assert resp.status_code == 404
