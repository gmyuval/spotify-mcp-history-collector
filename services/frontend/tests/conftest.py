"""Test fixtures for the admin frontend."""

from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from frontend.api_client import AdminApiClient


def _default_mock_api() -> AsyncMock:
    """Create a mock AdminApiClient with sensible default return values."""
    api = AsyncMock(spec=AdminApiClient)

    api.get_sync_status.return_value = {
        "total_users": 3,
        "active_syncs": 1,
        "paused_users": 1,
        "errored_users": 0,
        "users": [
            {"id": 1, "display_name": "Alice", "sync_status": "idle"},
            {"id": 2, "display_name": "Bob", "sync_status": "paused"},
        ],
    }
    api.list_users.return_value = {
        "items": [
            {"id": 1, "spotify_id": "user1", "display_name": "Alice", "sync_status": "idle"},
            {"id": 2, "spotify_id": "user2", "display_name": "Bob", "sync_status": "paused"},
        ],
        "total": 2,
    }
    api.get_user.return_value = {
        "id": 1,
        "spotify_id": "user1",
        "display_name": "Alice",
        "sync_status": "idle",
        "email": "alice@example.com",
    }
    api.list_job_runs.return_value = {"items": [], "total": 0}
    api.list_import_jobs.return_value = {"items": [], "total": 0}
    api.list_logs.return_value = {"items": [], "total": 0}
    api.pause_user.return_value = {"message": "User paused"}
    api.resume_user.return_value = {"message": "User resumed"}
    api.trigger_sync.return_value = {"message": "Sync triggered"}
    api.delete_user.return_value = {"message": "User deleted"}
    api.upload_import.return_value = {"id": 42, "status": "pending"}
    api.purge_logs.return_value = {"message": "Purged 10 logs"}

    # RBAC defaults
    api.list_roles.return_value = [
        {
            "id": 1,
            "name": "admin",
            "description": "System administrator",
            "is_system": True,
            "permissions": [{"id": 1, "codename": "admin:access", "description": "Admin panel access"}],
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        },
        {
            "id": 2,
            "name": "viewer",
            "description": "Read-only access",
            "is_system": False,
            "permissions": [],
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        },
    ]
    api.list_permissions.return_value = [
        {"id": 1, "codename": "admin:access", "description": "Admin panel access"},
        {"id": 2, "codename": "users:read", "description": "View users"},
    ]
    api.create_role.return_value = {
        "id": 3,
        "name": "editor",
        "description": None,
        "is_system": False,
        "permissions": [],
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00",
    }
    api.update_role.return_value = {
        "id": 2,
        "name": "viewer",
        "description": "Updated",
        "is_system": False,
        "permissions": [],
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00",
    }
    api.delete_role.return_value = {"message": "Role deleted"}
    api.get_user_roles.return_value = {"user_id": 1, "roles": []}
    api.set_user_roles.return_value = {"message": "Roles updated"}

    return api


@pytest.fixture
def mock_api() -> AsyncMock:
    """Mock AdminApiClient with default return values for all methods."""
    return _default_mock_api()


@pytest.fixture
def client(mock_api: AsyncMock) -> Generator[TestClient]:
    """TestClient with mock API client injected via overridden lifespan."""
    from frontend.main import app

    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def _test_lifespan(a: FastAPI) -> AsyncGenerator[None]:
        a.state.api = mock_api
        yield

    app.router.lifespan_context = _test_lifespan
    try:
        with TestClient(app) as tc:
            yield tc
    finally:
        app.router.lifespan_context = original_lifespan
