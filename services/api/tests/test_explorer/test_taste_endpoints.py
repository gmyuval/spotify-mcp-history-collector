"""Tests for taste profile explorer API endpoints (/api/me/taste-profile, /api/me/preference-events)."""

from collections.abc import AsyncGenerator, Generator

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.auth.jwt import JWTService
from app.main import app
from app.settings import AppSettings, get_settings
from shared.db.base import Base
from shared.db.models.rbac import Permission, Role, RolePermission, UserRole
from shared.db.models.user import User

TEST_FERNET_KEY = Fernet.generate_key().decode()


def _test_settings() -> AppSettings:
    return AppSettings(
        SPOTIFY_CLIENT_ID="test-id",
        SPOTIFY_CLIENT_SECRET="test-secret",
        TOKEN_ENCRYPTION_KEY=TEST_FERNET_KEY,
        JWT_COOKIE_SECURE=False,
        ADMIN_AUTH_MODE="",
        AUTH_ALLOWED_REDIRECT_ORIGINS="http://localhost:8001,http://localhost:8002",
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
async def seeded_user(async_engine: AsyncEngine) -> int:
    """Seed a user with own_data.view permission."""
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        user = User(spotify_user_id="taste_test_user", display_name="Taste Tester")
        session.add(user)
        await session.flush()

        perm = Permission(codename="own_data.view", description="View own data")
        session.add(perm)
        await session.flush()

        role = Role(name="user", description="Standard user", is_system=True)
        session.add(role)
        await session.flush()

        session.add(RolePermission(role_id=role.id, permission_id=perm.id))
        session.add(UserRole(user_id=user.id, role_id=role.id))

        await session.commit()
        return user.id


@pytest.fixture
def client(async_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    from contextlib import asynccontextmanager

    from app.dependencies import db_manager

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

    monkeypatch.setattr("app.auth.middleware.get_settings", _test_settings)

    class _TestDBManager:
        def session(self_inner):  # noqa: N805
            @asynccontextmanager
            async def _ctx() -> AsyncGenerator[AsyncSession]:
                async with session_factory() as s:
                    try:
                        yield s
                        await s.commit()
                    except Exception:
                        await s.rollback()
                        raise

            return _ctx()

    monkeypatch.setattr("app.auth.middleware.db_manager", _TestDBManager())

    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def jwt_service() -> JWTService:
    return JWTService(_test_settings())


def _auth_cookies(jwt_service: JWTService, user_id: int) -> dict[str, str]:
    token = jwt_service.create_access_token(user_id)
    return {"access_token": token}


# ── GET /api/me/taste-profile ──────────────────────────────────────


class TestGetTasteProfile:
    def test_empty_profile(self, client: TestClient, seeded_user: int, jwt_service: JWTService) -> None:
        resp = client.get("/api/me/taste-profile", cookies=_auth_cookies(jwt_service, seeded_user))
        assert resp.status_code == 200
        data = resp.json()
        assert data["profile"]["version"] == 0
        assert data["profile"]["profile"] == {}
        assert data["recent_events"] == []

    def test_with_profile(self, client: TestClient, seeded_user: int, jwt_service: JWTService) -> None:
        cookies = _auth_cookies(jwt_service, seeded_user)
        # Create profile first
        client.patch(
            "/api/me/taste-profile",
            json={"patch": {"core_genres": ["metal"]}, "reason": "test"},
            cookies=cookies,
        )
        resp = client.get("/api/me/taste-profile", cookies=cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert data["profile"]["version"] == 1
        assert data["profile"]["profile"]["core_genres"] == ["metal"]
        # Should have a preference event from the reason
        assert len(data["recent_events"]) == 1
        assert data["recent_events"][0]["type"] == "note"

    def test_requires_auth(self, client: TestClient) -> None:
        resp = client.get("/api/me/taste-profile")
        assert resp.status_code == 401


# ── PATCH /api/me/taste-profile ────────────────────────────────────


class TestUpdateTasteProfile:
    def test_create_profile(self, client: TestClient, seeded_user: int, jwt_service: JWTService) -> None:
        cookies = _auth_cookies(jwt_service, seeded_user)
        resp = client.patch(
            "/api/me/taste-profile",
            json={"patch": {"core_genres": ["symphonic metal", "power metal"]}},
            cookies=cookies,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == 1
        assert data["profile"]["core_genres"] == ["symphonic metal", "power metal"]

    def test_merge_patch(self, client: TestClient, seeded_user: int, jwt_service: JWTService) -> None:
        cookies = _auth_cookies(jwt_service, seeded_user)
        # Create
        client.patch(
            "/api/me/taste-profile", json={"patch": {"core_genres": ["metal"], "mood": "dark"}}, cookies=cookies
        )
        # Update mood only
        resp = client.patch("/api/me/taste-profile", json={"patch": {"mood": "chill"}}, cookies=cookies)
        data = resp.json()
        assert data["version"] == 2
        assert data["profile"]["core_genres"] == ["metal"]
        assert data["profile"]["mood"] == "chill"

    def test_with_reason(self, client: TestClient, seeded_user: int, jwt_service: JWTService) -> None:
        cookies = _auth_cookies(jwt_service, seeded_user)
        resp = client.patch(
            "/api/me/taste-profile",
            json={"patch": {"core_genres": ["metal"]}, "reason": "User said they like metal"},
            cookies=cookies,
        )
        assert resp.status_code == 200
        # Check that a preference event was created
        events_resp = client.get("/api/me/preference-events", cookies=cookies)
        assert events_resp.json()["total"] == 1

    def test_empty_patch_rejected(self, client: TestClient, seeded_user: int, jwt_service: JWTService) -> None:
        cookies = _auth_cookies(jwt_service, seeded_user)
        resp = client.patch("/api/me/taste-profile", json={"patch": {}}, cookies=cookies)
        assert resp.status_code == 422

    def test_requires_auth(self, client: TestClient) -> None:
        resp = client.patch("/api/me/taste-profile", json={"patch": {"foo": "bar"}})
        assert resp.status_code == 401


# ── DELETE /api/me/taste-profile ───────────────────────────────────


class TestClearTasteProfile:
    def test_clear_existing(self, client: TestClient, seeded_user: int, jwt_service: JWTService) -> None:
        cookies = _auth_cookies(jwt_service, seeded_user)
        # Create profile
        client.patch("/api/me/taste-profile", json={"patch": {"core_genres": ["metal"]}}, cookies=cookies)
        # Clear
        resp = client.delete("/api/me/taste-profile", cookies=cookies)
        assert resp.status_code == 200
        assert resp.json()["cleared"] is True
        # Verify it's gone
        get_resp = client.get("/api/me/taste-profile", cookies=cookies)
        assert get_resp.json()["profile"]["version"] == 0

    def test_clear_nonexistent(self, client: TestClient, seeded_user: int, jwt_service: JWTService) -> None:
        """Clearing when no profile exists succeeds silently."""
        cookies = _auth_cookies(jwt_service, seeded_user)
        resp = client.delete("/api/me/taste-profile", cookies=cookies)
        assert resp.status_code == 200
        assert resp.json()["cleared"] is True

    def test_clear_and_recreate(self, client: TestClient, seeded_user: int, jwt_service: JWTService) -> None:
        cookies = _auth_cookies(jwt_service, seeded_user)
        # Create, update to v2
        client.patch("/api/me/taste-profile", json={"patch": {"core_genres": ["metal"]}}, cookies=cookies)
        client.patch("/api/me/taste-profile", json={"patch": {"mood": "dark"}}, cookies=cookies)
        # Clear
        client.delete("/api/me/taste-profile", cookies=cookies)
        # Recreate
        resp = client.patch("/api/me/taste-profile", json={"patch": {"core_genres": ["jazz"]}}, cookies=cookies)
        assert resp.json()["version"] == 1
        assert "mood" not in resp.json()["profile"]

    def test_requires_auth(self, client: TestClient) -> None:
        resp = client.delete("/api/me/taste-profile")
        assert resp.status_code == 401


# ── GET /api/me/preference-events ──────────────────────────────────


class TestPreferenceEvents:
    def test_empty_events(self, client: TestClient, seeded_user: int, jwt_service: JWTService) -> None:
        cookies = _auth_cookies(jwt_service, seeded_user)
        resp = client.get("/api/me/preference-events", cookies=cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_events_from_profile_updates(self, client: TestClient, seeded_user: int, jwt_service: JWTService) -> None:
        cookies = _auth_cookies(jwt_service, seeded_user)
        # Create profile updates with reasons (each creates a preference event)
        client.patch(
            "/api/me/taste-profile", json={"patch": {"core_genres": ["metal"]}, "reason": "First"}, cookies=cookies
        )
        client.patch("/api/me/taste-profile", json={"patch": {"mood": "dark"}}, cookies=cookies)
        client.patch("/api/me/taste-profile", json={"patch": {"avoid": ["pop"]}, "reason": "Second"}, cookies=cookies)

        resp = client.get("/api/me/preference-events", cookies=cookies)
        data = resp.json()
        assert data["total"] == 2  # Only updates with reason create events
        assert data["items"][0]["type"] == "note"

    def test_pagination(self, client: TestClient, seeded_user: int, jwt_service: JWTService) -> None:
        cookies = _auth_cookies(jwt_service, seeded_user)
        # Create 5 events
        for i in range(5):
            client.patch(
                "/api/me/taste-profile",
                json={"patch": {f"key_{i}": f"val_{i}"}, "reason": f"Reason {i}"},
                cookies=cookies,
            )

        # Page 1
        resp = client.get("/api/me/preference-events?limit=2&offset=0", cookies=cookies)
        data = resp.json()
        assert data["total"] == 5
        assert len(data["items"]) == 2
        assert data["limit"] == 2
        assert data["offset"] == 0

        # Page 2
        resp = client.get("/api/me/preference-events?limit=2&offset=2", cookies=cookies)
        data = resp.json()
        assert len(data["items"]) == 2

        # Page 3
        resp = client.get("/api/me/preference-events?limit=2&offset=4", cookies=cookies)
        data = resp.json()
        assert len(data["items"]) == 1

    def test_requires_auth(self, client: TestClient) -> None:
        resp = client.get("/api/me/preference-events")
        assert resp.status_code == 401
