"""Settings management pages — admin-configurable settings UI."""

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from frontend.api_client import AdminApiClient, ApiError


class SettingsRouter:
    """Class-based router for settings management pages."""

    def __init__(self) -> None:
        self.router = APIRouter()
        self.router.add_api_route("/", self.list_settings, methods=["GET"], response_class=HTMLResponse)
        self.router.add_api_route(
            "/{key:path}/reset", self.reset_setting, methods=["POST"], response_class=HTMLResponse
        )
        self.router.add_api_route("/{key:path}", self.update_setting, methods=["POST"], response_class=HTMLResponse)

    async def list_settings(self, request: Request) -> HTMLResponse:
        """Render the settings management page."""
        api: AdminApiClient = request.app.state.api
        error: str | None = None
        by_category: dict[str, list[Any]] = {}

        try:
            data = await api.list_settings()
            by_category = data.get("by_category", {})
        except ApiError as e:
            error = e.detail

        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            request,
            "settings.html",
            {
                "active_page": "settings",
                "by_category": by_category,
                "error": error,
            },
        )

    async def update_setting(self, request: Request, key: str) -> HTMLResponse:
        """Update a single setting — HTMX inline save."""
        api: AdminApiClient = request.app.state.api
        form = await request.form()
        raw_value = str(form.get("value", "")).strip()

        # Parse the submitted value: try JSON first, fall back to string
        try:
            value: object = json.loads(raw_value)
        except json.JSONDecodeError, ValueError:
            value = raw_value

        try:
            updated = await api.update_setting(key, value)
            return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
                request,
                "partials/_setting_row.html",
                {"setting": updated, "flash": "Saved"},
            )
        except ApiError as e:
            return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
                request,
                "partials/_setting_row.html",
                {
                    "setting": {"key": key, "value_json": raw_value, "description": "", "category": ""},
                    "flash_error": e.detail,
                },
            )

    async def reset_setting(self, request: Request, key: str) -> HTMLResponse:
        """Reset a single setting to its default — HTMX reset button."""
        api: AdminApiClient = request.app.state.api
        try:
            await api.reset_settings(key=key)
            # Fetch the updated row to re-render it
            data = await api.list_settings()
            by_category = data.get("by_category", {})
            setting: dict[str, Any] | None = None
            for settings_list in by_category.values():
                for s in settings_list:
                    if s["key"] == key:
                        setting = s
                        break
                if setting:
                    break
            if setting is None:
                setting = {"key": key, "value_json": None, "description": "", "category": ""}
            return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
                request,
                "partials/_setting_row.html",
                {"setting": setting, "flash": "Reset to default"},
            )
        except ApiError as e:
            return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
                request,
                "partials/_alert.html",
                {"alert_type": "danger", "message": e.detail},
            )


_instance = SettingsRouter()
router = _instance.router
