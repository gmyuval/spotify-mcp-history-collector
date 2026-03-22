"""Tests for analytics API endpoints (/api/me/analytics/*)."""

from collections.abc import AsyncGenerator, Generator
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.auth.jwt import JWTService
from app.main import app
from app.settings import AppSettings, get_settings
from shared.db.base import Base
from shared.db.models.music import Artist, Play, Track, TrackArtist
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
async def seeded_data(async_engine: AsyncEngine) -> dict[str, object]:
    """Seed a user with plays spread across multiple hours and days."""
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        user = User(spotify_user_id="analytics_user", display_name="Analytics Tester")
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

        artist = Artist(name="Analytics Artist", spotify_artist_id="artist_a")
        session.add(artist)
        await session.flush()

        track = Track(name="Analytics Track", spotify_track_id="track_a", duration_ms=200000)
        session.add(track)
        await session.flush()

        session.add(TrackArtist(track_id=track.id, artist_id=artist.id, position=0))

        now = datetime.now(UTC)
        # 10 plays spread across different hours and days
        for i in range(10):
            session.add(
                Play(
                    user_id=user.id,
                    track_id=track.id,
                    played_at=now - timedelta(days=i, hours=i % 6),
                    ms_played=200000,
                    source="spotify_api",
                )
            )

        await session.commit()
        return {"user_id": user.id}


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
        def session(self_inner) -> AbstractAsyncContextManager[AsyncSession]:  # noqa: N805
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


# --- Heatmap ---


class TestHeatmap:
    def test_heatmap_returns_cells(
        self, client: TestClient, seeded_data: dict[str, object], jwt_service: JWTService
    ) -> None:
        user_id: int = seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/analytics/heatmap?days=90", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        data = resp.json()
        assert "cells" in data
        assert len(data["cells"]) > 0
        cell = data["cells"][0]
        assert "weekday" in cell
        assert "hour" in cell
        assert "play_count" in cell
        assert 0 <= cell["weekday"] <= 6
        assert 0 <= cell["hour"] <= 23

    def test_heatmap_requires_auth(self, client: TestClient) -> None:
        resp = client.get("/api/me/analytics/heatmap")
        assert resp.status_code == 401

    def test_heatmap_short_window(
        self, client: TestClient, seeded_data: dict[str, object], jwt_service: JWTService
    ) -> None:
        """With plays spread over 10 days, a 1-day window should return only recent plays."""
        user_id: int = seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/analytics/heatmap?days=1", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        total = sum(c["play_count"] for c in resp.json()["cells"])
        assert total < 10  # not all plays — only those within 1 day

    def test_heatmap_all_time(
        self, client: TestClient, seeded_data: dict[str, object], jwt_service: JWTService
    ) -> None:
        """All-time window should return all 10 plays."""
        user_id: int = seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/analytics/heatmap?days=3650", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        total = sum(c["play_count"] for c in resp.json()["cells"])
        assert total == 10


# --- Timeline ---


class TestTimeline:
    def test_timeline_day_bucket(
        self, client: TestClient, seeded_data: dict[str, object], jwt_service: JWTService
    ) -> None:
        user_id: int = seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/analytics/timeline?days=90&bucket=day", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["bucket_size"] == "day"
        assert len(data["buckets"]) > 0
        b = data["buckets"][0]
        assert "period" in b
        assert "play_count" in b
        assert "ms_played" in b

    def test_timeline_week_bucket(
        self, client: TestClient, seeded_data: dict[str, object], jwt_service: JWTService
    ) -> None:
        user_id: int = seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/analytics/timeline?days=90&bucket=week", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["bucket_size"] == "week"
        # Weeks should have fewer buckets than days
        assert len(data["buckets"]) >= 1

    def test_timeline_month_bucket(
        self, client: TestClient, seeded_data: dict[str, object], jwt_service: JWTService
    ) -> None:
        user_id: int = seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get(
            "/api/me/analytics/timeline?days=90&bucket=month", cookies=_auth_cookies(jwt_service, user_id)
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["bucket_size"] == "month"

    def test_timeline_invalid_bucket_rejected(
        self, client: TestClient, seeded_data: dict[str, object], jwt_service: JWTService
    ) -> None:
        user_id: int = seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/analytics/timeline?days=90&bucket=year", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 422

    def test_timeline_requires_auth(self, client: TestClient) -> None:
        resp = client.get("/api/me/analytics/timeline")
        assert resp.status_code == 401

    def test_timeline_total_plays(
        self, client: TestClient, seeded_data: dict[str, object], jwt_service: JWTService
    ) -> None:
        user_id: int = seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get(
            "/api/me/analytics/timeline?days=3650&bucket=day", cookies=_auth_cookies(jwt_service, user_id)
        )
        assert resp.status_code == 200
        total = sum(b["play_count"] for b in resp.json()["buckets"])
        assert total == 10
