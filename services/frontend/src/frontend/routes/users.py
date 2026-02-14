"""User management pages — class-based router for list, detail, and actions."""

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from frontend.api_client import AdminApiClient, ApiError
from frontend.routes._helpers import safe_int


class UsersRouter:
    """Class-based router for user management pages."""

    def __init__(self) -> None:
        self.router = APIRouter()
        self.router.add_api_route("/", self.list_users, methods=["GET"], response_class=HTMLResponse)
        self.router.add_api_route(
            "/partials/users-table", self.users_table_partial, methods=["GET"], response_class=HTMLResponse
        )
        self.router.add_api_route("/{user_id}", self.user_detail, methods=["GET"], response_class=HTMLResponse)
        self.router.add_api_route("/{user_id}/pause", self.pause_user, methods=["POST"], response_class=HTMLResponse)
        self.router.add_api_route("/{user_id}/resume", self.resume_user, methods=["POST"], response_class=HTMLResponse)
        self.router.add_api_route(
            "/{user_id}/trigger-sync", self.trigger_sync, methods=["POST"], response_class=HTMLResponse
        )
        self.router.add_api_route("/{user_id}", self.delete_user, methods=["DELETE"], response_class=HTMLResponse)

    async def list_users(self, request: Request) -> HTMLResponse:
        """Render users list page."""
        api: AdminApiClient = request.app.state.api
        error: str | None = None
        data: dict[str, object] = {"items": [], "total": 0, "limit": 50, "offset": 0}

        limit = safe_int(request.query_params.get("limit"), 50)
        offset = safe_int(request.query_params.get("offset"), 0)

        try:
            data = await api.list_users(limit=limit, offset=offset)
        except ApiError as e:
            error = e.detail

        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "users.html",
            {
                "request": request,
                "active_page": "users",
                "users": data.get("items", []),
                "total": data.get("total", 0),
                "limit": limit,
                "offset": offset,
                "error": error,
            },
        )

    async def users_table_partial(self, request: Request) -> HTMLResponse:
        """HTMX partial — users table body with pagination."""
        api: AdminApiClient = request.app.state.api
        limit = safe_int(request.query_params.get("limit"), 50)
        offset = safe_int(request.query_params.get("offset"), 0)

        try:
            data = await api.list_users(limit=limit, offset=offset)
        except ApiError:
            data = {"items": [], "total": 0}

        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "partials/_users_table.html",
            {
                "request": request,
                "users": data.get("items", []),
                "total": data.get("total", 0),
                "limit": limit,
                "offset": offset,
            },
        )

    async def user_detail(self, request: Request, user_id: int) -> HTMLResponse:
        """Render user detail page."""
        api: AdminApiClient = request.app.state.api
        error: str | None = None
        user: dict[str, object] = {}
        recent_jobs: list[object] = []
        recent_imports: list[object] = []

        try:
            user_result, jobs_data, imports_data = await asyncio.gather(
                api.get_user(user_id),
                api.list_job_runs(user_id=user_id, limit=10),
                api.list_import_jobs(user_id=user_id, limit=10),
            )
            user = dict(user_result)
            recent_jobs = list(jobs_data.get("items", []))
            recent_imports = list(imports_data.get("items", []))
        except ApiError as e:
            error = e.detail

        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "user_detail.html",
            {
                "request": request,
                "active_page": "users",
                "user": user,
                "recent_jobs": recent_jobs,
                "recent_imports": recent_imports,
                "error": error,
            },
        )

    async def pause_user(self, request: Request, user_id: int) -> HTMLResponse:
        """Pause sync for a user — returns action result partial."""
        return await self._user_action(request, user_id, "pause")

    async def resume_user(self, request: Request, user_id: int) -> HTMLResponse:
        """Resume sync for a user — returns action result partial."""
        return await self._user_action(request, user_id, "resume")

    async def trigger_sync(self, request: Request, user_id: int) -> HTMLResponse:
        """Trigger re-sync for a user — returns action result partial."""
        return await self._user_action(request, user_id, "trigger_sync")

    async def delete_user(self, request: Request, user_id: int) -> HTMLResponse:
        """Delete a user — returns action result partial."""
        api: AdminApiClient = request.app.state.api
        try:
            result = await api.delete_user(user_id)
            return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
                "partials/_alert.html",
                {
                    "request": request,
                    "alert_type": "success",
                    "message": result.get("message", "User deleted"),
                },
            )
        except ApiError as e:
            return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
                "partials/_alert.html",
                {"request": request, "alert_type": "danger", "message": e.detail},
            )

    async def _user_action(self, request: Request, user_id: int, action: str) -> HTMLResponse:
        """Execute a user action and return an alert partial."""
        api: AdminApiClient = request.app.state.api
        try:
            method = getattr(api, f"{action}_user" if action != "trigger_sync" else "trigger_sync")
            result = await method(user_id)
            return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
                "partials/_user_actions.html",
                {
                    "request": request,
                    "alert_type": "success",
                    "message": result.get("message", f"Action '{action}' succeeded"),
                    "user_id": user_id,
                },
            )
        except ApiError as e:
            return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
                "partials/_user_actions.html",
                {
                    "request": request,
                    "alert_type": "danger",
                    "message": e.detail,
                    "user_id": user_id,
                },
            )


_instance = UsersRouter()
router = _instance.router
