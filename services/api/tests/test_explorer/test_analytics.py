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
from shared.db.enums import TrackSource
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

        artist = Artist(name="Analytics Artist", spotify_artist_id="artist_a", genres="rock, indie")
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
                    source=TrackSource.SPOTIFY_API,
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


# --- Genre Distribution ---


@pytest.fixture
async def genre_seeded_data(async_engine: AsyncEngine) -> dict[str, object]:
    """Seed a user with two artists having overlapping genres."""
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        user = User(spotify_user_id="genre_user", display_name="Genre Tester")
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

        # Artist A: rock, indie (10 plays)
        artist_a = Artist(name="Artist A", spotify_artist_id="ga_1", genres="rock, indie")
        session.add(artist_a)
        await session.flush()

        track_a = Track(name="Track A", spotify_track_id="gt_1", duration_ms=200000)
        session.add(track_a)
        await session.flush()
        session.add(TrackArtist(track_id=track_a.id, artist_id=artist_a.id, position=0))

        # Artist B: rock, metal (5 plays)
        artist_b = Artist(name="Artist B", spotify_artist_id="ga_2", genres="rock, metal")
        session.add(artist_b)
        await session.flush()

        track_b = Track(name="Track B", spotify_track_id="gt_2", duration_ms=180000)
        session.add(track_b)
        await session.flush()
        session.add(TrackArtist(track_id=track_b.id, artist_id=artist_b.id, position=0))

        # Artist C: no genres (3 plays — should be excluded)
        artist_c = Artist(name="Artist C", spotify_artist_id="ga_3", genres=None)
        session.add(artist_c)
        await session.flush()

        track_c = Track(name="Track C", spotify_track_id="gt_3", duration_ms=150000)
        session.add(track_c)
        await session.flush()
        session.add(TrackArtist(track_id=track_c.id, artist_id=artist_c.id, position=0))

        now = datetime.now(UTC)
        for i in range(10):
            session.add(
                Play(
                    user_id=user.id,
                    track_id=track_a.id,
                    played_at=now - timedelta(days=i),
                    ms_played=200000,
                    source=TrackSource.SPOTIFY_API,
                )
            )
        for i in range(5):
            session.add(
                Play(
                    user_id=user.id,
                    track_id=track_b.id,
                    played_at=now - timedelta(days=i, hours=2),
                    ms_played=180000,
                    source=TrackSource.SPOTIFY_API,
                )
            )
        for i in range(3):
            session.add(
                Play(
                    user_id=user.id,
                    track_id=track_c.id,
                    played_at=now - timedelta(days=i, hours=4),
                    ms_played=150000,
                    source=TrackSource.SPOTIFY_API,
                )
            )

        await session.commit()
        return {"user_id": user.id}


class TestGenres:
    def test_genres_returns_items(
        self, client: TestClient, genre_seeded_data: dict[str, object], jwt_service: JWTService
    ) -> None:
        user_id: int = genre_seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/analytics/genres?days=3650", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        data = resp.json()
        assert "genres" in data
        assert len(data["genres"]) > 0
        item = data["genres"][0]
        assert "genre" in item
        assert "play_count" in item
        assert "artist_count" in item

    def test_genres_rock_is_top(
        self, client: TestClient, genre_seeded_data: dict[str, object], jwt_service: JWTService
    ) -> None:
        """Rock should be top genre — 10 plays (A) + 5 plays (B) = 15."""
        user_id: int = genre_seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/analytics/genres?days=3650", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        genres = resp.json()["genres"]
        rock = next(g for g in genres if g["genre"] == "rock")
        assert rock["play_count"] == 15
        assert rock["artist_count"] == 2

    def test_genres_indie_and_metal(
        self, client: TestClient, genre_seeded_data: dict[str, object], jwt_service: JWTService
    ) -> None:
        """indie = 10 plays (A only), metal = 5 plays (B only)."""
        user_id: int = genre_seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/analytics/genres?days=3650", cookies=_auth_cookies(jwt_service, user_id))
        genres = {g["genre"]: g for g in resp.json()["genres"]}
        assert genres["indie"]["play_count"] == 10
        assert genres["indie"]["artist_count"] == 1
        assert genres["metal"]["play_count"] == 5
        assert genres["metal"]["artist_count"] == 1

    def test_genres_excludes_null_genres(
        self, client: TestClient, genre_seeded_data: dict[str, object], jwt_service: JWTService
    ) -> None:
        """Artist C has no genres — its 3 plays should not appear."""
        user_id: int = genre_seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/analytics/genres?days=3650", cookies=_auth_cookies(jwt_service, user_id))
        total = sum(g["play_count"] for g in resp.json()["genres"])
        # 10 (A: rock) + 10 (A: indie) + 5 (B: rock) + 5 (B: metal) = 30
        assert total == 30

    def test_genres_time_window(
        self, client: TestClient, genre_seeded_data: dict[str, object], jwt_service: JWTService
    ) -> None:
        """Short window should return fewer plays."""
        user_id: int = genre_seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/analytics/genres?days=1", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        total = sum(g["play_count"] for g in resp.json()["genres"])
        assert total < 30

    def test_genres_requires_auth(self, client: TestClient) -> None:
        resp = client.get("/api/me/analytics/genres")
        assert resp.status_code == 401


# --- Discovery Rate ---


@pytest.fixture
async def discovery_seeded_data(async_engine: AsyncEngine) -> dict[str, object]:
    """Seed plays with tracks first played on different days."""
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        user = User(spotify_user_id="discovery_user", display_name="Discovery Tester")
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

        artist = Artist(name="Discovery Artist", spotify_artist_id="da_1")
        session.add(artist)
        await session.flush()

        # Track A: first played 5 days ago, replayed 3 days ago and today
        track_a = Track(name="Track A", spotify_track_id="dt_1", duration_ms=200000)
        session.add(track_a)
        await session.flush()
        session.add(TrackArtist(track_id=track_a.id, artist_id=artist.id, position=0))

        # Track B: first played 3 days ago only
        track_b = Track(name="Track B", spotify_track_id="dt_2", duration_ms=180000)
        session.add(track_b)
        await session.flush()
        session.add(TrackArtist(track_id=track_b.id, artist_id=artist.id, position=0))

        # Track C: first played today only
        track_c = Track(name="Track C", spotify_track_id="dt_3", duration_ms=150000)
        session.add(track_c)
        await session.flush()
        session.add(TrackArtist(track_id=track_c.id, artist_id=artist.id, position=0))

        # Anchor to midday so hour offsets never cross date boundaries
        now = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
        plays = [
            # Track A: first play 5 days ago (new), replay 3 days ago (repeat), replay today (repeat)
            Play(
                user_id=user.id,
                track_id=track_a.id,
                played_at=now - timedelta(days=5),
                ms_played=200000,
                source=TrackSource.SPOTIFY_API,
            ),
            Play(
                user_id=user.id,
                track_id=track_a.id,
                played_at=now - timedelta(days=3),
                ms_played=200000,
                source=TrackSource.SPOTIFY_API,
            ),
            Play(
                user_id=user.id,
                track_id=track_a.id,
                played_at=now - timedelta(hours=1),
                ms_played=200000,
                source=TrackSource.SPOTIFY_API,
            ),
            # Track B: first play 3 days ago (new)
            Play(
                user_id=user.id,
                track_id=track_b.id,
                played_at=now - timedelta(days=3, hours=1),
                ms_played=180000,
                source=TrackSource.SPOTIFY_API,
            ),
            # Track C: first play today (new)
            Play(
                user_id=user.id,
                track_id=track_c.id,
                played_at=now - timedelta(hours=2),
                ms_played=150000,
                source=TrackSource.SPOTIFY_API,
            ),
        ]
        session.add_all(plays)
        await session.commit()
        return {"user_id": user.id}


class TestDiscovery:
    def test_discovery_returns_items(
        self, client: TestClient, discovery_seeded_data: dict[str, object], jwt_service: JWTService
    ) -> None:
        user_id: int = discovery_seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/analytics/discovery?days=3650", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        data = resp.json()
        assert "days" in data
        assert len(data["days"]) > 0
        item = data["days"][0]
        assert "date" in item
        assert "new_tracks" in item
        assert "repeat_tracks" in item

    def test_discovery_new_vs_repeat(
        self, client: TestClient, discovery_seeded_data: dict[str, object], jwt_service: JWTService
    ) -> None:
        """5 days ago: 1 new (A). 3 days ago: 1 new (B) + 1 repeat (A). Today: 1 new (C) + 1 repeat (A)."""
        user_id: int = discovery_seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/analytics/discovery?days=3650", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        days_data = {d["date"]: d for d in resp.json()["days"]}

        total_new = sum(d["new_tracks"] for d in days_data.values())
        total_repeat = sum(d["repeat_tracks"] for d in days_data.values())
        assert total_new == 3  # A first, B first, C first
        assert total_repeat == 2  # A replay x2

    def test_discovery_time_window(
        self, client: TestClient, discovery_seeded_data: dict[str, object], jwt_service: JWTService
    ) -> None:
        """1-day window should only show today's plays."""
        user_id: int = discovery_seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/analytics/discovery?days=1", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        days_data = resp.json()["days"]
        # Only today's plays: Track A replay (repeat) + Track C first play (new)
        total = sum(d["new_tracks"] + d["repeat_tracks"] for d in days_data)
        assert total == 2  # Track A replay (repeat) + Track C first play (new)

    def test_discovery_requires_auth(self, client: TestClient) -> None:
        resp = client.get("/api/me/analytics/discovery")
        assert resp.status_code == 401
