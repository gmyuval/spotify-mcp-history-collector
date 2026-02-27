"""Tests for user-facing explorer API endpoints (/api/me/*)."""

from collections.abc import AsyncGenerator, Generator
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.auth.jwt import JWTService
from app.main import app
from app.settings import AppSettings, get_settings
from shared.db.base import Base
from shared.db.models.cache import CachedPlaylist, CachedPlaylistTrack
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
    """Seed a user with own_data.view permission + play history + cached playlist."""
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        # User
        user = User(spotify_user_id="explorer_test_user", display_name="Explorer Tester")
        session.add(user)
        await session.flush()

        # RBAC: permission + role + assignment
        perm = Permission(codename="own_data.view", description="View own data")
        session.add(perm)
        await session.flush()

        role = Role(name="user", description="Standard user", is_system=True)
        session.add(role)
        await session.flush()

        session.add(RolePermission(role_id=role.id, permission_id=perm.id))
        session.add(UserRole(user_id=user.id, role_id=role.id))

        # Another user (to test data isolation)
        other_user = User(spotify_user_id="other_user", display_name="Other")
        session.add(other_user)
        await session.flush()

        # Music data
        artist = Artist(name="Test Artist", spotify_artist_id="artist_1")
        session.add(artist)
        await session.flush()

        track = Track(name="Test Track", spotify_track_id="track_1", duration_ms=180000)
        session.add(track)
        await session.flush()

        session.add(TrackArtist(track_id=track.id, artist_id=artist.id, position=0))

        now = datetime.now(UTC)
        for i in range(5):
            session.add(
                Play(
                    user_id=user.id,
                    track_id=track.id,
                    played_at=now - timedelta(hours=i),
                    ms_played=180000,
                    source="spotify_api",
                )
            )
        # One play for other user (should not appear in our results)
        session.add(
            Play(
                user_id=other_user.id,
                track_id=track.id,
                played_at=now - timedelta(hours=10),
                ms_played=180000,
                source="spotify_api",
            )
        )

        # Cached playlist
        playlist = CachedPlaylist(
            spotify_playlist_id="pl_123",
            user_id=user.id,
            name="My Playlist",
            description="Test playlist",
            owner_display_name="Explorer Tester",
            total_tracks=1,
            snapshot_id="snap_1",
            fetched_at=now,
        )
        session.add(playlist)
        await session.flush()

        session.add(
            CachedPlaylistTrack(
                cached_playlist_id=playlist.id,
                spotify_track_id="track_1",
                track_name="Test Track",
                artists_json='[{"id": "artist_1", "name": "Test Artist"}]',
                position=0,
            )
        )

        await session.commit()
        return {
            "user_id": user.id,
            "other_user_id": other_user.id,
            "track_id": track.id,
            "playlist_id": playlist.id,
        }


@pytest.fixture
def client(
    async_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[TestClient]:
    """TestClient with DB + auth overrides."""
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

    # Override DI dependencies
    app.dependency_overrides[db_manager.dependency] = _override
    app.dependency_overrides[get_settings] = _test_settings

    # Monkeypatch middleware's module-level get_settings (not via DI)
    monkeypatch.setattr("app.auth.middleware.get_settings", _test_settings)

    # Monkeypatch middleware's db_manager for request.state.db_session
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


class TestDashboard:
    def test_dashboard_returns_stats(
        self, client: TestClient, seeded_data: dict[str, object], jwt_service: JWTService
    ) -> None:
        user_id: int = seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/dashboard", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_plays"] == 5
        assert data["unique_tracks"] == 1
        assert data["unique_artists"] == 1
        assert data["listening_hours"] >= 0
        assert len(data["top_artists"]) == 1
        assert len(data["top_tracks"]) == 1

    def test_dashboard_requires_auth(self, client: TestClient) -> None:
        resp = client.get("/api/me/dashboard")
        assert resp.status_code == 401


class TestHistory:
    def test_history_returns_paginated(
        self, client: TestClient, seeded_data: dict[str, object], jwt_service: JWTService
    ) -> None:
        user_id: int = seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/history?limit=3", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert len(data["items"]) == 3
        assert data["limit"] == 3
        assert data["offset"] == 0
        # Ordered by played_at DESC
        assert data["items"][0]["track_name"] == "Test Track"

    def test_history_offset(self, client: TestClient, seeded_data: dict[str, object], jwt_service: JWTService) -> None:
        user_id: int = seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/history?limit=3&offset=3", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert len(data["items"]) == 2  # Only 2 remaining

    def test_history_search(self, client: TestClient, seeded_data: dict[str, object], jwt_service: JWTService) -> None:
        user_id: int = seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/history?q=Test", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        assert resp.json()["total"] == 5

        resp = client.get("/api/me/history?q=Nonexistent", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_history_isolates_users(
        self, client: TestClient, seeded_data: dict[str, object], jwt_service: JWTService
    ) -> None:
        """User can only see their own plays, not other users'."""
        user_id: int = seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/history", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        assert resp.json()["total"] == 5  # Not 6 (other user's play excluded)


class TestTopArtists:
    def test_top_artists(self, client: TestClient, seeded_data: dict[str, object], jwt_service: JWTService) -> None:
        user_id: int = seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/top-artists", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["artist_name"] == "Test Artist"
        assert data[0]["play_count"] == 5


class TestTopTracks:
    def test_top_tracks(self, client: TestClient, seeded_data: dict[str, object], jwt_service: JWTService) -> None:
        user_id: int = seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/top-tracks", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["track_name"] == "Test Track"
        assert data[0]["play_count"] == 5


class TestPlaylists:
    def test_playlists_list(self, client: TestClient, seeded_data: dict[str, object], jwt_service: JWTService) -> None:
        user_id: int = seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/playlists", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "My Playlist"

    def test_playlist_detail(self, client: TestClient, seeded_data: dict[str, object], jwt_service: JWTService) -> None:
        user_id: int = seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/playlists/pl_123", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "My Playlist"
        assert len(data["tracks"]) == 1
        assert data["tracks"][0]["track_name"] == "Test Track"

    def test_playlist_not_found(
        self, client: TestClient, seeded_data: dict[str, object], jwt_service: JWTService
    ) -> None:
        user_id: int = seeded_data["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/playlists/nonexistent", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 404
