"""Tests for JWT auth endpoints — callback JWT issuance, refresh, logout."""

from collections.abc import AsyncGenerator

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.auth.jwt import JWTService
from app.auth.state import OAuthStateManager
from app.dependencies import db_manager
from app.main import app
from app.settings import AppSettings, get_settings
from shared.db.base import Base
from shared.db.models.rbac import Permission, Role, RolePermission, UserRole
from shared.db.models.user import User

TEST_FERNET_KEY = Fernet.generate_key().decode()


def _test_settings() -> AppSettings:
    return AppSettings(
        SPOTIFY_CLIENT_ID="test-client-id",
        SPOTIFY_CLIENT_SECRET="test-client-secret",
        SPOTIFY_REDIRECT_URI="http://localhost:8000/auth/callback",
        TOKEN_ENCRYPTION_KEY=TEST_FERNET_KEY,
        JWT_COOKIE_SECURE=False,
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
def override_deps(async_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_session() -> AsyncGenerator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[db_manager.dependency] = _override_session
    app.dependency_overrides[get_settings] = _test_settings

    # The JWT middleware calls get_settings() directly (not via DI).
    # Monkeypatch it so the middleware uses the test encryption key.
    monkeypatch.setattr("app.auth.middleware.get_settings", _test_settings)

    # Reset in-memory rate limiter to avoid 429s from accumulated test hits.
    from app.middleware import RateLimitMiddleware

    current = app.middleware_stack
    while current is not None:
        if isinstance(current, RateLimitMiddleware):
            current._hits.clear()
            break
        current = getattr(current, "app", None)

    yield
    app.dependency_overrides.clear()


def _make_state() -> str:
    settings = _test_settings()
    mgr = OAuthStateManager(key=settings.TOKEN_ENCRYPTION_KEY, ttl_seconds=settings.OAUTH_STATE_TTL_SECONDS)
    return mgr.generate()


MOCK_TOKEN_RESPONSE = {
    "access_token": "mock-access-token",
    "token_type": "Bearer",
    "expires_in": 3600,
    "refresh_token": "mock-refresh-token",
    "scope": "user-read-recently-played user-top-read",
}

MOCK_PROFILE_RESPONSE = {
    "id": "testuser123",
    "display_name": "Test User",
    "email": "test@example.com",
    "country": "US",
    "product": "premium",
}


@respx.mock
def test_callback_returns_jwt_for_api_client(override_deps: None) -> None:
    """OAuth callback returns access_token and refresh_token in JSON body."""
    from fastapi.testclient import TestClient

    client = TestClient(app, follow_redirects=False)
    respx.post("https://accounts.spotify.com/api/token").mock(
        return_value=httpx.Response(200, json=MOCK_TOKEN_RESPONSE)
    )
    respx.get("https://api.spotify.com/v1/me").mock(return_value=httpx.Response(200, json=MOCK_PROFILE_RESPONSE))

    state = _make_state()
    response = client.get(f"/auth/callback?code=test-code&state={state}")
    assert response.status_code == 200

    data = response.json()
    assert data["message"] == "Authorization successful"
    assert data["access_token"] is not None
    assert data["refresh_token"] is not None
    assert data["expires_in"] == 900  # 15 min * 60

    # Verify the JWT is valid
    svc = JWTService(_test_settings())
    user_id = svc.decode_access_token(data["access_token"])
    assert user_id > 0


@respx.mock
def test_callback_sets_cookies_for_browser(override_deps: None) -> None:
    """Browser callback (Accept: text/html) sets JWT cookies and redirects."""
    from fastapi.testclient import TestClient

    client = TestClient(app, follow_redirects=False)
    respx.post("https://accounts.spotify.com/api/token").mock(
        return_value=httpx.Response(200, json=MOCK_TOKEN_RESPONSE)
    )
    respx.get("https://api.spotify.com/v1/me").mock(return_value=httpx.Response(200, json=MOCK_PROFILE_RESPONSE))

    state = _make_state()
    response = client.get(
        f"/auth/callback?code=test-code&state={state}",
        headers={"Accept": "text/html"},
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/users"

    # Check cookies are set
    assert "access_token" in response.cookies
    assert "refresh_token" in response.cookies


@respx.mock
def test_refresh_with_valid_token(override_deps: None) -> None:
    """POST /auth/refresh with valid refresh token returns new access token."""
    from fastapi.testclient import TestClient

    client = TestClient(app, follow_redirects=False)

    # First create a user via callback
    respx.post("https://accounts.spotify.com/api/token").mock(
        return_value=httpx.Response(200, json=MOCK_TOKEN_RESPONSE)
    )
    respx.get("https://api.spotify.com/v1/me").mock(return_value=httpx.Response(200, json=MOCK_PROFILE_RESPONSE))
    state = _make_state()
    cb_resp = client.get(f"/auth/callback?code=test-code&state={state}")
    refresh_token = cb_resp.json()["refresh_token"]

    # Now refresh
    resp = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    data = resp.json()
    assert data["access_token"] is not None
    assert data["token_type"] == "Bearer"
    assert data["expires_in"] == 900


def test_refresh_without_token(override_deps: None) -> None:
    """POST /auth/refresh without token returns 401."""
    from fastapi.testclient import TestClient

    client = TestClient(app, follow_redirects=False)
    resp = client.post("/auth/refresh")
    assert resp.status_code == 401
    assert "No refresh token" in resp.json()["detail"]


def test_refresh_with_invalid_token(override_deps: None) -> None:
    """POST /auth/refresh with invalid token returns 401."""
    from fastapi.testclient import TestClient

    client = TestClient(app, follow_redirects=False)
    resp = client.post("/auth/refresh", json={"refresh_token": "invalid.token.here"})
    assert resp.status_code == 401


@respx.mock
def test_refresh_with_deleted_user(override_deps: None, async_engine: AsyncEngine) -> None:
    """POST /auth/refresh for a deleted user returns 401."""
    from fastapi.testclient import TestClient

    client = TestClient(app, follow_redirects=False)

    # Create user via callback
    respx.post("https://accounts.spotify.com/api/token").mock(
        return_value=httpx.Response(200, json=MOCK_TOKEN_RESPONSE)
    )
    respx.get("https://api.spotify.com/v1/me").mock(return_value=httpx.Response(200, json=MOCK_PROFILE_RESPONSE))
    state = _make_state()
    cb_resp = client.get(f"/auth/callback?code=test-code&state={state}")
    refresh_token = cb_resp.json()["refresh_token"]

    # Delete the user directly from DB.
    # SQLite doesn't enforce ON DELETE CASCADE by default, so delete related
    # records (SpotifyToken, SyncCheckpoint, UserRole) before the user.
    import asyncio

    from shared.db.models.operations import SyncCheckpoint
    from shared.db.models.rbac import UserRole
    from shared.db.models.user import SpotifyToken as SpotifyTokenModel

    async def _delete_user() -> None:
        factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            result = await session.execute(select(User))
            user = result.scalar_one()
            # Delete related records first (SQLite cascade workaround)
            await session.execute(select(SpotifyTokenModel).where(SpotifyTokenModel.user_id == user.id))
            from sqlalchemy import delete

            await session.execute(delete(SpotifyTokenModel).where(SpotifyTokenModel.user_id == user.id))
            await session.execute(delete(SyncCheckpoint).where(SyncCheckpoint.user_id == user.id))
            await session.execute(delete(UserRole).where(UserRole.user_id == user.id))
            await session.delete(user)
            await session.commit()

    asyncio.get_event_loop().run_until_complete(_delete_user())

    resp = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 401
    assert "User not found" in resp.json()["detail"]


def test_logout_clears_cookies(override_deps: None) -> None:
    """POST /auth/logout clears auth cookies."""
    from fastapi.testclient import TestClient

    client = TestClient(app, follow_redirects=False)
    resp = client.post("/auth/logout")
    assert resp.status_code == 200
    assert resp.json()["message"] == "Logged out"

    # Cookies should be cleared (max-age=0 in Set-Cookie headers)
    set_cookies = resp.headers.get_list("set-cookie")
    cookie_names = [c.split("=")[0] for c in set_cookies]
    assert "access_token" in cookie_names
    assert "refresh_token" in cookie_names


@respx.mock
async def test_new_user_gets_user_role(override_deps: None, async_engine: AsyncEngine) -> None:
    """New user created via callback gets the 'user' role assigned."""
    from fastapi.testclient import TestClient

    # Seed the 'user' role
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        role = Role(name="user", description="Standard user", is_system=True)
        perm = Permission(codename="own_data.view", description="View own data")
        session.add_all([role, perm])
        await session.flush()
        session.add(RolePermission(role_id=role.id, permission_id=perm.id))
        await session.commit()

    client = TestClient(app, follow_redirects=False)
    respx.post("https://accounts.spotify.com/api/token").mock(
        return_value=httpx.Response(200, json=MOCK_TOKEN_RESPONSE)
    )
    respx.get("https://api.spotify.com/v1/me").mock(return_value=httpx.Response(200, json=MOCK_PROFILE_RESPONSE))
    state = _make_state()
    cb_resp = client.get(f"/auth/callback?code=test-code&state={state}")
    assert cb_resp.status_code == 200
    assert cb_resp.json()["is_new_user"] is True

    # Verify the user has the 'user' role
    async with factory() as session:
        user_result = await session.execute(select(User).where(User.spotify_user_id == "testuser123"))
        user = user_result.scalar_one()
        role_result = await session.execute(select(UserRole).where(UserRole.user_id == user.id))
        user_roles = role_result.scalars().all()
        assert len(user_roles) == 1
