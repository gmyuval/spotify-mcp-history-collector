"""Tests for admin authentication middleware."""

import base64
from collections.abc import AsyncGenerator, Generator

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.dependencies import db_manager
from app.main import app
from app.settings import AppSettings, get_settings
from shared.db.base import Base

TEST_FERNET_KEY = Fernet.generate_key().decode()
ADMIN_TOKEN = "test-admin-token-secret"
ADMIN_USER = "admin"
ADMIN_PASS = "admin-pass"


def _settings_disabled() -> AppSettings:
    return AppSettings(
        SPOTIFY_CLIENT_ID="test",
        SPOTIFY_CLIENT_SECRET="test",
        TOKEN_ENCRYPTION_KEY=TEST_FERNET_KEY,
        ADMIN_AUTH_MODE="",
    )


def _settings_token() -> AppSettings:
    return AppSettings(
        SPOTIFY_CLIENT_ID="test",
        SPOTIFY_CLIENT_SECRET="test",
        TOKEN_ENCRYPTION_KEY=TEST_FERNET_KEY,
        ADMIN_AUTH_MODE="token",
        ADMIN_TOKEN=ADMIN_TOKEN,
    )


def _settings_basic() -> AppSettings:
    return AppSettings(
        SPOTIFY_CLIENT_ID="test",
        SPOTIFY_CLIENT_SECRET="test",
        TOKEN_ENCRYPTION_KEY=TEST_FERNET_KEY,
        ADMIN_AUTH_MODE="basic",
        ADMIN_USERNAME=ADMIN_USER,
        ADMIN_PASSWORD=ADMIN_PASS,
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


def _make_client(async_engine: AsyncEngine, settings_fn: type) -> tuple[TestClient, Generator[None]]:
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_session() -> AsyncGenerator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[db_manager.dependency] = _override_session
    app.dependency_overrides[get_settings] = settings_fn
    return TestClient(app)


@pytest.fixture
def cleanup() -> Generator[None]:
    yield
    app.dependency_overrides.clear()


# --- Disabled mode ---


def test_auth_disabled_allows_all(async_engine: AsyncEngine, cleanup: None) -> None:
    client = _make_client(async_engine, _settings_disabled)
    resp = client.get("/admin/users")
    assert resp.status_code == 200


# --- Token mode ---


def test_token_auth_valid(async_engine: AsyncEngine, cleanup: None) -> None:
    client = _make_client(async_engine, _settings_token)
    resp = client.get("/admin/users", headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
    assert resp.status_code == 200


def test_token_auth_missing_header(async_engine: AsyncEngine, cleanup: None) -> None:
    client = _make_client(async_engine, _settings_token)
    resp = client.get("/admin/users")
    assert resp.status_code == 401


def test_token_auth_wrong_token(async_engine: AsyncEngine, cleanup: None) -> None:
    client = _make_client(async_engine, _settings_token)
    resp = client.get("/admin/users", headers={"Authorization": "Bearer wrong-token"})
    assert resp.status_code == 401


def test_token_auth_wrong_scheme(async_engine: AsyncEngine, cleanup: None) -> None:
    client = _make_client(async_engine, _settings_token)
    resp = client.get("/admin/users", headers={"Authorization": f"Basic {ADMIN_TOKEN}"})
    assert resp.status_code == 401


# --- Basic auth mode ---


def _basic_header(user: str, password: str) -> dict[str, str]:
    encoded = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {encoded}"}


def test_basic_auth_valid(async_engine: AsyncEngine, cleanup: None) -> None:
    client = _make_client(async_engine, _settings_basic)
    resp = client.get("/admin/users", headers=_basic_header(ADMIN_USER, ADMIN_PASS))
    assert resp.status_code == 200


def test_basic_auth_wrong_password(async_engine: AsyncEngine, cleanup: None) -> None:
    client = _make_client(async_engine, _settings_basic)
    resp = client.get("/admin/users", headers=_basic_header(ADMIN_USER, "wrong"))
    assert resp.status_code == 401


def test_basic_auth_missing_header(async_engine: AsyncEngine, cleanup: None) -> None:
    client = _make_client(async_engine, _settings_basic)
    resp = client.get("/admin/users")
    assert resp.status_code == 401


# --- MCP auth ---


def test_mcp_tools_requires_auth(async_engine: AsyncEngine, cleanup: None) -> None:
    """GET /mcp/tools requires Bearer token auth (defense-in-depth)."""
    client = _make_client(async_engine, _settings_token)
    resp = client.get("/mcp/tools")
    assert resp.status_code == 401


def test_mcp_call_requires_auth(async_engine: AsyncEngine, cleanup: None) -> None:
    """POST /mcp/call should require auth."""
    client = _make_client(async_engine, _settings_token)
    resp = client.post("/mcp/call", json={"tool": "ops.sync_status", "args": {"user_id": 1}})
    assert resp.status_code == 401


def test_mcp_call_with_auth(async_engine: AsyncEngine, cleanup: None) -> None:
    """POST /mcp/call with valid token should work."""
    client = _make_client(async_engine, _settings_token)
    resp = client.post(
        "/mcp/call",
        json={"tool": "ops.sync_status", "args": {"user_id": 1}},
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    # Should get 200 (tool may return error in body but HTTP is 200)
    assert resp.status_code == 200
