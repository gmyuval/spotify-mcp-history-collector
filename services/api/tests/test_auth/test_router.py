"""Tests for OAuth router endpoints."""

from unittest.mock import patch

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.state import OAuthStateManager
from app.dependencies import db_manager
from app.main import app
from app.settings import AppSettings, get_settings
from shared.db.base import Base

TEST_FERNET_KEY = Fernet.generate_key().decode()


def _test_settings() -> AppSettings:
    return AppSettings(
        SPOTIFY_CLIENT_ID="test-client-id",
        SPOTIFY_CLIENT_SECRET="test-client-secret",
        SPOTIFY_REDIRECT_URI="http://localhost:8000/auth/callback",
        TOKEN_ENCRYPTION_KEY=TEST_FERNET_KEY,
    )


@pytest.fixture
async def async_engine():  # type: ignore[no-untyped-def]
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def override_deps(async_engine):  # type: ignore[no-untyped-def]
    """Override FastAPI dependencies for testing."""
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_session():  # type: ignore[no-untyped-def]
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[db_manager.dependency] = _override_session
    app.dependency_overrides[get_settings] = _test_settings

    # Reset in-memory rate limiter to avoid 429s from accumulated test hits.
    from app.middleware import RateLimitMiddleware

    for mw in app.user_middleware:
        if mw.cls is RateLimitMiddleware:
            mw.kwargs.setdefault("auth_limit", 10)
            break
    # Walk the ASGI app stack to find the live middleware instance.
    current = app.middleware_stack
    while current is not None:
        if isinstance(current, RateLimitMiddleware):
            current._hits.clear()
            break
        current = getattr(current, "app", None)

    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client(override_deps) -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(app, follow_redirects=False)


def _make_state() -> str:
    """Generate a valid OAuth state using test settings."""
    settings = _test_settings()
    mgr = OAuthStateManager(key=settings.TOKEN_ENCRYPTION_KEY, ttl_seconds=settings.OAUTH_STATE_TTL_SECONDS)
    return mgr.generate()


MOCK_TOKEN_RESPONSE = {
    "access_token": "mock-access-token",
    "token_type": "Bearer",
    "expires_in": 3600,
    "refresh_token": "mock-refresh-token",
    "scope": "user-read-recently-played user-top-read user-read-email user-read-private",
}

MOCK_PROFILE_RESPONSE = {
    "id": "testuser123",
    "display_name": "Test User",
    "email": "test@example.com",
    "country": "US",
    "product": "premium",
}


def test_login_redirects_to_spotify(client: TestClient) -> None:
    """GET /auth/login returns a redirect to Spotify authorize URL."""
    response = client.get("/auth/login")
    assert response.status_code == 307
    location = response.headers["location"]
    assert "accounts.spotify.com/authorize" in location
    assert "client_id=test-client-id" in location
    assert "response_type=code" in location
    assert "state=" in location


@respx.mock
def test_callback_success(client: TestClient) -> None:
    """Successful callback creates user, token, and sync checkpoint."""
    respx.post("https://accounts.spotify.com/api/token").mock(
        return_value=httpx.Response(200, json=MOCK_TOKEN_RESPONSE)
    )
    respx.get("https://api.spotify.com/v1/me").mock(return_value=httpx.Response(200, json=MOCK_PROFILE_RESPONSE))

    state = _make_state()
    response = client.get(f"/auth/callback?code=test-auth-code&state={state}")
    assert response.status_code == 200

    data = response.json()
    assert data["message"] == "Authorization successful"
    assert data["user"]["spotify_user_id"] == "testuser123"
    assert data["is_new_user"] is True
    # JWT fields present in response
    assert data["access_token"] is not None
    assert data["refresh_token"] is not None
    assert data["expires_in"] is not None

    # Call again to test upsert (existing user)
    respx.post("https://accounts.spotify.com/api/token").mock(
        return_value=httpx.Response(200, json=MOCK_TOKEN_RESPONSE)
    )
    respx.get("https://api.spotify.com/v1/me").mock(return_value=httpx.Response(200, json=MOCK_PROFILE_RESPONSE))
    state2 = _make_state()
    response2 = client.get(f"/auth/callback?code=test-auth-code2&state={state2}")
    assert response2.status_code == 200
    assert response2.json()["is_new_user"] is False


def test_callback_invalid_state(client: TestClient) -> None:
    """Bad state parameter returns 400."""
    response = client.get("/auth/callback?code=test-code&state=invalid-state")
    assert response.status_code == 400
    assert "Invalid or expired state" in response.json()["detail"]


def test_callback_expired_state(client: TestClient) -> None:
    """Expired state parameter returns 400."""
    settings = _test_settings()
    mgr = OAuthStateManager(key=settings.TOKEN_ENCRYPTION_KEY, ttl_seconds=settings.OAUTH_STATE_TTL_SECONDS)
    with patch("app.auth.state.time") as mock_time:
        mock_time.time.return_value = 1000000.0
        state = mgr.generate()
    response = client.get(f"/auth/callback?code=test-code&state={state}")
    assert response.status_code == 400


@respx.mock
def test_callback_spotify_token_error(client: TestClient) -> None:
    """Spotify token endpoint error returns 502 with descriptive detail."""
    state = _make_state()
    respx.post("https://accounts.spotify.com/api/token").mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )

    response = client.get(f"/auth/callback?code=bad-code&state={state}")
    assert response.status_code == 502
    assert "exchange authorization code" in response.json()["detail"]


@respx.mock
def test_callback_spotify_profile_error(client: TestClient) -> None:
    """Spotify profile endpoint error returns 502 with descriptive detail."""
    state = _make_state()
    respx.post("https://accounts.spotify.com/api/token").mock(
        return_value=httpx.Response(200, json=MOCK_TOKEN_RESPONSE)
    )
    respx.get("https://api.spotify.com/v1/me").mock(
        return_value=httpx.Response(401, json={"error": {"message": "Invalid token"}})
    )

    response = client.get(f"/auth/callback?code=test-code&state={state}")
    assert response.status_code == 502
    assert "fetch user profile" in response.json()["detail"]
