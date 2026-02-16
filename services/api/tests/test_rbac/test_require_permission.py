"""Tests for require_permission FastAPI dependency."""

from collections.abc import AsyncGenerator
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.admin.auth import require_permission
from shared.db.base import Base
from shared.db.models.rbac import Permission, Role, RolePermission, UserRole
from shared.db.models.user import User


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
async def session(async_engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess
        await sess.commit()


@pytest.fixture
async def seeded_data(session: AsyncSession) -> dict[str, int]:
    """Seed user, role, permissions, and links."""
    user = User(spotify_user_id="dep_user", display_name="Dep Test")
    session.add(user)
    await session.flush()

    perm_view = Permission(codename="own_data.view", description="View own data")
    perm_manage = Permission(codename="users.manage", description="Manage users")
    session.add_all([perm_view, perm_manage])
    await session.flush()

    role = Role(name="user", description="Standard user", is_system=True)
    session.add(role)
    await session.flush()

    session.add(RolePermission(role_id=role.id, permission_id=perm_view.id))
    session.add(UserRole(user_id=user.id, role_id=role.id))
    await session.flush()

    return {"user_id": user.id, "role_id": role.id}


def _make_request(user_id: int | None = None, db_session: AsyncSession | None = None) -> MagicMock:
    """Create a mock Request with optional state attributes."""
    request = MagicMock()
    state = MagicMock()

    if user_id is not None:
        state.user_id = user_id
    else:
        del state.user_id

    if db_session is not None:
        state.db_session = db_session
    else:
        del state.db_session

    request.state = state
    return request


class TestRequirePermission:
    """Tests for the require_permission dependency factory."""

    async def test_missing_user_id_raises_401(self) -> None:
        dep = require_permission("own_data.view")
        request = _make_request(user_id=None)

        with pytest.raises(HTTPException) as exc_info:
            await dep(request)
        assert exc_info.value.status_code == 401

    async def test_missing_db_session_raises_500(self) -> None:
        dep = require_permission("own_data.view")
        request = _make_request(user_id=1, db_session=None)

        with pytest.raises(HTTPException) as exc_info:
            await dep(request)
        assert exc_info.value.status_code == 500

    async def test_permission_granted(self, session: AsyncSession, seeded_data: dict[str, int]) -> None:
        dep = require_permission("own_data.view")
        request = _make_request(user_id=seeded_data["user_id"], db_session=session)

        result = await dep(request)
        assert result == seeded_data["user_id"]

    async def test_permission_denied_raises_403(self, session: AsyncSession, seeded_data: dict[str, int]) -> None:
        dep = require_permission("users.manage")
        request = _make_request(user_id=seeded_data["user_id"], db_session=session)

        with pytest.raises(HTTPException) as exc_info:
            await dep(request)
        assert exc_info.value.status_code == 403
        assert "users.manage" in str(exc_info.value.detail)

    async def test_different_permissions_different_results(
        self, session: AsyncSession, seeded_data: dict[str, int]
    ) -> None:
        request = _make_request(user_id=seeded_data["user_id"], db_session=session)

        # own_data.view is granted
        dep_view = require_permission("own_data.view")
        result = await dep_view(request)
        assert result == seeded_data["user_id"]

        # users.manage is NOT granted
        dep_manage = require_permission("users.manage")
        with pytest.raises(HTTPException) as exc_info:
            await dep_manage(request)
        assert exc_info.value.status_code == 403
