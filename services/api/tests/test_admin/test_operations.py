"""Tests for admin operational endpoints — sync status, job runs, import jobs."""

from collections.abc import AsyncGenerator, Generator
from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.dependencies import db_manager
from app.main import app
from app.settings import AppSettings, get_settings
from shared.db.base import Base
from shared.db.enums import ImportStatus, JobStatus, JobType, SyncStatus
from shared.db.models.operations import ImportJob, JobRun, SyncCheckpoint
from shared.db.models.user import User

TEST_FERNET_KEY = Fernet.generate_key().decode()


def _test_settings() -> AppSettings:
    return AppSettings(
        SPOTIFY_CLIENT_ID="test",
        SPOTIFY_CLIENT_SECRET="test",
        TOKEN_ENCRYPTION_KEY=TEST_FERNET_KEY,
        ADMIN_AUTH_MODE="",
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
async def seeded_data(async_engine: AsyncEngine) -> int:
    """Create a user with sync checkpoint, job runs, and import jobs. Returns user_id."""
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        user = User(spotify_user_id="opuser", display_name="Ops User")
        session.add(user)
        await session.flush()

        cp = SyncCheckpoint(user_id=user.id, status=SyncStatus.IDLE)
        session.add(cp)

        # Job runs
        session.add_all(
            [
                JobRun(
                    user_id=user.id,
                    job_type=JobType.POLL,
                    status=JobStatus.SUCCESS,
                    records_fetched=10,
                    records_inserted=5,
                    records_skipped=5,
                    started_at=datetime(2026, 1, 10, 10, 0, tzinfo=UTC),
                    completed_at=datetime(2026, 1, 10, 10, 1, tzinfo=UTC),
                ),
                JobRun(
                    user_id=user.id,
                    job_type=JobType.INITIAL_SYNC,
                    status=JobStatus.ERROR,
                    error_message="Rate limited",
                    started_at=datetime(2026, 1, 9, 8, 0, tzinfo=UTC),
                ),
            ]
        )

        # Import job
        session.add(
            ImportJob(
                user_id=user.id,
                status=ImportStatus.SUCCESS,
                file_path="/uploads/test.zip",
                file_size_bytes=1024,
                records_ingested=100,
            )
        )

        await session.commit()
        return user.id


# --- Global Sync Status ---


def test_sync_status(client: TestClient, seeded_data: int) -> None:
    resp = client.get("/admin/sync-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_users"] == 1
    assert data["active_syncs"] == 0
    assert data["error_users"] == 0
    assert len(data["recent_errors"]) == 1  # The error job run
    assert data["recent_errors"][0]["error_message"] == "Rate limited"


def test_sync_status_empty(client: TestClient) -> None:
    resp = client.get("/admin/sync-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_users"] == 0
    assert data["recent_errors"] == []


# --- Job Runs ---


def test_list_job_runs(client: TestClient, seeded_data: int) -> None:
    resp = client.get("/admin/job-runs")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2


def test_list_job_runs_filter_type(client: TestClient, seeded_data: int) -> None:
    resp = client.get("/admin/job-runs?job_type=poll")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["job_type"] == "poll"


def test_list_job_runs_filter_status(client: TestClient, seeded_data: int) -> None:
    resp = client.get("/admin/job-runs?status=error")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["error_message"] == "Rate limited"


def test_list_job_runs_filter_user(client: TestClient, seeded_data: int) -> None:
    resp = client.get(f"/admin/job-runs?user_id={seeded_data}")
    assert resp.status_code == 200
    assert resp.json()["total"] == 2


def test_list_job_runs_empty(client: TestClient) -> None:
    resp = client.get("/admin/job-runs?user_id=9999")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


# --- Import Jobs ---


def test_list_import_jobs(client: TestClient, seeded_data: int) -> None:
    resp = client.get("/admin/import-jobs")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["records_ingested"] == 100


def test_list_import_jobs_filter_status(client: TestClient, seeded_data: int) -> None:
    resp = client.get("/admin/import-jobs?status=success")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_list_import_jobs_pagination(client: TestClient, seeded_data: int) -> None:
    resp = client.get("/admin/import-jobs?limit=1&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["limit"] == 1
