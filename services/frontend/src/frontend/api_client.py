"""Typed async HTTP client for the admin API."""

import base64
from typing import Any

import httpx


class ApiError(Exception):
    """Raised when the admin API returns a non-2xx response."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"API error {status_code}: {detail}")


def build_auth_headers(
    auth_mode: str,
    token: str = "",
    username: str = "",
    password: str = "",
) -> dict[str, str]:
    """Build Authorization header based on auth mode."""
    if auth_mode == "token" and token:
        return {"Authorization": f"Bearer {token}"}
    if auth_mode == "basic" and username and password:
        encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
        return {"Authorization": f"Basic {encoded}"}
    return {}


class AdminApiClient:
    """Async HTTP client wrapping all admin API endpoints."""

    def __init__(self, base_url: str, auth_headers: dict[str, str]) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers=auth_headers,
            timeout=30.0,
        )

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Make an API request and return JSON response."""
        response = await self._client.request(method, path, **kwargs)
        if response.status_code >= 400:
            detail = response.text
            try:
                body = response.json()
                detail = body.get("detail", detail)
            except Exception:
                pass
            raise ApiError(response.status_code, detail)
        return response.json()  # type: ignore[no-any-return]

    # --- User Management ---

    async def list_users(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """GET /admin/users — paginated user list."""
        return await self._request("GET", "/admin/users", params={"limit": limit, "offset": offset})

    async def get_user(self, user_id: int) -> dict[str, Any]:
        """GET /admin/users/{user_id} — user detail."""
        return await self._request("GET", f"/admin/users/{user_id}")

    async def pause_user(self, user_id: int) -> dict[str, Any]:
        """POST /admin/users/{user_id}/pause."""
        return await self._request("POST", f"/admin/users/{user_id}/pause")

    async def resume_user(self, user_id: int) -> dict[str, Any]:
        """POST /admin/users/{user_id}/resume."""
        return await self._request("POST", f"/admin/users/{user_id}/resume")

    async def trigger_sync(self, user_id: int) -> dict[str, Any]:
        """POST /admin/users/{user_id}/trigger-sync."""
        return await self._request("POST", f"/admin/users/{user_id}/trigger-sync")

    async def delete_user(self, user_id: int) -> dict[str, Any]:
        """DELETE /admin/users/{user_id}."""
        return await self._request("DELETE", f"/admin/users/{user_id}")

    # --- Imports ---

    async def upload_import(
        self,
        user_id: int,
        file_content: bytes,
        filename: str,
    ) -> dict[str, Any]:
        """POST /admin/users/{user_id}/import — upload ZIP."""
        return await self._request(
            "POST",
            f"/admin/users/{user_id}/import",
            files={"file": (filename, file_content, "application/zip")},
        )

    async def get_import_job(self, job_id: int) -> dict[str, Any]:
        """GET /admin/import-jobs/{job_id}."""
        return await self._request("GET", f"/admin/import-jobs/{job_id}")

    async def list_import_jobs(
        self,
        user_id: int | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """GET /admin/import-jobs — paginated import job list."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if user_id is not None:
            params["user_id"] = user_id
        if status:
            params["status"] = status
        return await self._request("GET", "/admin/import-jobs", params=params)

    # --- Operations ---

    async def get_sync_status(self) -> dict[str, Any]:
        """GET /admin/sync-status — global sync overview."""
        return await self._request("GET", "/admin/sync-status")

    async def list_job_runs(
        self,
        user_id: int | None = None,
        job_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """GET /admin/job-runs — paginated job run history."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if user_id is not None:
            params["user_id"] = user_id
        if job_type:
            params["job_type"] = job_type
        if status:
            params["status"] = status
        return await self._request("GET", "/admin/job-runs", params=params)

    # --- Logs ---

    async def list_logs(
        self,
        service: str | None = None,
        level: str | None = None,
        user_id: int | None = None,
        q: str | None = None,
        since: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """GET /admin/logs — paginated log query."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if service:
            params["service"] = service
        if level:
            params["level"] = level
        if user_id is not None:
            params["user_id"] = user_id
        if q:
            params["q"] = q
        if since:
            params["since"] = since
        return await self._request("GET", "/admin/logs", params=params)

    async def purge_logs(self, older_than_days: int | None = None) -> dict[str, Any]:
        """POST /admin/maintenance/purge-logs."""
        params: dict[str, Any] = {}
        if older_than_days is not None:
            params["older_than_days"] = older_than_days
        return await self._request("POST", "/admin/maintenance/purge-logs", params=params)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
