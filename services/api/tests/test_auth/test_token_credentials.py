"""Tests for TokenManager per-user credential resolution."""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.crypto import TokenEncryptor
from app.auth.tokens import TokenManager
from app.settings import AppSettings
from shared.db.base import Base
from shared.db.models.user import SpotifyToken, User

TEST_FERNET_KEY = Fernet.generate_key().decode()


def _test_settings() -> AppSettings:
    return AppSettings(
        SPOTIFY_CLIENT_ID="system-client-id",
        SPOTIFY_CLIENT_SECRET="system-client-secret",
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
async def async_session(async_engine):  # type: ignore[no-untyped-def]
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session


async def _create_user_with_token(
    session: AsyncSession,
    access_token: str = "existing-access-token",
    expires_at: datetime | None = None,
    refresh_token: str = "test-refresh-token",
    custom_client_id: str | None = None,
    custom_client_secret: str | None = None,
) -> tuple[User, SpotifyToken]:
    """Helper to create a user with a token record and optional custom credentials."""
    encryptor = TokenEncryptor(TEST_FERNET_KEY)
    user = User(spotify_user_id="testuser", display_name="Test")

    if custom_client_id is not None:
        user.custom_spotify_client_id = custom_client_id
    if custom_client_secret is not None:
        user.encrypted_custom_client_secret = encryptor.encrypt(custom_client_secret)

    session.add(user)
    await session.flush()

    token = SpotifyToken(
        user_id=user.id,
        encrypted_refresh_token=encryptor.encrypt(refresh_token),
        access_token=access_token,
        token_expires_at=expires_at or (datetime.now(UTC) + timedelta(hours=1)),
    )
    session.add(token)
    await session.flush()
    return user, token


def _mock_token_response() -> httpx.Response:
    """Return a successful Spotify token refresh response."""
    return httpx.Response(
        200,
        json={
            "access_token": "new-access-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        },
    )


@respx.mock
async def test_refresh_uses_system_credentials_by_default(async_session: AsyncSession) -> None:
    """When user has NO custom credentials, refresh uses system client_id/secret."""
    user, _token = await _create_user_with_token(
        async_session,
        access_token="expired-token",
        expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    manager = TokenManager(_test_settings())

    route = respx.post("https://accounts.spotify.com/api/token").mock(return_value=_mock_token_response())

    result = await manager.refresh_access_token(user.id, async_session)
    assert result == "new-access-token"

    # Verify the request body contains system credentials
    assert route.called
    request = route.calls[0].request
    body = parse_qs(request.content.decode())
    assert body["client_id"] == ["system-client-id"]
    assert body["client_secret"] == ["system-client-secret"]


@respx.mock
async def test_refresh_uses_custom_credentials(async_session: AsyncSession) -> None:
    """When user HAS custom_spotify_client_id and encrypted_custom_client_secret,
    refresh uses those instead of system defaults."""
    user, _token = await _create_user_with_token(
        async_session,
        access_token="expired-token",
        expires_at=datetime.now(UTC) - timedelta(minutes=5),
        custom_client_id="custom-client-id",
        custom_client_secret="custom-client-secret",
    )
    manager = TokenManager(_test_settings())

    route = respx.post("https://accounts.spotify.com/api/token").mock(return_value=_mock_token_response())

    result = await manager.refresh_access_token(user.id, async_session)
    assert result == "new-access-token"

    # Verify the request body contains custom credentials
    assert route.called
    request = route.calls[0].request
    body = parse_qs(request.content.decode())
    assert body["client_id"] == ["custom-client-id"]
    assert body["client_secret"] == ["custom-client-secret"]


@respx.mock
async def test_refresh_falls_back_when_only_client_id_set(async_session: AsyncSession) -> None:
    """If only client_id is set (no secret), falls back to system defaults."""
    user, _token = await _create_user_with_token(
        async_session,
        access_token="expired-token",
        expires_at=datetime.now(UTC) - timedelta(minutes=5),
        custom_client_id="custom-client-id",
        # custom_client_secret is NOT set — left as None
    )
    manager = TokenManager(_test_settings())

    route = respx.post("https://accounts.spotify.com/api/token").mock(return_value=_mock_token_response())

    result = await manager.refresh_access_token(user.id, async_session)
    assert result == "new-access-token"

    # Verify the request body falls back to system credentials
    assert route.called
    request = route.calls[0].request
    body = parse_qs(request.content.decode())
    assert body["client_id"] == ["system-client-id"]
    assert body["client_secret"] == ["system-client-secret"]
