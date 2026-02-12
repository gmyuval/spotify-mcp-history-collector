"""Tests for admin log viewer and purge endpoints."""

from collections.abc import AsyncGenerator, Generator
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.dependencies import db_manager
from app.main import app
from app.settings import AppSettings, get_settings
from shared.db.base import Base
from shared.db.enums import LogLevel
from shared.db.models.log import Log

TEST_FERNET_KEY = Fernet.generate_key().decode()


def _test_settings() -> AppSettings:
    return AppSettings(
        SPOTIFY_CLIENT_ID="test",
        SPOTIFY_CLIENT_SECRET="test",
        TOKEN_ENCRYPTION_KEY=TEST_FERNET_KEY,
        ADMIN_AUTH_MODE="",
        LOG_RETENTION_DAYS=30,
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
async def seeded_logs(async_engine: AsyncEngine) -> None:
    """Insert sample log entries."""
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        now = datetime.now(UTC)
        session.add_all(
            [
                Log(
                    timestamp=now,
                    service="api",
                    level=LogLevel.INFO,
                    message="Request processed",
                ),
                Log(
                    timestamp=now,
                    service="api",
                    level=LogLevel.ERROR,
                    message="Failed to connect",
                ),
                Log(
                    timestamp=now,
                    service="collector",
                    level=LogLevel.INFO,
                    message="Poll completed",
                ),
                Log(
                    timestamp=now - timedelta(days=60),
                    service="api",
                    level=LogLevel.WARNING,
                    message="Old warning log",
                ),
            ]
        )
        await session.commit()


# --- Log Queries ---


def test_list_logs(client: TestClient, seeded_logs: None) -> None:
    resp = client.get("/admin/logs")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 4
    assert len(data["items"]) == 4


def test_list_logs_filter_service(client: TestClient, seeded_logs: None) -> None:
    resp = client.get("/admin/logs?service=collector")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["message"] == "Poll completed"


def test_list_logs_filter_level(client: TestClient, seeded_logs: None) -> None:
    resp = client.get("/admin/logs?level=error")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["message"] == "Failed to connect"


def test_list_logs_text_search(client: TestClient, seeded_logs: None) -> None:
    resp = client.get("/admin/logs?q=connect")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_list_logs_empty(client: TestClient) -> None:
    resp = client.get("/admin/logs")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


# --- Purge ---


def test_purge_logs(client: TestClient, seeded_logs: None) -> None:
    """Purge should remove logs older than specified days."""
    resp = client.post("/admin/maintenance/purge-logs?older_than_days=30")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "1" in data["message"]  # 1 log older than 30 days

    # Verify remaining logs
    logs_resp = client.get("/admin/logs")
    assert logs_resp.json()["total"] == 3


def test_purge_logs_default_retention(client: TestClient, seeded_logs: None) -> None:
    """Purge without param uses LOG_RETENTION_DAYS from settings."""
    resp = client.post("/admin/maintenance/purge-logs")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
