"""Roles management pages — class-based router for RBAC role CRUD."""

import asyncio
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from frontend.api_client import AdminApiClient, ApiError


class RolesRouter:
    """Class-based router for roles management pages."""

    def __init__(self) -> None:
        self.router = APIRouter()
        self.router.add_api_route("/", self.list_roles, methods=["GET"], response_class=HTMLResponse)
        self.router.add_api_route("/create", self.create_role, methods=["POST"], response_class=HTMLResponse)
        self.router.add_api_route("/{role_id}/update", self.update_role, methods=["POST"], response_class=HTMLResponse)
        self.router.add_api_route("/{role_id}/delete", self.delete_role, methods=["POST"], response_class=HTMLResponse)

    async def list_roles(self, request: Request) -> HTMLResponse:
        """Render roles management page."""
        api: AdminApiClient = request.app.state.api
        error: str | None = None
        roles: list[Any] = []
        permissions: list[Any] = []

        try:
            roles, permissions = await asyncio.gather(
                api.list_roles(),
                api.list_permissions(),
            )
        except ApiError as e:
            error = e.detail

        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "roles.html",
            {
                "request": request,
                "active_page": "roles",
                "roles": roles,
                "permissions": permissions,
                "error": error,
            },
        )

    async def create_role(self, request: Request) -> HTMLResponse:
        """Create a new role — HTMX form submission."""
        api: AdminApiClient = request.app.state.api
        form = await request.form()
        name = str(form.get("name", "")).strip()
        description = str(form.get("description", "")).strip() or None
        perm_codenames = [str(v) for v in form.getlist("permissions")]

        if not name:
            return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
                "partials/_alert.html",
                {"request": request, "alert_type": "danger", "message": "Role name is required"},
            )

        try:
            await api.create_role(name=name, description=description, permission_codenames=perm_codenames)
            return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
                "partials/_alert.html",
                {"request": request, "alert_type": "success", "message": f"Role '{name}' created"},
            )
        except ApiError as e:
            return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
                "partials/_alert.html",
                {"request": request, "alert_type": "danger", "message": e.detail},
            )

    async def update_role(self, request: Request, role_id: int) -> HTMLResponse:
        """Update a role — HTMX form submission."""
        api: AdminApiClient = request.app.state.api
        form = await request.form()
        name = str(form.get("name", "")).strip() or None
        description = str(form.get("description", "")).strip()
        perm_codenames = [str(v) for v in form.getlist("permissions")]

        try:
            await api.update_role(
                role_id=role_id,
                name=name,
                description=description,
                permission_codenames=perm_codenames,
            )
            return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
                "partials/_alert.html",
                {"request": request, "alert_type": "success", "message": "Role updated"},
            )
        except ApiError as e:
            return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
                "partials/_alert.html",
                {"request": request, "alert_type": "danger", "message": e.detail},
            )

    async def delete_role(self, request: Request, role_id: int) -> HTMLResponse:
        """Delete a role — HTMX button click."""
        api: AdminApiClient = request.app.state.api
        try:
            result = await api.delete_role(role_id)
            return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
                "partials/_alert.html",
                {"request": request, "alert_type": "success", "message": result.get("message", "Role deleted")},
            )
        except ApiError as e:
            return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
                "partials/_alert.html",
                {"request": request, "alert_type": "danger", "message": e.detail},
            )


_instance = RolesRouter()
router = _instance.router
