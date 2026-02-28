"""Tests for ops tools invoked through the MCP dispatcher."""

from collections.abc import AsyncGenerator, Generator
from datetime import datetime

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
        RATE_LIMIT_MCP_PER_MINUTE=10000,
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
def override_deps(async_engine: AsyncEngine) -> Generator[None]:
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async def _override() -> AsyncGenerator[AsyncSession]:
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[db_manager.dependency] = _override
    app.dependency_overrides[get_settings] = _test_settings
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client(override_deps: None) -> TestClient:
    return TestClient(app)


@pytest.fixture
async def seeded_user(async_engine: AsyncEngine) -> int:
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        user = User(spotify_user_id="opsuser", display_name="Ops")
        session.add(user)
        await session.flush()

        # SyncCheckpoint
        session.add(
            SyncCheckpoint(
                user_id=user.id,
                status=SyncStatus.IDLE,
                initial_sync_completed_at=datetime(2026, 1, 1),
                last_poll_completed_at=datetime(2026, 2, 1, 10, 0),
            )
        )

        # JobRun
        session.add(
            JobRun(
                user_id=user.id,
                job_type=JobType.POLL,
                status=JobStatus.SUCCESS,
                started_at=datetime(2026, 2, 1, 10, 0),
                completed_at=datetime(2026, 2, 1, 10, 1),
                records_fetched=5,
                records_inserted=3,
                records_skipped=2,
            )
        )

        # ImportJob
        session.add(
            ImportJob(
                user_id=user.id,
                status=ImportStatus.SUCCESS,
                file_path="/uploads/test.zip",
                file_size_bytes=1024,
                records_ingested=100,
                completed_at=datetime(2026, 1, 15),
            )
        )

        await session.flush()
        uid = user.id
        await session.commit()
    return uid


def test_ops_sync_status(client: TestClient, seeded_user: int) -> None:
    resp = client.post(
        "/mcp/call",
        json={"tool": "ops.sync_status", "args": {"user_id": seeded_user}},
    )
    data = resp.json()
    assert data["success"]
    assert data["result"]["status"] == "idle"
    assert data["result"]["initial_sync_completed_at"] is not None


def test_ops_latest_job_runs(client: TestClient, seeded_user: int) -> None:
    resp = client.post(
        "/mcp/call",
        json={"tool": "ops.latest_job_runs", "args": {"user_id": seeded_user, "limit": 5}},
    )
    data = resp.json()
    assert data["success"]
    assert len(data["result"]) == 1
    assert data["result"][0]["job_type"] == "poll"
    assert data["result"][0]["records_inserted"] == 3


def test_ops_latest_import_jobs(client: TestClient, seeded_user: int) -> None:
    resp = client.post(
        "/mcp/call",
        json={"tool": "ops.latest_import_jobs", "args": {"user_id": seeded_user}},
    )
    data = resp.json()
    assert data["success"]
    assert len(data["result"]) == 1
    assert data["result"][0]["records_ingested"] == 100
    assert data["result"][0]["status"] == "success"


def test_ops_sync_status_no_data(client: TestClient) -> None:
    resp = client.post(
        "/mcp/call",
        json={"tool": "ops.sync_status", "args": {"user_id": 99999}},
    )
    data = resp.json()
    assert data["success"]
    assert data["result"]["status"] == "no_checkpoint"
