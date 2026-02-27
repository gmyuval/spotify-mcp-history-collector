"""Tests for AdminApiClient and auth header helpers."""

import httpx
import pytest
import respx

from frontend.api_client import AdminApiClient, ApiError, build_auth_headers

BASE_URL = "http://test-api:8000"
AUTH = {"Authorization": "Bearer test-token"}


# --- build_auth_headers ---


def test_build_auth_headers_token() -> None:
    headers = build_auth_headers("token", token="my-secret")
    assert headers == {"Authorization": "Bearer my-secret"}


def test_build_auth_headers_basic() -> None:
    headers = build_auth_headers("basic", username="admin", password="secret")
    assert "Authorization" in headers
    assert headers["Authorization"].startswith("Basic ")


def test_build_auth_headers_empty_mode() -> None:
    assert build_auth_headers("") == {}


def test_build_auth_headers_token_mode_no_token() -> None:
    assert build_auth_headers("token", token="") == {}


# --- AdminApiClient methods ---


@respx.mock
async def test_list_users() -> None:
    respx.get(f"{BASE_URL}/admin/users").mock(return_value=httpx.Response(200, json={"items": [{"id": 1}], "total": 1}))
    api = AdminApiClient(base_url=BASE_URL, auth_headers=AUTH)
    result = await api.list_users(limit=10, offset=0)
    assert result["total"] == 1
    assert len(result["items"]) == 1
    await api.close()


@respx.mock
async def test_get_user() -> None:
    respx.get(f"{BASE_URL}/admin/users/1").mock(
        return_value=httpx.Response(200, json={"id": 1, "display_name": "Alice"})
    )
    api = AdminApiClient(base_url=BASE_URL, auth_headers=AUTH)
    result = await api.get_user(1)
    assert result["id"] == 1
    assert result["display_name"] == "Alice"
    await api.close()


@respx.mock
async def test_pause_user() -> None:
    respx.post(f"{BASE_URL}/admin/users/1/pause").mock(return_value=httpx.Response(200, json={"message": "paused"}))
    api = AdminApiClient(base_url=BASE_URL, auth_headers=AUTH)
    result = await api.pause_user(1)
    assert result["message"] == "paused"
    await api.close()


@respx.mock
async def test_resume_user() -> None:
    respx.post(f"{BASE_URL}/admin/users/1/resume").mock(return_value=httpx.Response(200, json={"message": "resumed"}))
    api = AdminApiClient(base_url=BASE_URL, auth_headers=AUTH)
    result = await api.resume_user(1)
    assert result["message"] == "resumed"
    await api.close()


@respx.mock
async def test_trigger_sync() -> None:
    respx.post(f"{BASE_URL}/admin/users/1/trigger-sync").mock(
        return_value=httpx.Response(200, json={"message": "sync triggered"})
    )
    api = AdminApiClient(base_url=BASE_URL, auth_headers=AUTH)
    result = await api.trigger_sync(1)
    assert result["message"] == "sync triggered"
    await api.close()


@respx.mock
async def test_delete_user() -> None:
    respx.delete(f"{BASE_URL}/admin/users/1").mock(return_value=httpx.Response(200, json={"message": "deleted"}))
    api = AdminApiClient(base_url=BASE_URL, auth_headers=AUTH)
    result = await api.delete_user(1)
    assert result["message"] == "deleted"
    await api.close()


@respx.mock
async def test_upload_import() -> None:
    route = respx.post(f"{BASE_URL}/admin/users/1/import").mock(return_value=httpx.Response(200, json={"id": 42}))
    api = AdminApiClient(base_url=BASE_URL, auth_headers=AUTH)
    result = await api.upload_import(1, b"zip-content", "export.zip")
    assert result["id"] == 42
    assert route.called
    await api.close()


@respx.mock
async def test_list_import_jobs_with_filters() -> None:
    route = respx.get(f"{BASE_URL}/admin/import-jobs").mock(
        return_value=httpx.Response(200, json={"items": [], "total": 0})
    )
    api = AdminApiClient(base_url=BASE_URL, auth_headers=AUTH)
    result = await api.list_import_jobs(user_id=1, status="pending")
    assert result["total"] == 0
    # Verify filter params were sent
    req = route.calls[0].request
    assert "user_id=1" in str(req.url)
    assert "status=pending" in str(req.url)
    await api.close()


@respx.mock
async def test_get_sync_status() -> None:
    respx.get(f"{BASE_URL}/admin/sync-status").mock(return_value=httpx.Response(200, json={"total_users": 5}))
    api = AdminApiClient(base_url=BASE_URL, auth_headers=AUTH)
    result = await api.get_sync_status()
    assert result["total_users"] == 5
    await api.close()


@respx.mock
async def test_list_job_runs_with_filters() -> None:
    route = respx.get(f"{BASE_URL}/admin/job-runs").mock(
        return_value=httpx.Response(200, json={"items": [], "total": 0})
    )
    api = AdminApiClient(base_url=BASE_URL, auth_headers=AUTH)
    result = await api.list_job_runs(job_type="poll", status="success")
    assert result["total"] == 0
    req = route.calls[0].request
    assert "job_type=poll" in str(req.url)
    assert "status=success" in str(req.url)
    await api.close()


@respx.mock
async def test_list_logs() -> None:
    respx.get(f"{BASE_URL}/admin/logs").mock(return_value=httpx.Response(200, json={"items": [{"id": 1}], "total": 1}))
    api = AdminApiClient(base_url=BASE_URL, auth_headers=AUTH)
    result = await api.list_logs(service="api", level="error")
    assert result["total"] == 1
    await api.close()


@respx.mock
async def test_purge_logs() -> None:
    respx.post(f"{BASE_URL}/admin/maintenance/purge-logs").mock(
        return_value=httpx.Response(200, json={"message": "purged 10 records"})
    )
    api = AdminApiClient(base_url=BASE_URL, auth_headers=AUTH)
    result = await api.purge_logs(older_than_days=30)
    assert result["message"] == "purged 10 records"
    await api.close()


# --- Error handling ---


@respx.mock
async def test_error_response_json_detail() -> None:
    respx.get(f"{BASE_URL}/admin/users").mock(return_value=httpx.Response(404, json={"detail": "Not found"}))
    api = AdminApiClient(base_url=BASE_URL, auth_headers=AUTH)
    with pytest.raises(ApiError) as exc_info:
        await api.list_users()
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Not found"
    await api.close()


@respx.mock
async def test_error_response_plain_text() -> None:
    respx.get(f"{BASE_URL}/admin/users").mock(return_value=httpx.Response(500, text="Internal Server Error"))
    api = AdminApiClient(base_url=BASE_URL, auth_headers=AUTH)
    with pytest.raises(ApiError) as exc_info:
        await api.list_users()
    assert exc_info.value.status_code == 500
    assert "Internal Server Error" in exc_info.value.detail
    await api.close()


@respx.mock
async def test_auth_header_forwarded() -> None:
    route = respx.get(f"{BASE_URL}/admin/sync-status").mock(return_value=httpx.Response(200, json={}))
    api = AdminApiClient(base_url=BASE_URL, auth_headers={"Authorization": "Bearer my-secret"})
    await api.get_sync_status()
    assert route.calls[0].request.headers["Authorization"] == "Bearer my-secret"
    await api.close()


# --- RBAC ---


@respx.mock
async def test_list_roles() -> None:
    respx.get(f"{BASE_URL}/admin/roles").mock(return_value=httpx.Response(200, json=[{"id": 1, "name": "admin"}]))
    api = AdminApiClient(base_url=BASE_URL, auth_headers=AUTH)
    result = await api.list_roles()
    assert len(result) == 1
    assert result[0]["name"] == "admin"
    await api.close()


@respx.mock
async def test_list_permissions() -> None:
    respx.get(f"{BASE_URL}/admin/permissions").mock(
        return_value=httpx.Response(200, json=[{"id": 1, "codename": "roles.manage"}])
    )
    api = AdminApiClient(base_url=BASE_URL, auth_headers=AUTH)
    result = await api.list_permissions()
    assert len(result) == 1
    assert result[0]["codename"] == "roles.manage"
    await api.close()


@respx.mock
async def test_create_role() -> None:
    route = respx.post(f"{BASE_URL}/admin/roles").mock(
        return_value=httpx.Response(201, json={"id": 3, "name": "editor"})
    )
    api = AdminApiClient(base_url=BASE_URL, auth_headers=AUTH)
    result = await api.create_role(name="editor", description="Can edit", permission_codenames=["roles.manage"])
    assert result["name"] == "editor"
    body = route.calls[0].request.content
    assert b"editor" in body
    await api.close()


@respx.mock
async def test_update_role() -> None:
    route = respx.put(f"{BASE_URL}/admin/roles/2").mock(
        return_value=httpx.Response(200, json={"id": 2, "name": "viewer"})
    )
    api = AdminApiClient(base_url=BASE_URL, auth_headers=AUTH)
    result = await api.update_role(role_id=2, name="viewer", permission_codenames=["users.view_all"])
    assert result["id"] == 2
    assert route.called
    await api.close()


@respx.mock
async def test_delete_role() -> None:
    respx.delete(f"{BASE_URL}/admin/roles/2").mock(return_value=httpx.Response(200, json={"message": "Role deleted"}))
    api = AdminApiClient(base_url=BASE_URL, auth_headers=AUTH)
    result = await api.delete_role(2)
    assert result["message"] == "Role deleted"
    await api.close()


@respx.mock
async def test_get_user_roles() -> None:
    respx.get(f"{BASE_URL}/admin/users/1/roles").mock(
        return_value=httpx.Response(200, json={"user_id": 1, "roles": [{"id": 1, "name": "admin"}]})
    )
    api = AdminApiClient(base_url=BASE_URL, auth_headers=AUTH)
    result = await api.get_user_roles(1)
    assert result["user_id"] == 1
    assert len(result["roles"]) == 1
    await api.close()


@respx.mock
async def test_set_user_roles() -> None:
    route = respx.put(f"{BASE_URL}/admin/users/1/roles").mock(
        return_value=httpx.Response(200, json={"message": "Roles updated"})
    )
    api = AdminApiClient(base_url=BASE_URL, auth_headers=AUTH)
    result = await api.set_user_roles(1, [1, 2])
    assert result["message"] == "Roles updated"
    body = route.calls[0].request.content
    assert b"role_ids" in body
    await api.close()
