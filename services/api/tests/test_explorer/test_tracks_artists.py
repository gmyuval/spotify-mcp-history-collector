"""Tests for /api/me/tracks and /api/me/artists browser endpoints."""

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
    """Seed user with 2 artists, 3 tracks, and varied play history."""
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        user = User(spotify_user_id="browser_test_user", display_name="Browser Tester")
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

        other_user = User(spotify_user_id="other_user", display_name="Other")
        session.add(other_user)
        await session.flush()

        artist_a = Artist(name="Alpha Artist", spotify_artist_id="artist_a")
        artist_b = Artist(name="Beta Artist", spotify_artist_id="artist_b")
        session.add_all([artist_a, artist_b])
        await session.flush()

        track_1 = Track(name="Alpha Song", spotify_track_id="t1", duration_ms=200000)
        track_2 = Track(name="Beta Song", spotify_track_id="t2", duration_ms=180000)
        track_3 = Track(name="Gamma Song", spotify_track_id="t3", duration_ms=220000)
        session.add_all([track_1, track_2, track_3])
        await session.flush()

        session.add(TrackArtist(track_id=track_1.id, artist_id=artist_a.id, position=0))
        session.add(TrackArtist(track_id=track_2.id, artist_id=artist_b.id, position=0))
        session.add(TrackArtist(track_id=track_3.id, artist_id=artist_a.id, position=0))

        now = datetime.now(UTC)
        # Track 1: 5 plays (recent)
        for i in range(5):
            session.add(
                Play(
                    user_id=user.id,
                    track_id=track_1.id,
                    played_at=now - timedelta(hours=i),
                    ms_played=200000,
                    source="spotify_api",
                )
            )
        # Track 2: 3 plays (recent)
        for i in range(3):
            session.add(
                Play(
                    user_id=user.id,
                    track_id=track_2.id,
                    played_at=now - timedelta(hours=i + 10),
                    ms_played=180000,
                    source="spotify_api",
                )
            )
        # Track 3: 1 play (60 days ago — outside 30d window)
        session.add(
            Play(
                user_id=user.id,
                track_id=track_3.id,
                played_at=now - timedelta(days=60),
                ms_played=220000,
                source="spotify_api",
            )
        )
        # Other user's play (should never appear)
        session.add(
            Play(
                user_id=other_user.id,
                track_id=track_1.id,
                played_at=now - timedelta(hours=20),
                ms_played=200000,
                source="spotify_api",
            )
        )

        await session.commit()
        return {"user_id": user.id, "other_user_id": other_user.id}


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


class TestTracks:
    def test_tracks_returns_paginated(
        self, client: TestClient, seeded_data: dict[str, object], jwt_service: JWTService
    ) -> None:
        user_id: int = seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/tracks", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3  # 3 unique tracks
        assert len(data["items"]) == 3
        assert data["limit"] == 50
        assert data["offset"] == 0
        # Default sort: play_count DESC — track_1 (5 plays) first
        assert data["items"][0]["name"] == "Alpha Song"
        assert data["items"][0]["play_count"] == 5

    def test_tracks_pagination(
        self, client: TestClient, seeded_data: dict[str, object], jwt_service: JWTService
    ) -> None:
        user_id: int = seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/tracks?limit=2&offset=0", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["items"]) == 2

        resp2 = client.get("/api/me/tracks?limit=2&offset=2", cookies=_auth_cookies(jwt_service, user_id))
        data2 = resp2.json()
        assert len(data2["items"]) == 1

    def test_tracks_sort_by_name(
        self, client: TestClient, seeded_data: dict[str, object], jwt_service: JWTService
    ) -> None:
        user_id: int = seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/tracks?sort=name", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        names = [item["name"] for item in resp.json()["items"]]
        assert names == sorted(names)

    def test_tracks_search(self, client: TestClient, seeded_data: dict[str, object], jwt_service: JWTService) -> None:
        user_id: int = seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/tracks?q=Beta", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["name"] == "Beta Song"

    def test_tracks_days_filter(
        self, client: TestClient, seeded_data: dict[str, object], jwt_service: JWTService
    ) -> None:
        user_id: int = seeded_data["user_id"]  # type: ignore[assignment]
        # 30 days: should exclude track_3 (60 days ago)
        resp = client.get("/api/me/tracks?days=30", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

        # 90 days: should include all 3
        resp = client.get("/api/me/tracks?days=90", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.json()["total"] == 3

    def test_tracks_requires_auth(self, client: TestClient) -> None:
        resp = client.get("/api/me/tracks")
        assert resp.status_code == 401


class TestArtists:
    def test_artists_returns_paginated(
        self, client: TestClient, seeded_data: dict[str, object], jwt_service: JWTService
    ) -> None:
        user_id: int = seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/artists", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2  # 2 unique artists
        assert len(data["items"]) == 2
        assert data["limit"] == 50
        assert data["offset"] == 0
        # Default sort: play_count DESC — Alpha Artist (6 plays: 5 + 1) first
        assert data["items"][0]["name"] == "Alpha Artist"
        assert data["items"][0]["play_count"] == 6

    def test_artists_pagination(
        self, client: TestClient, seeded_data: dict[str, object], jwt_service: JWTService
    ) -> None:
        user_id: int = seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/artists?limit=1", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 1

    def test_artists_sort_by_name(
        self, client: TestClient, seeded_data: dict[str, object], jwt_service: JWTService
    ) -> None:
        user_id: int = seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/artists?sort=name", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        names = [item["name"] for item in resp.json()["items"]]
        assert names == sorted(names)

    def test_artists_search(self, client: TestClient, seeded_data: dict[str, object], jwt_service: JWTService) -> None:
        user_id: int = seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/artists?q=Beta", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["name"] == "Beta Artist"

    def test_artists_days_filter(
        self, client: TestClient, seeded_data: dict[str, object], jwt_service: JWTService
    ) -> None:
        user_id: int = seeded_data["user_id"]  # type: ignore[assignment]
        # 30 days: Alpha has 5 plays (recent), Beta has 3 plays (recent), Gamma is through Alpha (60d ago)
        resp = client.get("/api/me/artists?days=30", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        # Only Alpha and Beta have recent plays
        assert resp.json()["total"] == 2

    def test_artists_track_count(
        self, client: TestClient, seeded_data: dict[str, object], jwt_service: JWTService
    ) -> None:
        user_id: int = seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/artists", cookies=_auth_cookies(jwt_service, user_id))
        data = resp.json()
        # Alpha Artist has 2 tracks (track_1 and track_3), Beta has 1 (track_2)
        alpha = next(a for a in data["items"] if a["name"] == "Alpha Artist")
        beta = next(a for a in data["items"] if a["name"] == "Beta Artist")
        assert alpha["track_count"] == 2
        assert beta["track_count"] == 1

    def test_artists_requires_auth(self, client: TestClient) -> None:
        resp = client.get("/api/me/artists")
        assert resp.status_code == 401


class TestDashboardDays:
    def test_dashboard_accepts_days_param(
        self, client: TestClient, seeded_data: dict[str, object], jwt_service: JWTService
    ) -> None:
        user_id: int = seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/dashboard?days=7", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        data = resp.json()
        # Top lists should be limited to 7-day window
        assert "top_artists" in data
        assert "top_tracks" in data

    def test_dashboard_default_days(
        self, client: TestClient, seeded_data: dict[str, object], jwt_service: JWTService
    ) -> None:
        user_id: int = seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/dashboard", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        data = resp.json()
        # Default 30d: should have top_artists and top_tracks
        assert len(data["top_artists"]) >= 1
        assert len(data["top_tracks"]) >= 1
