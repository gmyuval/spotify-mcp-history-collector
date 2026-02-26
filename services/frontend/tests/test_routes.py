"""Tests for frontend route handlers."""

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from frontend.api_client import ApiError

# --- Health check ---


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


# --- Dashboard ---


def test_dashboard_page(client: TestClient, mock_api: AsyncMock) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Dashboard" in response.text
    mock_api.get_sync_status.assert_called_once()
    mock_api.list_job_runs.assert_any_call(limit=5)
    mock_api.list_job_runs.assert_any_call(status="running", limit=10)
    mock_api.list_import_jobs.assert_any_call(limit=5)


def test_dashboard_sync_status_partial(client: TestClient, mock_api: AsyncMock) -> None:
    response = client.get("/partials/sync-status")
    assert response.status_code == 200
    mock_api.get_sync_status.assert_called_once()


def test_dashboard_api_error(client: TestClient, mock_api: AsyncMock) -> None:
    mock_api.get_sync_status.side_effect = ApiError(503, "Service unavailable")
    response = client.get("/")
    assert response.status_code == 200
    assert "Service unavailable" in response.text


# --- Users ---


def test_users_list_page(client: TestClient, mock_api: AsyncMock) -> None:
    response = client.get("/users")
    assert response.status_code == 200
    assert "Users" in response.text
    mock_api.list_users.assert_called_once_with(limit=50, offset=0)


def test_users_table_partial(client: TestClient, mock_api: AsyncMock) -> None:
    response = client.get("/users/partials/users-table?limit=10&offset=20")
    assert response.status_code == 200
    mock_api.list_users.assert_called_once_with(limit=10, offset=20)


def test_user_detail_page(client: TestClient, mock_api: AsyncMock) -> None:
    response = client.get("/users/1")
    assert response.status_code == 200
    mock_api.get_user.assert_called_once_with(1)
    mock_api.list_job_runs.assert_called_once_with(user_id=1, limit=10)
    mock_api.list_import_jobs.assert_called_once_with(user_id=1, limit=10)


def test_user_pause(client: TestClient, mock_api: AsyncMock) -> None:
    response = client.post("/users/1/pause")
    assert response.status_code == 200
    mock_api.pause_user.assert_called_once_with(1)


def test_user_resume(client: TestClient, mock_api: AsyncMock) -> None:
    response = client.post("/users/1/resume")
    assert response.status_code == 200
    mock_api.resume_user.assert_called_once_with(1)


def test_user_trigger_sync(client: TestClient, mock_api: AsyncMock) -> None:
    response = client.post("/users/1/trigger-sync")
    assert response.status_code == 200
    mock_api.trigger_sync.assert_called_once_with(1)


def test_user_delete(client: TestClient, mock_api: AsyncMock) -> None:
    response = client.delete("/users/1")
    assert response.status_code == 200
    assert "User deleted" in response.text
    mock_api.delete_user.assert_called_once_with(1)


# --- Jobs ---


def test_jobs_page(client: TestClient, mock_api: AsyncMock) -> None:
    response = client.get("/jobs")
    assert response.status_code == 200
    assert "Job Runs" in response.text
    mock_api.list_job_runs.assert_called_once()


def test_jobs_table_partial(client: TestClient, mock_api: AsyncMock) -> None:
    response = client.get("/jobs/partials/jobs-table?job_type=poll&status=success")
    assert response.status_code == 200
    mock_api.list_job_runs.assert_called_once_with(limit=50, offset=0, job_type="poll", status="success")


# --- Imports ---


def test_imports_page(client: TestClient, mock_api: AsyncMock) -> None:
    response = client.get("/imports")
    assert response.status_code == 200
    assert "Import" in response.text
    mock_api.list_import_jobs.assert_called_once()
    mock_api.list_users.assert_called_once_with(limit=200)


def test_imports_table_partial(client: TestClient, mock_api: AsyncMock) -> None:
    response = client.get("/imports/partials/imports-table?status=pending")
    assert response.status_code == 200
    mock_api.list_import_jobs.assert_called_once()


def test_import_upload_success(client: TestClient, mock_api: AsyncMock) -> None:
    response = client.post(
        "/imports/upload",
        data={"user_id": "1"},
        files={"file": ("export.zip", b"fake-zip", "application/zip")},
    )
    assert response.status_code == 200
    assert "42" in response.text  # import job ID
    mock_api.upload_import.assert_called_once()


def test_import_upload_missing_fields(client: TestClient, mock_api: AsyncMock) -> None:
    response = client.post("/imports/upload", data={"user_id": ""})
    assert response.status_code == 200
    assert "required" in response.text.lower()
    mock_api.upload_import.assert_not_called()


# --- Logs ---


def test_logs_page(client: TestClient, mock_api: AsyncMock) -> None:
    response = client.get("/logs")
    assert response.status_code == 200
    assert "Logs" in response.text
    mock_api.list_logs.assert_called_once()


def test_logs_table_partial(client: TestClient, mock_api: AsyncMock) -> None:
    response = client.get("/logs/partials/logs-table?service=api&level=error")
    assert response.status_code == 200
    mock_api.list_logs.assert_called_once_with(limit=50, offset=0, service="api", level="error")


def test_logs_purge(client: TestClient, mock_api: AsyncMock) -> None:
    response = client.post("/logs/purge", data={"days": "30"})
    assert response.status_code == 200
    assert "Purged" in response.text
    mock_api.purge_logs.assert_called_once_with(older_than_days=30)


def test_logs_purge_invalid_days(client: TestClient, mock_api: AsyncMock) -> None:
    response = client.post("/logs/purge", data={"days": "abc"})
    assert response.status_code == 200
    assert "Invalid" in response.text
    mock_api.purge_logs.assert_not_called()


# --- Roles ---


def test_roles_page(client: TestClient, mock_api: AsyncMock) -> None:
    response = client.get("/roles")
    assert response.status_code == 200
    assert "Roles" in response.text
    assert "admin" in response.text
    mock_api.list_roles.assert_called_once()
    mock_api.list_permissions.assert_called_once()


def test_roles_create(client: TestClient, mock_api: AsyncMock) -> None:
    response = client.post(
        "/roles/create",
        data={"name": "editor", "description": "Can edit", "permissions": ["admin:access"]},
    )
    assert response.status_code == 200
    mock_api.create_role.assert_called_once_with(
        name="editor", description="Can edit", permission_codenames=["admin:access"]
    )


def test_roles_create_empty_name(client: TestClient, mock_api: AsyncMock) -> None:
    response = client.post("/roles/create", data={"name": ""})
    assert response.status_code == 200
    assert "required" in response.text.lower()
    mock_api.create_role.assert_not_called()


def test_roles_update(client: TestClient, mock_api: AsyncMock) -> None:
    response = client.post(
        "/roles/2/update",
        data={"name": "viewer", "description": "Updated", "permissions": ["users:read"]},
    )
    assert response.status_code == 200
    mock_api.update_role.assert_called_once_with(
        role_id=2, name="viewer", description="Updated", permission_codenames=["users:read"]
    )


def test_roles_delete(client: TestClient, mock_api: AsyncMock) -> None:
    response = client.post("/roles/2/delete")
    assert response.status_code == 200
    mock_api.delete_role.assert_called_once_with(2)


def test_roles_api_error(client: TestClient, mock_api: AsyncMock) -> None:
    mock_api.list_roles.side_effect = ApiError(500, "Internal error")
    response = client.get("/roles")
    assert response.status_code == 200
    assert "Internal error" in response.text


# --- User Detail Roles ---


def test_user_detail_shows_roles(client: TestClient, mock_api: AsyncMock) -> None:
    response = client.get("/users/1")
    assert response.status_code == 200
    assert "Roles" in response.text
    mock_api.list_roles.assert_called_once()
    mock_api.get_user_roles.assert_called_once_with(1)


def test_set_user_roles(client: TestClient, mock_api: AsyncMock) -> None:
    response = client.post("/users/1/set-roles", data={"role_ids": ["1", "2"]})
    assert response.status_code == 200
    assert "updated" in response.text.lower()
    mock_api.set_user_roles.assert_called_once_with(1, [1, 2])


def test_set_user_roles_error(client: TestClient, mock_api: AsyncMock) -> None:
    mock_api.set_user_roles.side_effect = ApiError(400, "Invalid role")
    response = client.post("/users/1/set-roles", data={"role_ids": ["999"]})
    assert response.status_code == 200
    assert "Invalid role" in response.text
