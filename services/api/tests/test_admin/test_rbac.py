"""Tests for admin RBAC endpoints (roles CRUD and user role assignment)."""

from collections.abc import AsyncGenerator, Generator

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.dependencies import db_manager
from app.main import app
from app.settings import AppSettings, get_settings
from shared.db.base import Base
from shared.db.models.rbac import Permission, Role, RolePermission
from shared.db.models.user import User

TEST_FERNET_KEY = Fernet.generate_key().decode()


def _test_settings() -> AppSettings:
    return AppSettings(
        SPOTIFY_CLIENT_ID="test-id",
        SPOTIFY_CLIENT_SECRET="test-secret",
        TOKEN_ENCRYPTION_KEY=TEST_FERNET_KEY,
        ADMIN_AUTH_MODE="",
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
def client(async_engine: AsyncEngine) -> Generator[TestClient]:
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
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
async def seeded_rbac(async_engine: AsyncEngine) -> dict[str, int]:
    """Seed permissions, a system role, and a user for RBAC tests."""
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        p1 = Permission(codename="users.manage", description="Manage users")
        p2 = Permission(codename="own_data.view", description="View own data")
        p3 = Permission(codename="mcp_tools.use", description="Use MCP tools")
        session.add_all([p1, p2, p3])
        await session.flush()

        admin_role = Role(name="admin", description="Full access", is_system=True)
        session.add(admin_role)
        await session.flush()
        session.add_all(
            [
                RolePermission(role_id=admin_role.id, permission_id=p1.id),
                RolePermission(role_id=admin_role.id, permission_id=p2.id),
                RolePermission(role_id=admin_role.id, permission_id=p3.id),
            ]
        )

        user = User(spotify_user_id="rbac_user", display_name="RBAC Test")
        session.add(user)
        await session.flush()
        await session.commit()

        return {
            "user_id": user.id,
            "admin_role_id": admin_role.id,
            "p1_id": p1.id,
            "p2_id": p2.id,
            "p3_id": p3.id,
        }


# --- List roles ---


def test_list_roles(client: TestClient, seeded_rbac: dict[str, int]) -> None:
    resp = client.get("/admin/roles")
    assert resp.status_code == 200
    roles = resp.json()
    assert len(roles) == 1
    assert roles[0]["name"] == "admin"
    assert roles[0]["is_system"] is True
    assert len(roles[0]["permissions"]) == 3


# --- List permissions ---


def test_list_permissions(client: TestClient, seeded_rbac: dict[str, int]) -> None:
    resp = client.get("/admin/permissions")
    assert resp.status_code == 200
    perms = resp.json()
    assert len(perms) == 3
    codenames = {p["codename"] for p in perms}
    assert codenames == {"users.manage", "own_data.view", "mcp_tools.use"}


# --- Create role ---


def test_create_role(client: TestClient, seeded_rbac: dict[str, int]) -> None:
    resp = client.post(
        "/admin/roles",
        json={"name": "editor", "description": "Can edit", "permission_codenames": ["users.manage", "own_data.view"]},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "editor"
    assert data["is_system"] is False
    assert len(data["permissions"]) == 2


def test_create_role_no_permissions(client: TestClient, seeded_rbac: dict[str, int]) -> None:
    resp = client.post("/admin/roles", json={"name": "empty_role"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["permissions"] == []


def test_create_role_duplicate_name(client: TestClient, seeded_rbac: dict[str, int]) -> None:
    resp = client.post("/admin/roles", json={"name": "admin"})
    assert resp.status_code == 409


def test_create_role_invalid_permission(client: TestClient, seeded_rbac: dict[str, int]) -> None:
    resp = client.post("/admin/roles", json={"name": "bad", "permission_codenames": ["nonexistent.perm"]})
    assert resp.status_code == 400
    assert "nonexistent.perm" in resp.json()["detail"]


# --- Update role ---


def test_update_role_permissions(client: TestClient, seeded_rbac: dict[str, int]) -> None:
    create_resp = client.post("/admin/roles", json={"name": "custom", "permission_codenames": ["users.manage"]})
    role_id = create_resp.json()["id"]

    resp = client.put(f"/admin/roles/{role_id}", json={"permission_codenames": ["own_data.view", "mcp_tools.use"]})
    assert resp.status_code == 200
    codenames = {p["codename"] for p in resp.json()["permissions"]}
    assert codenames == {"own_data.view", "mcp_tools.use"}


def test_update_role_name(client: TestClient, seeded_rbac: dict[str, int]) -> None:
    create_resp = client.post("/admin/roles", json={"name": "old_name"})
    role_id = create_resp.json()["id"]

    resp = client.put(f"/admin/roles/{role_id}", json={"name": "new_name"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "new_name"


def test_update_system_role_rename_fails(client: TestClient, seeded_rbac: dict[str, int]) -> None:
    role_id = seeded_rbac["admin_role_id"]
    resp = client.put(f"/admin/roles/{role_id}", json={"name": "super-admin"})
    assert resp.status_code == 400
    assert "system" in resp.json()["detail"].lower()


def test_update_system_role_permissions_ok(client: TestClient, seeded_rbac: dict[str, int]) -> None:
    """System roles can have their permissions changed."""
    role_id = seeded_rbac["admin_role_id"]
    resp = client.put(f"/admin/roles/{role_id}", json={"permission_codenames": ["users.manage"]})
    assert resp.status_code == 200
    assert len(resp.json()["permissions"]) == 1


def test_update_role_not_found(client: TestClient, seeded_rbac: dict[str, int]) -> None:
    resp = client.put("/admin/roles/9999", json={"name": "whatever"})
    assert resp.status_code == 404


# --- Delete role ---


def test_delete_custom_role(client: TestClient, seeded_rbac: dict[str, int]) -> None:
    create_resp = client.post("/admin/roles", json={"name": "temp"})
    role_id = create_resp.json()["id"]

    resp = client.delete(f"/admin/roles/{role_id}")
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    # Verify it's gone
    roles = client.get("/admin/roles").json()
    assert all(r["name"] != "temp" for r in roles)


def test_delete_system_role_fails(client: TestClient, seeded_rbac: dict[str, int]) -> None:
    role_id = seeded_rbac["admin_role_id"]
    resp = client.delete(f"/admin/roles/{role_id}")
    assert resp.status_code == 400


def test_delete_role_not_found(client: TestClient, seeded_rbac: dict[str, int]) -> None:
    resp = client.delete("/admin/roles/9999")
    assert resp.status_code == 404


# --- User roles ---


def test_get_user_roles_empty(client: TestClient, seeded_rbac: dict[str, int]) -> None:
    uid = seeded_rbac["user_id"]
    resp = client.get(f"/admin/users/{uid}/roles")
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == uid
    assert data["roles"] == []


def test_set_user_roles(client: TestClient, seeded_rbac: dict[str, int]) -> None:
    uid = seeded_rbac["user_id"]
    rid = seeded_rbac["admin_role_id"]

    resp = client.put(f"/admin/users/{uid}/roles", json={"role_ids": [rid]})
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    roles_resp = client.get(f"/admin/users/{uid}/roles")
    data = roles_resp.json()
    assert len(data["roles"]) == 1
    assert data["roles"][0]["name"] == "admin"


def test_set_user_roles_replaces(client: TestClient, seeded_rbac: dict[str, int]) -> None:
    uid = seeded_rbac["user_id"]
    rid = seeded_rbac["admin_role_id"]

    client.put(f"/admin/users/{uid}/roles", json={"role_ids": [rid]})
    client.put(f"/admin/users/{uid}/roles", json={"role_ids": []})

    roles_resp = client.get(f"/admin/users/{uid}/roles")
    assert roles_resp.json()["roles"] == []


def test_set_user_roles_invalid_role(client: TestClient, seeded_rbac: dict[str, int]) -> None:
    uid = seeded_rbac["user_id"]
    resp = client.put(f"/admin/users/{uid}/roles", json={"role_ids": [9999]})
    assert resp.status_code == 400


def test_get_user_roles_user_not_found(client: TestClient, seeded_rbac: dict[str, int]) -> None:
    resp = client.get("/admin/users/9999/roles")
    assert resp.status_code == 404
