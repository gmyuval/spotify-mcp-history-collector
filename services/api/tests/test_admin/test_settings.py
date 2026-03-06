"""Tests for admin settings API endpoints."""

from collections.abc import AsyncGenerator, Generator

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.admin.settings_service import SettingsService, _settings_service
from app.dependencies import db_manager
from app.main import app
from app.settings import AppSettings, get_settings
from shared.db.base import Base

TEST_FERNET_KEY = Fernet.generate_key().decode()


def _test_settings() -> AppSettings:
    return AppSettings(
        SPOTIFY_CLIENT_ID="test",
        SPOTIFY_CLIENT_SECRET="test",
        TOKEN_ENCRYPTION_KEY=TEST_FERNET_KEY,
        ADMIN_AUTH_MODE="",  # Disabled for testing
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
    _settings_service.invalidate_cache()
    yield
    app.dependency_overrides.clear()
    _settings_service.invalidate_cache()


@pytest.fixture
def client(override_deps: None) -> TestClient:
    return TestClient(app)


# ── GET /admin/settings ───────────────────────────────────────────────


class TestListSettings:
    def test_returns_all_categories(self, client: TestClient) -> None:
        resp = client.get("/admin/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "by_category" in data
        by_cat = data["by_category"]
        assert "search" in by_cat
        assert "playlist" in by_cat

    def test_all_default_keys_present(self, client: TestClient) -> None:
        resp = client.get("/admin/settings")
        assert resp.status_code == 200
        by_cat = resp.json()["by_category"]
        all_keys = {s["key"] for cat in by_cat.values() for s in cat}
        for key in SettingsService.DEFAULTS:
            assert key in all_keys, f"Missing key: {key}"

    def test_default_values_returned_when_db_empty(self, client: TestClient) -> None:
        resp = client.get("/admin/settings")
        assert resp.status_code == 200
        by_cat = resp.json()["by_category"]
        search_settings = {s["key"]: s for s in by_cat["search"]}
        assert search_settings["search.default_limit"]["value_json"] == 25
        assert search_settings["search.score_playlist_name"]["value_json"] == 1.0


# ── GET /admin/settings/{key} ─────────────────────────────────────────


class TestGetSetting:
    def test_known_key_returns_default(self, client: TestClient) -> None:
        resp = client.get("/admin/settings/search.default_limit")
        assert resp.status_code == 200
        data = resp.json()
        assert data["key"] == "search.default_limit"
        assert data["value_json"] == 25
        assert data["default_value"] == 25

    def test_unknown_key_returns_404(self, client: TestClient) -> None:
        resp = client.get("/admin/settings/no.such.key")
        assert resp.status_code == 404


# ── PUT /admin/settings/{key} ─────────────────────────────────────────


class TestUpdateSetting:
    def test_update_integer_setting(self, client: TestClient) -> None:
        resp = client.put("/admin/settings/search.default_limit", json={"value_json": 10})
        assert resp.status_code == 200
        data = resp.json()
        assert data["value_json"] == 10

    def test_update_float_setting(self, client: TestClient) -> None:
        resp = client.put("/admin/settings/search.score_playlist_name", json={"value_json": 0.5})
        assert resp.status_code == 200
        assert resp.json()["value_json"] == 0.5

    def test_update_unknown_key_returns_404(self, client: TestClient) -> None:
        resp = client.put("/admin/settings/no.such.key", json={"value_json": 99})
        assert resp.status_code == 404

    def test_update_wrong_type_returns_400(self, client: TestClient) -> None:
        resp = client.put("/admin/settings/search.default_limit", json={"value_json": "not-an-int"})
        assert resp.status_code == 400
        assert "expects an integer" in resp.json()["detail"]

    def test_update_below_min_bound_returns_400(self, client: TestClient) -> None:
        resp = client.put("/admin/settings/search.default_limit", json={"value_json": 0})
        assert resp.status_code == 400
        assert ">=" in resp.json()["detail"]

    def test_update_negative_float_score_returns_400(self, client: TestClient) -> None:
        resp = client.put("/admin/settings/search.score_playlist_name", json={"value_json": -0.5})
        assert resp.status_code == 400
        assert ">=" in resp.json()["detail"]

    def test_update_invalidates_cache_and_persists(self, client: TestClient) -> None:
        # Update
        client.put("/admin/settings/search.default_limit", json={"value_json": 7})
        # Fetch again — should return new value
        resp = client.get("/admin/settings/search.default_limit")
        assert resp.status_code == 200
        assert resp.json()["value_json"] == 7


# ── POST /admin/settings/reset ────────────────────────────────────────


class TestResetSettings:
    def test_reset_single_key(self, client: TestClient) -> None:
        # First change the value
        client.put("/admin/settings/search.default_limit", json={"value_json": 99})
        # Then reset it
        resp = client.post("/admin/settings/reset", json={"key": "search.default_limit"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        # Check it's back to default
        get_resp = client.get("/admin/settings/search.default_limit")
        assert get_resp.json()["value_json"] == 25

    def test_reset_all_settings(self, client: TestClient) -> None:
        # Change a few settings
        client.put("/admin/settings/search.default_limit", json={"value_json": 99})
        client.put("/admin/settings/playlist.snapshot_compaction_threshold", json={"value_json": 50})
        # Reset all
        resp = client.post("/admin/settings/reset", json={})
        assert resp.status_code == 200
        # Verify defaults restored
        r1 = client.get("/admin/settings/search.default_limit")
        assert r1.json()["value_json"] == 25
        r2 = client.get("/admin/settings/playlist.snapshot_compaction_threshold")
        assert r2.json()["value_json"] == 10

    def test_reset_unknown_key_returns_404(self, client: TestClient) -> None:
        resp = client.post("/admin/settings/reset", json={"key": "no.such.key"})
        assert resp.status_code == 404
