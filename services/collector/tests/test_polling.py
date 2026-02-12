"""Tests for PollingService."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from collector.polling import PollingService
from collector.settings import CollectorSettings
from shared.crypto import TokenEncryptor
from shared.db.base import Base
from shared.db.models.music import Play
from shared.db.models.operations import SyncCheckpoint
from shared.db.models.user import SpotifyToken, User
from shared.spotify.models import (
    RecentlyPlayedResponse,
    SpotifyArtistSimplified,
    SpotifyPlayHistoryItem,
    SpotifyTrack,
)

TEST_FERNET_KEY = Fernet.generate_key().decode()


def _test_settings() -> CollectorSettings:
    return CollectorSettings(
        SPOTIFY_CLIENT_ID="test-client-id",
        SPOTIFY_CLIENT_SECRET="test-client-secret",
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


async def _create_user_with_token(session: AsyncSession) -> User:
    encryptor = TokenEncryptor(TEST_FERNET_KEY)
    user = User(spotify_user_id="testuser", display_name="Test")
    session.add(user)
    await session.flush()

    token = SpotifyToken(
        user_id=user.id,
        encrypted_refresh_token=encryptor.encrypt("refresh-token"),
        access_token="valid-access-token",
        token_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    session.add(token)
    await session.flush()
    return user


def _recently_played_response() -> RecentlyPlayedResponse:
    return RecentlyPlayedResponse(
        items=[
            SpotifyPlayHistoryItem(
                track=SpotifyTrack(
                    id="t1",
                    name="Track 1",
                    duration_ms=200000,
                    artists=[SpotifyArtistSimplified(id="a1", name="Artist 1")],
                ),
                played_at=datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC),
            ),
            SpotifyPlayHistoryItem(
                track=SpotifyTrack(
                    id="t2",
                    name="Track 2",
                    duration_ms=180000,
                    artists=[SpotifyArtistSimplified(id="a2", name="Artist 2")],
                ),
                played_at=datetime(2024, 1, 15, 10, 25, 0, tzinfo=UTC),
            ),
        ]
    )


async def test_poll_user_end_to_end(async_session: AsyncSession) -> None:
    """Full poll_user flow: fetch, upsert, update checkpoint."""
    user = await _create_user_with_token(async_session)
    service = PollingService(_test_settings())

    mock_response = _recently_played_response()

    with (
        patch.object(service._token_manager, "get_valid_token", new_callable=AsyncMock, return_value="valid-token"),
        patch("collector.polling.SpotifyClient") as mock_client_cls,
    ):
        mock_client = AsyncMock()
        mock_client.get_recently_played = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        inserted, skipped = await service.poll_user(user.id, async_session)

    assert inserted == 2
    assert skipped == 0

    # Verify plays were inserted
    result = await async_session.execute(select(Play).where(Play.user_id == user.id))
    plays = result.scalars().all()
    assert len(plays) == 2

    # Verify checkpoint was updated
    result = await async_session.execute(select(SyncCheckpoint).where(SyncCheckpoint.user_id == user.id))
    checkpoint = result.scalar_one()
    assert checkpoint.last_poll_completed_at is not None
    # SQLite returns naive datetimes; PostgreSQL returns tz-aware. Compare date parts.
    expected = datetime(2024, 1, 15, 10, 30, 0)
    actual = checkpoint.last_poll_latest_played_at
    assert actual is not None
    assert actual.replace(tzinfo=None) == expected


async def test_poll_user_empty_response(async_session: AsyncSession) -> None:
    """Empty response returns (0, 0) without creating checkpoint."""
    user = await _create_user_with_token(async_session)
    service = PollingService(_test_settings())

    with (
        patch.object(service._token_manager, "get_valid_token", new_callable=AsyncMock, return_value="valid-token"),
        patch("collector.polling.SpotifyClient") as mock_client_cls,
    ):
        mock_client = AsyncMock()
        mock_client.get_recently_played = AsyncMock(return_value=RecentlyPlayedResponse(items=[]))
        mock_client_cls.return_value = mock_client

        inserted, skipped = await service.poll_user(user.id, async_session)

    assert inserted == 0
    assert skipped == 0


async def test_poll_user_dedup(async_session: AsyncSession) -> None:
    """Second poll with same items yields all skipped."""
    user = await _create_user_with_token(async_session)
    service = PollingService(_test_settings())

    mock_response = _recently_played_response()

    with (
        patch.object(service._token_manager, "get_valid_token", new_callable=AsyncMock, return_value="valid-token"),
        patch("collector.polling.SpotifyClient") as mock_client_cls,
    ):
        mock_client = AsyncMock()
        mock_client.get_recently_played = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        inserted1, skipped1 = await service.poll_user(user.id, async_session)
        inserted2, skipped2 = await service.poll_user(user.id, async_session)

    assert inserted1 == 2
    assert skipped1 == 0
    assert inserted2 == 0
    assert skipped2 == 2
