"""Tests for collection-level playlist cache freshness (#50).

Verifies that staleness is determined by sync_checkpoints.playlist_cache_synced_at
rather than max(CachedPlaylist.fetched_at).
"""

from collections.abc import AsyncGenerator, Generator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.auth.jwt import JWTService
from app.main import app
from app.settings import AppSettings, get_settings
from shared.db.base import Base
from shared.db.models.cache import CachedPlaylist
from shared.db.models.operations import SyncCheckpoint
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


async def _seed_user_with_rbac(session: AsyncSession) -> int:
    """Create a user with own_data.view permission; return user_id."""
    user = User(spotify_user_id="freshness_test_user", display_name="Freshness Tester")
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
    return user.id


def _auth_cookies(jwt_service: JWTService, user_id: int) -> dict[str, str]:
    token = jwt_service.create_access_token(user_id)
    return {"access_token": token}


@pytest.fixture
async def fresh_cache(async_engine: AsyncEngine) -> dict[str, object]:
    """User + recent checkpoint + 1 playlist."""
    now = datetime.now(UTC)
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        user_id = await _seed_user_with_rbac(session)
        session.add(SyncCheckpoint(user_id=user_id, playlist_cache_synced_at=now))
        session.add(
            CachedPlaylist(
                spotify_playlist_id="pl_fresh",
                user_id=user_id,
                name="Fresh Playlist",
                total_tracks=3,
                fetched_at=now,
            )
        )
        await session.commit()
        return {"user_id": user_id}


@pytest.fixture
async def stale_cache(async_engine: AsyncEngine) -> dict[str, object]:
    """User + old checkpoint (2h) + playlist with recent fetched_at.

    Key scenario from #50: individual row looks fresh but collection is stale.
    """
    now = datetime.now(UTC)
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        user_id = await _seed_user_with_rbac(session)
        session.add(SyncCheckpoint(user_id=user_id, playlist_cache_synced_at=now - timedelta(hours=2)))
        # Individual playlist was fetched recently — old code would consider this fresh
        session.add(
            CachedPlaylist(
                spotify_playlist_id="pl_recent",
                user_id=user_id,
                name="Recently Touched Playlist",
                total_tracks=5,
                fetched_at=now,
            )
        )
        await session.commit()
        return {"user_id": user_id}


@pytest.fixture
async def no_checkpoint(async_engine: AsyncEngine) -> dict[str, object]:
    """User + playlist but NO checkpoint (pre-migration data)."""
    now = datetime.now(UTC)
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        user_id = await _seed_user_with_rbac(session)
        session.add(
            CachedPlaylist(
                spotify_playlist_id="pl_old",
                user_id=user_id,
                name="Old Playlist",
                total_tracks=2,
                fetched_at=now,
            )
        )
        await session.commit()
        return {"user_id": user_id}


@pytest.fixture
def client(
    async_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[TestClient]:
    """TestClient with DB + auth overrides — matches test_endpoints.py pattern."""
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
    monkeypatch.setattr("app.explorer.services.playlist_service.get_settings", _test_settings)

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


class TestPlaylistCacheFreshness:
    """Verify collection-level freshness via playlist_cache_synced_at."""

    def test_fresh_cache_skips_refresh(
        self,
        client: TestClient,
        fresh_cache: dict[str, object],
        jwt_service: JWTService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When playlist_cache_synced_at is recent, refresh is NOT called."""

        async def _unexpected_refresh(*args: object, **kwargs: object) -> None:
            raise AssertionError("_fetch_playlists_from_spotify should not run for fresh cache")

        monkeypatch.setattr(
            "app.explorer.services.playlist_service.PlaylistService._fetch_playlists_from_spotify",
            _unexpected_refresh,
        )
        user_id: int = fresh_cache["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/playlists", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Fresh Playlist"

    def test_stale_checkpoint_triggers_refresh(
        self,
        client: TestClient,
        stale_cache: dict[str, object],
        jwt_service: JWTService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When checkpoint is old, refresh IS called.

        Refresh returns None (simulating Spotify unavailable), stale DB data returned as fallback.
        """
        refresh_called = False

        async def _spy_refresh(*args: object, **kwargs: object) -> None:
            nonlocal refresh_called
            refresh_called = True
            return None

        monkeypatch.setattr(
            "app.explorer.services.playlist_service.PlaylistService._fetch_playlists_from_spotify",
            _spy_refresh,
        )
        user_id: int = stale_cache["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/playlists", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        assert refresh_called is True
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Recently Touched Playlist"

    def test_no_checkpoint_triggers_refresh(
        self,
        client: TestClient,
        no_checkpoint: dict[str, object],
        jwt_service: JWTService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When no checkpoint exists, cache is stale — refresh IS called.

        Refresh returns None, DB data returned as fallback.
        """
        refresh_called = False

        async def _spy_refresh(*args: object, **kwargs: object) -> None:
            nonlocal refresh_called
            refresh_called = True
            return None

        monkeypatch.setattr(
            "app.explorer.services.playlist_service.PlaylistService._fetch_playlists_from_spotify",
            _spy_refresh,
        )
        user_id: int = no_checkpoint["user_id"]  # type: ignore[assignment]
        resp = client.get("/api/me/playlists", cookies=_auth_cookies(jwt_service, user_id))
        assert resp.status_code == 200
        assert refresh_called is True
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Old Playlist"
