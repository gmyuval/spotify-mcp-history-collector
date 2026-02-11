"""Tests for CollectorRunLoop."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from collector.runloop import CollectorRunLoop
from collector.settings import CollectorSettings
from shared.crypto import TokenEncryptor
from shared.db.base import Base
from shared.db.enums import SyncStatus
from shared.db.models.operations import SyncCheckpoint
from shared.db.models.user import SpotifyToken, User
from shared.db.session import DatabaseManager

TEST_FERNET_KEY = Fernet.generate_key().decode()


def _test_settings() -> CollectorSettings:
    return CollectorSettings(
        SPOTIFY_CLIENT_ID="test-id",
        SPOTIFY_CLIENT_SECRET="test-secret",
        TOKEN_ENCRYPTION_KEY=TEST_FERNET_KEY,
        COLLECTOR_INTERVAL_SECONDS=1,
        INITIAL_SYNC_CONCURRENCY=2,
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
    spotify_user_id: str = "testuser",
) -> User:
    encryptor = TokenEncryptor(TEST_FERNET_KEY)
    user = User(spotify_user_id=spotify_user_id, display_name="Test")
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


async def test_runs_initial_sync_for_new_user(async_engine, async_session: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    """Run loop should run initial sync for users without completed sync."""
    await _create_user_with_token(async_session)
    await async_session.commit()

    settings = _test_settings()

    # Create a mock DatabaseManager that yields sessions from our test engine
    db_manager = AsyncMock(spec=DatabaseManager)
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _mock_session():  # type: ignore[no-untyped-def]
        async with session_factory() as s:
            yield s
            await s.commit()

    db_manager.session = _mock_session

    run_loop = CollectorRunLoop(settings, db_manager)

    with (
        patch.object(
            run_loop._initial_sync_service, "sync_user", new_callable=AsyncMock, return_value=(10, 0)
        ) as mock_sync,
        patch.object(run_loop._polling_service, "poll_user", new_callable=AsyncMock) as mock_poll,
    ):
        # Run a single cycle
        await run_loop._run_cycle()

    mock_sync.assert_called_once()
    mock_poll.assert_not_called()


async def test_runs_polling_for_synced_user(async_engine, async_session: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    """Run loop should run polling for users with completed initial sync."""
    user = await _create_user_with_token(async_session)
    checkpoint = SyncCheckpoint(
        user_id=user.id,
        initial_sync_completed_at=datetime(2024, 1, 1),
        status=SyncStatus.IDLE,
    )
    async_session.add(checkpoint)
    await async_session.commit()

    settings = _test_settings()

    db_manager = AsyncMock(spec=DatabaseManager)
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _mock_session():  # type: ignore[no-untyped-def]
        async with session_factory() as s:
            yield s
            await s.commit()

    db_manager.session = _mock_session

    run_loop = CollectorRunLoop(settings, db_manager)

    with (
        patch.object(run_loop._initial_sync_service, "sync_user", new_callable=AsyncMock) as mock_sync,
        patch.object(run_loop._polling_service, "poll_user", new_callable=AsyncMock, return_value=(5, 0)) as mock_poll,
    ):
        await run_loop._run_cycle()

    mock_sync.assert_not_called()
    mock_poll.assert_called_once()


async def test_skips_paused_user(async_engine, async_session: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    """Run loop should skip paused users."""
    user = await _create_user_with_token(async_session)
    checkpoint = SyncCheckpoint(
        user_id=user.id,
        status=SyncStatus.PAUSED,
    )
    async_session.add(checkpoint)
    await async_session.commit()

    settings = _test_settings()

    db_manager = AsyncMock(spec=DatabaseManager)
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _mock_session():  # type: ignore[no-untyped-def]
        async with session_factory() as s:
            yield s
            await s.commit()

    db_manager.session = _mock_session

    run_loop = CollectorRunLoop(settings, db_manager)

    with (
        patch.object(run_loop._initial_sync_service, "sync_user", new_callable=AsyncMock) as mock_sync,
        patch.object(run_loop._polling_service, "poll_user", new_callable=AsyncMock) as mock_poll,
    ):
        await run_loop._run_cycle()

    mock_sync.assert_not_called()
    mock_poll.assert_not_called()


async def test_continues_after_user_error(async_engine, async_session: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    """If one user fails, others should still be processed."""
    user1 = await _create_user_with_token(async_session, spotify_user_id="user1")
    user2 = await _create_user_with_token(async_session, spotify_user_id="user2")

    # Both have completed sync → will run polling
    for user in [user1, user2]:
        cp = SyncCheckpoint(
            user_id=user.id,
            initial_sync_completed_at=datetime(2024, 1, 1),
            status=SyncStatus.IDLE,
        )
        async_session.add(cp)
    await async_session.commit()

    settings = _test_settings()

    db_manager = AsyncMock(spec=DatabaseManager)
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _mock_session():  # type: ignore[no-untyped-def]
        async with session_factory() as s:
            yield s
            await s.commit()

    db_manager.session = _mock_session

    run_loop = CollectorRunLoop(settings, db_manager)

    call_count = 0

    async def _poll_side_effect(user_id: int, session: AsyncSession) -> tuple[int, int]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Simulated failure")
        return 5, 0

    with (
        patch.object(run_loop._initial_sync_service, "sync_user", new_callable=AsyncMock),
        patch.object(run_loop._polling_service, "poll_user", side_effect=_poll_side_effect) as mock_poll,
    ):
        await run_loop._run_cycle()

    # Both users were attempted (gather with return_exceptions=True)
    assert mock_poll.call_count == 2


async def test_shutdown_event_stops_loop() -> None:
    """Setting shutdown_event stops the run loop."""
    settings = _test_settings()
    db_manager = AsyncMock(spec=DatabaseManager)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _mock_session():  # type: ignore[no-untyped-def]
        yield AsyncMock()

    db_manager.session = _mock_session

    run_loop = CollectorRunLoop(settings, db_manager)
    shutdown = asyncio.Event()
    shutdown.set()  # Already set → loop should exit immediately

    with patch.object(run_loop, "_run_cycle", new_callable=AsyncMock) as mock_cycle:
        await run_loop.run(shutdown)

    mock_cycle.assert_not_called()
