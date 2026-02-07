"""Tests for TokenManager."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.crypto import TokenEncryptor
from app.auth.exceptions import TokenNotFoundError, TokenRefreshError
from app.auth.tokens import TokenManager
from app.settings import AppSettings
from shared.db.base import Base
from shared.db.models.user import SpotifyToken, User

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
async def async_session(async_engine):  # type: ignore[no-untyped-def]
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session


async def _create_user_with_token(
    session: AsyncSession,
    access_token: str = "existing-access-token",
    expires_at: datetime | None = None,
    refresh_token: str = "test-refresh-token",
) -> tuple[User, SpotifyToken]:
    """Helper to create a user with a token record."""
    encryptor = TokenEncryptor(TEST_FERNET_KEY)
    user = User(spotify_user_id="testuser", display_name="Test")
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


async def test_get_valid_token_returns_cached(async_session: AsyncSession) -> None:
    """When token is not expired, returns existing access token without refresh."""
    user, _token = await _create_user_with_token(
        async_session,
        access_token="valid-token",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    manager = TokenManager(_test_settings())
    result = await manager.get_valid_token(user.id, async_session)
    assert result == "valid-token"


@respx.mock
async def test_get_valid_token_refreshes_expired(async_session: AsyncSession) -> None:
    """When token is expired, refreshes and returns new token."""
    user, _token = await _create_user_with_token(
        async_session,
        access_token="expired-token",
        expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    manager = TokenManager(_test_settings())

    respx.post("https://accounts.spotify.com/api/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "new-access-token",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        )
    )

    result = await manager.get_valid_token(user.id, async_session)
    assert result == "new-access-token"


@respx.mock
async def test_refresh_updates_db(async_session: AsyncSession) -> None:
    """After refresh, DB has new access token and expiry."""
    user, token_record = await _create_user_with_token(
        async_session,
        access_token="old-token",
        expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    manager = TokenManager(_test_settings())

    respx.post("https://accounts.spotify.com/api/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "refreshed-token",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        )
    )

    result = await manager.refresh_access_token(user.id, async_session)
    assert result == "refreshed-token"

    # Verify the DB record was updated
    assert token_record.access_token == "refreshed-token"
    assert token_record.token_expires_at is not None
    assert token_record.token_expires_at > datetime.now(UTC)


@respx.mock
async def test_refresh_with_new_refresh_token(async_session: AsyncSession) -> None:
    """When Spotify returns a new refresh token, it gets encrypted and stored."""
    user, token_record = await _create_user_with_token(
        async_session,
        access_token="old-token",
        expires_at=datetime.now(UTC) - timedelta(minutes=5),
        refresh_token="original-refresh-token",
    )
    old_encrypted = token_record.encrypted_refresh_token
    manager = TokenManager(_test_settings())

    respx.post("https://accounts.spotify.com/api/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "new-access-token",
                "token_type": "Bearer",
                "expires_in": 3600,
                "refresh_token": "brand-new-refresh-token",
            },
        )
    )

    await manager.refresh_access_token(user.id, async_session)

    # The encrypted refresh token should have changed
    assert token_record.encrypted_refresh_token != old_encrypted


async def test_get_valid_token_no_token_raises(async_session: AsyncSession) -> None:
    """Raises TokenNotFoundError when no token exists for the user."""
    manager = TokenManager(_test_settings())
    with pytest.raises(TokenNotFoundError, match="No token found"):
        await manager.get_valid_token(999, async_session)


@respx.mock
async def test_refresh_spotify_error_raises_token_refresh_error(async_session: AsyncSession) -> None:
    """Raises TokenRefreshError when Spotify returns an error during refresh."""
    user, _token = await _create_user_with_token(
        async_session,
        access_token="old-token",
        expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    manager = TokenManager(_test_settings())

    respx.post("https://accounts.spotify.com/api/token").mock(
        return_value=httpx.Response(401, json={"error": "invalid_client"})
    )

    with pytest.raises(TokenRefreshError, match="HTTP 401"):
        await manager.refresh_access_token(user.id, async_session)
