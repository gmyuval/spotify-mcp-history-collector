"""Tests for PermissionChecker service."""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.auth.permissions import PermissionChecker
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
async def checker() -> PermissionChecker:
    return PermissionChecker()


@pytest.fixture
async def seeded_data(session: AsyncSession) -> dict[str, int]:
    """Seed a user, roles, permissions, and links. Returns IDs."""
    # User
    user = User(spotify_user_id="perm_user", display_name="Perm Test")
    session.add(user)
    await session.flush()

    # Permissions
    p_manage = Permission(codename="users.manage", description="Manage users")
    p_view = Permission(codename="own_data.view", description="View own data")
    p_mcp = Permission(codename="mcp_tools.use", description="Use MCP tools")
    p_export = Permission(codename="own_data.export", description="Export data")
    session.add_all([p_manage, p_view, p_mcp, p_export])
    await session.flush()

    # Roles
    admin_role = Role(name="admin", description="Full access", is_system=True)
    user_role = Role(name="user", description="Standard user", is_system=True)
    session.add_all([admin_role, user_role])
    await session.flush()

    # Admin gets all permissions
    for p in [p_manage, p_view, p_mcp, p_export]:
        session.add(RolePermission(role_id=admin_role.id, permission_id=p.id))

    # User role gets view + mcp
    session.add(RolePermission(role_id=user_role.id, permission_id=p_view.id))
    session.add(RolePermission(role_id=user_role.id, permission_id=p_mcp.id))
    await session.flush()

    return {
        "user_id": user.id,
        "admin_role_id": admin_role.id,
        "user_role_id": user_role.id,
    }


# ------------------------------------------------------------------
# PermissionChecker tests
# ------------------------------------------------------------------


class TestPermissionChecker:
    """Tests for PermissionChecker.has_permission and get_user_permissions."""

    async def test_no_roles_no_permissions(
        self, checker: PermissionChecker, session: AsyncSession, seeded_data: dict[str, int]
    ) -> None:
        user_id = seeded_data["user_id"]
        perms = await checker.get_user_permissions(user_id, session)
        assert perms == set()

    async def test_has_permission_returns_false_without_role(
        self, checker: PermissionChecker, session: AsyncSession, seeded_data: dict[str, int]
    ) -> None:
        user_id = seeded_data["user_id"]
        result = await checker.has_permission(user_id, "users.manage", session)
        assert result is False

    async def test_user_role_permissions(
        self, checker: PermissionChecker, session: AsyncSession, seeded_data: dict[str, int]
    ) -> None:
        user_id = seeded_data["user_id"]
        session.add(UserRole(user_id=user_id, role_id=seeded_data["user_role_id"]))
        await session.flush()

        perms = await checker.get_user_permissions(user_id, session)
        assert perms == {"own_data.view", "mcp_tools.use"}

    async def test_has_permission_granted(
        self, checker: PermissionChecker, session: AsyncSession, seeded_data: dict[str, int]
    ) -> None:
        user_id = seeded_data["user_id"]
        session.add(UserRole(user_id=user_id, role_id=seeded_data["user_role_id"]))
        await session.flush()

        assert await checker.has_permission(user_id, "own_data.view", session) is True
        assert await checker.has_permission(user_id, "mcp_tools.use", session) is True

    async def test_has_permission_denied(
        self, checker: PermissionChecker, session: AsyncSession, seeded_data: dict[str, int]
    ) -> None:
        user_id = seeded_data["user_id"]
        session.add(UserRole(user_id=user_id, role_id=seeded_data["user_role_id"]))
        await session.flush()

        assert await checker.has_permission(user_id, "users.manage", session) is False

    async def test_admin_role_has_all_permissions(
        self, checker: PermissionChecker, session: AsyncSession, seeded_data: dict[str, int]
    ) -> None:
        user_id = seeded_data["user_id"]
        session.add(UserRole(user_id=user_id, role_id=seeded_data["admin_role_id"]))
        await session.flush()

        perms = await checker.get_user_permissions(user_id, session)
        assert perms == {"users.manage", "own_data.view", "mcp_tools.use", "own_data.export"}

    async def test_multiple_roles_merge_permissions(
        self, checker: PermissionChecker, session: AsyncSession, seeded_data: dict[str, int]
    ) -> None:
        user_id = seeded_data["user_id"]
        # Assign both roles — permissions should be union (no duplicates)
        session.add(UserRole(user_id=user_id, role_id=seeded_data["admin_role_id"]))
        session.add(UserRole(user_id=user_id, role_id=seeded_data["user_role_id"]))
        await session.flush()

        perms = await checker.get_user_permissions(user_id, session)
        assert perms == {"users.manage", "own_data.view", "mcp_tools.use", "own_data.export"}

    async def test_get_user_roles(
        self, checker: PermissionChecker, session: AsyncSession, seeded_data: dict[str, int]
    ) -> None:
        user_id = seeded_data["user_id"]
        session.add(UserRole(user_id=user_id, role_id=seeded_data["user_role_id"]))
        await session.flush()

        roles = await checker.get_user_roles(user_id, session)
        assert len(roles) == 1
        assert roles[0]["name"] == "user"
        assert roles[0]["is_system"] is True

    async def test_get_user_roles_empty(
        self, checker: PermissionChecker, session: AsyncSession, seeded_data: dict[str, int]
    ) -> None:
        user_id = seeded_data["user_id"]
        roles = await checker.get_user_roles(user_id, session)
        assert roles == []


class TestRoleAssignment:
    """Tests for PermissionChecker.assign_role and revoke_role."""

    async def test_assign_role(
        self, checker: PermissionChecker, session: AsyncSession, seeded_data: dict[str, int]
    ) -> None:
        user_id = seeded_data["user_id"]
        result = await checker.assign_role(user_id, "user", session)
        assert result is True

        roles = await checker.get_user_roles(user_id, session)
        assert len(roles) == 1
        assert roles[0]["name"] == "user"

    async def test_assign_role_idempotent(
        self, checker: PermissionChecker, session: AsyncSession, seeded_data: dict[str, int]
    ) -> None:
        user_id = seeded_data["user_id"]
        assert await checker.assign_role(user_id, "user", session) is True
        assert await checker.assign_role(user_id, "user", session) is False

        roles = await checker.get_user_roles(user_id, session)
        assert len(roles) == 1

    async def test_assign_nonexistent_role_raises(
        self, checker: PermissionChecker, session: AsyncSession, seeded_data: dict[str, int]
    ) -> None:
        user_id = seeded_data["user_id"]
        with pytest.raises(ValueError, match="Role not found: nonexistent"):
            await checker.assign_role(user_id, "nonexistent", session)

    async def test_revoke_role(
        self, checker: PermissionChecker, session: AsyncSession, seeded_data: dict[str, int]
    ) -> None:
        user_id = seeded_data["user_id"]
        await checker.assign_role(user_id, "user", session)
        result = await checker.revoke_role(user_id, "user", session)
        assert result is True

        roles = await checker.get_user_roles(user_id, session)
        assert roles == []

    async def test_revoke_role_not_assigned(
        self, checker: PermissionChecker, session: AsyncSession, seeded_data: dict[str, int]
    ) -> None:
        user_id = seeded_data["user_id"]
        result = await checker.revoke_role(user_id, "user", session)
        assert result is False

    async def test_revoke_nonexistent_role_raises(
        self, checker: PermissionChecker, session: AsyncSession, seeded_data: dict[str, int]
    ) -> None:
        user_id = seeded_data["user_id"]
        with pytest.raises(ValueError, match="Role not found: nonexistent"):
            await checker.revoke_role(user_id, "nonexistent", session)

    async def test_assign_revoke_permissions_updated(
        self, checker: PermissionChecker, session: AsyncSession, seeded_data: dict[str, int]
    ) -> None:
        user_id = seeded_data["user_id"]

        # Initially no permissions
        assert await checker.get_user_permissions(user_id, session) == set()

        # Assign user role → gains permissions
        await checker.assign_role(user_id, "user", session)
        perms = await checker.get_user_permissions(user_id, session)
        assert "own_data.view" in perms
        assert "mcp_tools.use" in perms

        # Revoke user role → loses permissions
        await checker.revoke_role(user_id, "user", session)
        assert await checker.get_user_permissions(user_id, session) == set()
