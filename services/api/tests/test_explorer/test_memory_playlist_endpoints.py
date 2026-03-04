"""Tests for memory playlist explorer API endpoints (/api/me/memory-playlists)."""

import uuid
from collections.abc import AsyncGenerator, Generator

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.auth.jwt import JWTService
from app.main import app
from app.settings import AppSettings, get_settings
from shared.db.base import Base
from shared.db.enums import PlaylistEventType, PlaylistSnapshotSource
from shared.db.models.memory import MemoryPlaylist, PlaylistEvent, PlaylistSnapshot
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


async def _seed_user(session: AsyncSession, spotify_user_id: str, display_name: str) -> int:
    """Create a user with own_data.view permission and return its ID."""
    user = User(spotify_user_id=spotify_user_id, display_name=display_name)
    session.add(user)
    await session.flush()

    # RBAC — idempotent: reuse existing permission/role if present
    from sqlalchemy import select

    perm_result = await session.execute(select(Permission).where(Permission.codename == "own_data.view"))
    perm = perm_result.scalar_one_or_none()
    if perm is None:
        perm = Permission(codename="own_data.view", description="View own data")
        session.add(perm)
        await session.flush()

    role_result = await session.execute(select(Role).where(Role.name == "user"))
    role = role_result.scalar_one_or_none()
    if role is None:
        role = Role(name="user", description="Standard user", is_system=True)
        session.add(role)
        await session.flush()
        session.add(RolePermission(role_id=role.id, permission_id=perm.id))

    session.add(UserRole(user_id=user.id, role_id=role.id))
    await session.flush()
    return user.id


@pytest.fixture
async def seeded_user(async_engine: AsyncEngine) -> int:
    """Seed a single user with own_data.view permission."""
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        user_id = await _seed_user(session, "mem_pl_user", "Memory Playlist Tester")
        await session.commit()
        return user_id


@pytest.fixture
async def seeded_users(async_engine: AsyncEngine) -> dict[str, int]:
    """Seed two users for isolation tests."""
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        user_a = await _seed_user(session, "user_a", "User A")
        user_b = await _seed_user(session, "user_b", "User B")
        await session.commit()
        return {"user_a": user_a, "user_b": user_b}


@pytest.fixture
async def seeded_playlist(async_engine: AsyncEngine, seeded_user: int) -> dict[str, object]:
    """Seed a memory playlist with snapshot and events for the test user."""
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        snapshot_id = uuid.uuid4()
        pl = MemoryPlaylist(
            playlist_id="sp_abc123",
            user_id=seeded_user,
            name="My AI Playlist",
            description="Created by assistant",
            intent_tags=["upbeat", "metal"],
            seed_context={"days": 30, "top_artists": ["Nightwish"]},
            latest_snapshot_id=None,
        )
        session.add(pl)
        await session.flush()

        snap = PlaylistSnapshot(
            snapshot_id=snapshot_id,
            playlist_id="sp_abc123",
            track_ids=["track1", "track2", "track3"],
            source=PlaylistSnapshotSource.CREATE,
        )
        session.add(snap)
        await session.flush()

        pl.latest_snapshot_id = snapshot_id

        event = PlaylistEvent(
            event_id=uuid.uuid4(),
            playlist_id="sp_abc123",
            user_id=seeded_user,
            type=PlaylistEventType.ADD_TRACKS,
            payload_json={"track_ids": ["track4"]},
        )
        session.add(event)
        await session.commit()

        return {"user_id": seeded_user, "playlist_id": "sp_abc123", "snapshot_id": snapshot_id}


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


# ── GET /api/me/memory-playlists ──────────────────────────────────


class TestListMemoryPlaylists:
    def test_empty(self, client: TestClient, seeded_user: int, jwt_service: JWTService) -> None:
        resp = client.get("/api/me/memory-playlists", cookies=_auth_cookies(jwt_service, seeded_user))
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_with_playlists(
        self, client: TestClient, seeded_playlist: dict[str, object], jwt_service: JWTService
    ) -> None:
        user_id: int = seeded_playlist["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/memory-playlists", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        item = data["items"][0]
        assert item["playlist_id"] == "sp_abc123"
        assert item["name"] == "My AI Playlist"
        assert item["intent_tags"] == ["upbeat", "metal"]
        assert item["track_count"] == 3

    def test_pagination(self, client: TestClient, seeded_playlist: dict[str, object], jwt_service: JWTService) -> None:
        user_id: int = seeded_playlist["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/memory-playlists?limit=1&offset=0", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["limit"] == 1
        assert data["offset"] == 0
        assert len(data["items"]) == 1

        # Page past all data
        resp2 = client.get("/api/me/memory-playlists?limit=1&offset=10", cookies=_auth_cookies(jwt_service, user_id))
        assert resp2.json()["items"] == []

    def test_requires_auth(self, client: TestClient) -> None:
        resp = client.get("/api/me/memory-playlists")
        assert resp.status_code == 401

    def test_user_isolation(
        self,
        client: TestClient,
        seeded_users: dict[str, int],
        async_engine: AsyncEngine,
        jwt_service: JWTService,
    ) -> None:
        """User A's playlists are not visible to User B."""
        import asyncio

        factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

        async def _seed_playlist_for_user_a() -> None:
            async with factory() as session:
                pl = MemoryPlaylist(
                    playlist_id="sp_user_a_only",
                    user_id=seeded_users["user_a"],
                    name="User A's Playlist",
                    intent_tags=[],
                    seed_context={},
                )
                session.add(pl)
                await session.commit()

        asyncio.run(_seed_playlist_for_user_a())

        # User A sees the playlist
        resp_a = client.get("/api/me/memory-playlists", cookies=_auth_cookies(jwt_service, seeded_users["user_a"]))
        assert resp_a.json()["total"] == 1

        # User B does not
        resp_b = client.get("/api/me/memory-playlists", cookies=_auth_cookies(jwt_service, seeded_users["user_b"]))
        assert resp_b.json()["total"] == 0


# ── GET /api/me/memory-playlists/{playlist_id} ───────────────────


class TestMemoryPlaylistDetail:
    def test_found(self, client: TestClient, seeded_playlist: dict[str, object], jwt_service: JWTService) -> None:
        user_id: int = seeded_playlist["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/memory-playlists/sp_abc123", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["playlist_id"] == "sp_abc123"
        assert data["name"] == "My AI Playlist"
        assert data["track_ids"] == ["track1", "track2", "track3"]
        assert data["intent_tags"] == ["upbeat", "metal"]
        assert data["seed_context"]["days"] == 30
        assert data["total_events"] == 1
        assert len(data["recent_events"]) == 1
        assert data["recent_events"][0]["type"] == "ADD_TRACKS"

    def test_not_found(self, client: TestClient, seeded_user: int, jwt_service: JWTService) -> None:
        resp = client.get("/api/me/memory-playlists/nonexistent", cookies=_auth_cookies(jwt_service, seeded_user))
        assert resp.status_code == 404

    def test_user_isolation(
        self,
        client: TestClient,
        seeded_playlist: dict[str, object],
        seeded_users: dict[str, int],
        jwt_service: JWTService,
    ) -> None:
        """Another user cannot access the playlist."""
        resp = client.get(
            "/api/me/memory-playlists/sp_abc123",
            cookies=_auth_cookies(jwt_service, seeded_users["user_b"]),
        )
        assert resp.status_code == 404

    def test_requires_auth(self, client: TestClient) -> None:
        resp = client.get("/api/me/memory-playlists/sp_abc123")
        assert resp.status_code == 401


# ── GET /api/me/memory-playlists/{playlist_id}/events ─────────────


class TestMemoryPlaylistEvents:
    def test_with_events(self, client: TestClient, seeded_playlist: dict[str, object], jwt_service: JWTService) -> None:
        user_id: int = seeded_playlist["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/memory-playlists/sp_abc123/events", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["type"] == "ADD_TRACKS"

    def test_pagination(self, client: TestClient, seeded_playlist: dict[str, object], jwt_service: JWTService) -> None:
        user_id: int = seeded_playlist["user_id"]  # type: ignore[assignment]
        resp = client.get(
            "/api/me/memory-playlists/sp_abc123/events?limit=1&offset=0",
            cookies=_auth_cookies(jwt_service, user_id),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["limit"] == 1
        assert len(data["items"]) == 1

    def test_not_found(self, client: TestClient, seeded_user: int, jwt_service: JWTService) -> None:
        resp = client.get(
            "/api/me/memory-playlists/nonexistent/events",
            cookies=_auth_cookies(jwt_service, seeded_user),
        )
        assert resp.status_code == 404

    def test_requires_auth(self, client: TestClient) -> None:
        resp = client.get("/api/me/memory-playlists/sp_abc123/events")
        assert resp.status_code == 401
