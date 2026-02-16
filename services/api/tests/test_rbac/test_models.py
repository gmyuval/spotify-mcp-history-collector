"""Tests for RBAC SQLAlchemy models and PermissionChecker."""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

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
async def user(session: AsyncSession) -> User:
    user = User(spotify_user_id="rbac_user", display_name="RBAC Test User")
    session.add(user)
    await session.flush()
    return user


@pytest.fixture
async def admin_role(session: AsyncSession) -> Role:
    role = Role(name="admin", description="Full access", is_system=True)
    session.add(role)
    await session.flush()
    return role


@pytest.fixture
async def viewer_role(session: AsyncSession) -> Role:
    role = Role(name="viewer", description="Read-only", is_system=True)
    session.add(role)
    await session.flush()
    return role


@pytest.fixture
async def permissions(session: AsyncSession) -> list[Permission]:
    perms = [
        Permission(codename="users.manage", description="Manage all users"),
        Permission(codename="own_data.view", description="View own data"),
        Permission(codename="mcp_tools.use", description="Use MCP tools"),
    ]
    session.add_all(perms)
    await session.flush()
    return perms


# ------------------------------------------------------------------
# Model creation tests
# ------------------------------------------------------------------


class TestRBACModels:
    """Tests for RBAC model creation and relationships."""

    async def test_create_role(self, session: AsyncSession) -> None:
        role = Role(name="test_role", description="A test role", is_system=False)
        session.add(role)
        await session.flush()

        result = await session.execute(select(Role).where(Role.name == "test_role"))
        fetched = result.scalar_one()
        assert fetched.name == "test_role"
        assert fetched.description == "A test role"
        assert fetched.is_system is False

    async def test_create_permission(self, session: AsyncSession) -> None:
        perm = Permission(codename="test.perm", description="Test permission")
        session.add(perm)
        await session.flush()

        result = await session.execute(select(Permission).where(Permission.codename == "test.perm"))
        fetched = result.scalar_one()
        assert fetched.codename == "test.perm"

    async def test_role_permission_link(
        self, session: AsyncSession, admin_role: Role, permissions: list[Permission]
    ) -> None:
        for perm in permissions:
            session.add(RolePermission(role_id=admin_role.id, permission_id=perm.id))
        await session.flush()

        result = await session.execute(select(RolePermission).where(RolePermission.role_id == admin_role.id))
        links = result.scalars().all()
        assert len(links) == 3

    async def test_user_role_assignment(self, session: AsyncSession, user: User, admin_role: Role) -> None:
        session.add(UserRole(user_id=user.id, role_id=admin_role.id))
        await session.flush()

        result = await session.execute(select(UserRole).where(UserRole.user_id == user.id))
        user_roles = result.scalars().all()
        assert len(user_roles) == 1
        assert user_roles[0].role_id == admin_role.id

    async def test_user_multiple_roles(
        self, session: AsyncSession, user: User, admin_role: Role, viewer_role: Role
    ) -> None:
        session.add(UserRole(user_id=user.id, role_id=admin_role.id))
        session.add(UserRole(user_id=user.id, role_id=viewer_role.id))
        await session.flush()

        result = await session.execute(select(UserRole).where(UserRole.user_id == user.id))
        user_roles = result.scalars().all()
        assert len(user_roles) == 2

    async def test_role_system_flag_default(self, session: AsyncSession) -> None:
        role = Role(name="custom_role")
        session.add(role)
        await session.flush()

        result = await session.execute(select(Role).where(Role.name == "custom_role"))
        fetched = result.scalar_one()
        assert fetched.is_system is False

    async def test_role_has_timestamps(self, session: AsyncSession) -> None:
        role = Role(name="timestamped_role", is_system=False)
        session.add(role)
        await session.flush()

        result = await session.execute(select(Role).where(Role.name == "timestamped_role"))
        fetched = result.scalar_one()
        assert fetched.created_at is not None
        assert fetched.updated_at is not None
