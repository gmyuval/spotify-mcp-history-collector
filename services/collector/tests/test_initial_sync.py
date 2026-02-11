"""Tests for InitialSyncService."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from collector.initial_sync import InitialSyncService
from collector.settings import CollectorSettings
from shared.crypto import TokenEncryptor
from shared.db.base import Base
from shared.db.enums import JobStatus, JobType, SyncStatus
from shared.db.models.music import Play
from shared.db.models.operations import JobRun, SyncCheckpoint
from shared.db.models.user import SpotifyToken, User
from shared.spotify.exceptions import SpotifyRateLimitError
from shared.spotify.models import (
    RecentlyPlayedResponse,
    SpotifyArtistSimplified,
    SpotifyPlayHistoryItem,
    SpotifyTrack,
)

TEST_FERNET_KEY = Fernet.generate_key().decode()


def _test_settings(**overrides: object) -> CollectorSettings:
    defaults: dict[str, object] = {
        "SPOTIFY_CLIENT_ID": "test-id",
        "SPOTIFY_CLIENT_SECRET": "test-secret",
        "TOKEN_ENCRYPTION_KEY": TEST_FERNET_KEY,
        "INITIAL_SYNC_MAX_DAYS": 30,
        "INITIAL_SYNC_MAX_REQUESTS": 200,
    }
    defaults.update(overrides)
    return CollectorSettings(**defaults)  # type: ignore[arg-type]


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


def _make_batch(played_at_base: datetime, count: int = 2, track_offset: int = 0) -> RecentlyPlayedResponse:
    """Create a RecentlyPlayedResponse with `count` items starting from played_at_base."""
    items = []
    for i in range(count):
        items.append(
            SpotifyPlayHistoryItem(
                track=SpotifyTrack(
                    id=f"t{track_offset + i}",
                    name=f"Track {track_offset + i}",
                    duration_ms=200000,
                    artists=[SpotifyArtistSimplified(id=f"a{track_offset + i}", name=f"Artist {track_offset + i}")],
                ),
                played_at=played_at_base - timedelta(minutes=i * 5),
            )
        )
    return RecentlyPlayedResponse(items=items)


async def test_initial_sync_happy_path(async_session: AsyncSession) -> None:
    """Two batches then empty batch → sync completed, checkpoint updated."""
    user = await _create_user_with_token(async_session)
    settings = _test_settings()
    service = InitialSyncService(settings)

    now = datetime.now(UTC)
    batch1 = _make_batch(now - timedelta(hours=1), count=2, track_offset=0)
    batch2 = _make_batch(now - timedelta(hours=2), count=2, track_offset=10)
    empty = RecentlyPlayedResponse(items=[])

    with (
        patch.object(service._token_manager, "get_valid_token", new_callable=AsyncMock, return_value="token"),
        patch("collector.initial_sync.SpotifyClient") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_client.get_recently_played = AsyncMock(side_effect=[batch1, batch2, empty])
        mock_cls.return_value = mock_client

        inserted, skipped = await service.sync_user(user.id, async_session)

    assert inserted == 4
    assert skipped == 0

    # Verify checkpoint
    result = await async_session.execute(select(SyncCheckpoint).where(SyncCheckpoint.user_id == user.id))
    cp = result.scalar_one()
    assert cp.initial_sync_completed_at is not None
    assert cp.initial_sync_started_at is not None
    assert cp.initial_sync_earliest_played_at is not None
    assert cp.status == SyncStatus.IDLE

    # Verify plays
    result = await async_session.execute(select(Play).where(Play.user_id == user.id))
    assert len(result.scalars().all()) == 4

    # Verify job run
    result = await async_session.execute(select(JobRun).where(JobRun.user_id == user.id))
    job = result.scalar_one()
    assert job.job_type == JobType.INITIAL_SYNC
    assert job.status == JobStatus.SUCCESS
    assert job.records_inserted == 4


async def test_stop_on_empty_batch(async_session: AsyncSession) -> None:
    """Empty first batch stops immediately."""
    user = await _create_user_with_token(async_session)
    service = InitialSyncService(_test_settings())

    with (
        patch.object(service._token_manager, "get_valid_token", new_callable=AsyncMock, return_value="token"),
        patch("collector.initial_sync.SpotifyClient") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_client.get_recently_played = AsyncMock(return_value=RecentlyPlayedResponse(items=[]))
        mock_cls.return_value = mock_client

        inserted, skipped = await service.sync_user(user.id, async_session)

    assert inserted == 0
    assert skipped == 0

    # Checkpoint should still be marked completed
    result = await async_session.execute(select(SyncCheckpoint).where(SyncCheckpoint.user_id == user.id))
    cp = result.scalar_one()
    assert cp.initial_sync_completed_at is not None


async def test_stop_on_no_progress(async_session: AsyncSession) -> None:
    """If oldest played_at doesn't advance, stop."""
    user = await _create_user_with_token(async_session)
    service = InitialSyncService(_test_settings())

    # Both batches have the same oldest played_at (recent dates to avoid max_days)
    same_time = datetime.now(UTC) - timedelta(hours=1)
    batch1 = _make_batch(same_time, count=1, track_offset=0)
    batch2 = _make_batch(same_time, count=1, track_offset=10)

    with (
        patch.object(service._token_manager, "get_valid_token", new_callable=AsyncMock, return_value="token"),
        patch("collector.initial_sync.SpotifyClient") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_client.get_recently_played = AsyncMock(side_effect=[batch1, batch2])
        mock_cls.return_value = mock_client

        inserted, skipped = await service.sync_user(user.id, async_session)

    # First batch inserted (1 item). Second batch has same oldest played_at → no-progress stop.
    # The second batch items are still processed before the no-progress check triggers on
    # the *next* iteration, but batch2 has same played_at + different track → inserted not skipped.
    assert inserted == 2
    assert skipped == 0


async def test_stop_on_max_days(async_session: AsyncSession) -> None:
    """Stop when oldest played_at exceeds MAX_DAYS."""
    user = await _create_user_with_token(async_session)
    settings = _test_settings(INITIAL_SYNC_MAX_DAYS=7)
    service = InitialSyncService(settings)

    # Batch with items older than 7 days
    old_time = datetime.now(UTC) - timedelta(days=10)
    batch = _make_batch(old_time, count=2, track_offset=0)

    with (
        patch.object(service._token_manager, "get_valid_token", new_callable=AsyncMock, return_value="token"),
        patch("collector.initial_sync.SpotifyClient") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_client.get_recently_played = AsyncMock(return_value=batch)
        mock_cls.return_value = mock_client

        inserted, skipped = await service.sync_user(user.id, async_session)

    # Batch was still processed before stopping
    assert inserted == 2

    result = await async_session.execute(select(SyncCheckpoint).where(SyncCheckpoint.user_id == user.id))
    cp = result.scalar_one()
    assert cp.initial_sync_completed_at is not None


async def test_stop_on_max_requests(async_session: AsyncSession) -> None:
    """Stop when request count reaches MAX_REQUESTS."""
    user = await _create_user_with_token(async_session)
    settings = _test_settings(INITIAL_SYNC_MAX_REQUESTS=2)
    service = InitialSyncService(settings)

    now = datetime.now(UTC)
    batch1 = _make_batch(now - timedelta(hours=1), count=1, track_offset=0)
    batch2 = _make_batch(now - timedelta(hours=2), count=1, track_offset=10)
    batch3 = _make_batch(now - timedelta(hours=3), count=1, track_offset=20)

    with (
        patch.object(service._token_manager, "get_valid_token", new_callable=AsyncMock, return_value="token"),
        patch("collector.initial_sync.SpotifyClient") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_client.get_recently_played = AsyncMock(side_effect=[batch1, batch2, batch3])
        mock_cls.return_value = mock_client

        inserted, skipped = await service.sync_user(user.id, async_session)

    # Only 2 batches processed (max_requests=2)
    assert inserted == 2

    result = await async_session.execute(select(SyncCheckpoint).where(SyncCheckpoint.user_id == user.id))
    cp = result.scalar_one()
    assert cp.initial_sync_completed_at is not None


async def test_stop_on_rate_limit(async_session: AsyncSession) -> None:
    """Stop on SpotifyRateLimitError."""
    user = await _create_user_with_token(async_session)
    service = InitialSyncService(_test_settings())

    with (
        patch.object(service._token_manager, "get_valid_token", new_callable=AsyncMock, return_value="token"),
        patch("collector.initial_sync.SpotifyClient") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_client.get_recently_played = AsyncMock(side_effect=SpotifyRateLimitError(retry_after=30.0))
        mock_cls.return_value = mock_client

        inserted, skipped = await service.sync_user(user.id, async_session)

    assert inserted == 0
    assert skipped == 0

    result = await async_session.execute(select(SyncCheckpoint).where(SyncCheckpoint.user_id == user.id))
    cp = result.scalar_one()
    # NOT marked completed — will retry on next cycle
    assert cp.initial_sync_completed_at is None


async def test_skip_already_completed(async_session: AsyncSession) -> None:
    """If initial sync is already completed, return (0, 0) immediately."""
    user = await _create_user_with_token(async_session)

    # Pre-create a completed checkpoint
    checkpoint = SyncCheckpoint(
        user_id=user.id,
        initial_sync_completed_at=datetime(2024, 1, 1),
    )
    async_session.add(checkpoint)
    await async_session.flush()

    service = InitialSyncService(_test_settings())
    inserted, skipped = await service.sync_user(user.id, async_session)

    assert inserted == 0
    assert skipped == 0
