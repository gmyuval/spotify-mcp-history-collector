"""Tests for admin user credential endpoints (GET/PUT/DELETE spotify-credentials)."""

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
        SPOTIFY_CLIENT_ID="test-id",
        SPOTIFY_CLIENT_SECRET="test-secret",
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
async def seeded_user(async_engine: AsyncEngine) -> int:
    """Create a single user and return its id."""
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        user = User(spotify_user_id="cred-test-user", display_name="Cred Test")
        session.add(user)
        await session.commit()
        return user.id


def test_get_credentials_no_custom(client: TestClient, seeded_user: int) -> None:
    """GET returns has_custom_credentials=false when no credentials are set."""
    resp = client.get(f"/admin/users/{seeded_user}/spotify-credentials")
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_custom_credentials"] is False
    assert data["custom_client_id"] is None


def test_set_credentials(client: TestClient, seeded_user: int) -> None:
    """PUT sets credentials and returns success."""
    resp = client.put(
        f"/admin/users/{seeded_user}/spotify-credentials",
        json={"client_id": "my-app-id", "client_secret": "my-app-secret"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True


def test_get_credentials_after_set(client: TestClient, seeded_user: int) -> None:
    """After PUT, GET returns has_custom_credentials=true with client_id."""
    client.put(
        f"/admin/users/{seeded_user}/spotify-credentials",
        json={"client_id": "my-app-id", "client_secret": "my-app-secret"},
    )
    resp = client.get(f"/admin/users/{seeded_user}/spotify-credentials")
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_custom_credentials"] is True
    assert data["custom_client_id"] == "my-app-id"


def test_clear_credentials(client: TestClient, seeded_user: int) -> None:
    """DELETE clears credentials and returns success."""
    # First set credentials
    client.put(
        f"/admin/users/{seeded_user}/spotify-credentials",
        json={"client_id": "my-app-id", "client_secret": "my-app-secret"},
    )
    # Then clear them
    resp = client.delete(f"/admin/users/{seeded_user}/spotify-credentials")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True


def test_get_credentials_after_clear(client: TestClient, seeded_user: int) -> None:
    """After DELETE, GET returns has_custom_credentials=false."""
    # Set then clear
    client.put(
        f"/admin/users/{seeded_user}/spotify-credentials",
        json={"client_id": "my-app-id", "client_secret": "my-app-secret"},
    )
    client.delete(f"/admin/users/{seeded_user}/spotify-credentials")
    # Verify
    resp = client.get(f"/admin/users/{seeded_user}/spotify-credentials")
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_custom_credentials"] is False
    assert data["custom_client_id"] is None


def test_set_credentials_user_not_found(client: TestClient) -> None:
    """PUT for non-existent user returns 404."""
    resp = client.put(
        "/admin/users/9999/spotify-credentials",
        json={"client_id": "my-app-id", "client_secret": "my-app-secret"},
    )
    assert resp.status_code == 404


def test_clear_credentials_user_not_found(client: TestClient) -> None:
    """DELETE for non-existent user returns 404."""
    resp = client.delete("/admin/users/9999/spotify-credentials")
    assert resp.status_code == 404
