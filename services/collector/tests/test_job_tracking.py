"""Tests for JobTracker."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from collector.job_tracking import JobTracker
from shared.db.base import Base
from shared.db.enums import JobStatus, JobType
from shared.db.models.operations import JobRun
from shared.db.models.user import User


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


async def _create_user(session: AsyncSession) -> User:
    user = User(spotify_user_id="testuser", display_name="Test")
    session.add(user)
    await session.flush()
    return user


async def test_start_job(async_session: AsyncSession) -> None:
    """start_job creates a JobRun with status=running."""
    user = await _create_user(async_session)
    tracker = JobTracker()

    job_run = await tracker.start_job(user.id, JobType.POLL, async_session)

    assert job_run.id is not None
    assert job_run.user_id == user.id
    assert job_run.job_type == JobType.POLL
    assert job_run.status == JobStatus.RUNNING
    assert job_run.started_at is not None
    assert job_run.completed_at is None

    # Verify persisted
    result = await async_session.execute(select(JobRun).where(JobRun.id == job_run.id))
    persisted = result.scalar_one()
    assert persisted.status == JobStatus.RUNNING


async def test_complete_job(async_session: AsyncSession) -> None:
    """complete_job sets status=success and records stats."""
    user = await _create_user(async_session)
    tracker = JobTracker()

    job_run = await tracker.start_job(user.id, JobType.INITIAL_SYNC, async_session)
    await tracker.complete_job(job_run, fetched=100, inserted=90, skipped=10, session=async_session)

    assert job_run.status == JobStatus.SUCCESS
    assert job_run.completed_at is not None
    assert job_run.records_fetched == 100
    assert job_run.records_inserted == 90
    assert job_run.records_skipped == 10

    # completed_at should be after started_at
    assert job_run.completed_at >= job_run.started_at


async def test_fail_job(async_session: AsyncSession) -> None:
    """fail_job sets status=error and records error message."""
    user = await _create_user(async_session)
    tracker = JobTracker()

    job_run = await tracker.start_job(user.id, JobType.POLL, async_session)
    await tracker.fail_job(job_run, "Connection timed out", async_session)

    assert job_run.status == JobStatus.ERROR
    assert job_run.completed_at is not None
    assert job_run.error_message == "Connection timed out"
