"""Taste profile page — view and manage AI-curated taste preferences."""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from explorer.api_client import ApiError, ExplorerApiClient
from explorer.routes._helpers import require_login, safe_int


class TasteRouter:
    """Taste profile management page with preference event history."""

    def __init__(self) -> None:
        self.router = APIRouter()
        self.router.add_api_route("/taste", self.taste, methods=["GET"], response_class=HTMLResponse)
        self.router.add_api_route("/taste/update", self.update, methods=["POST"], response_class=HTMLResponse)
        self.router.add_api_route("/taste/clear", self.clear, methods=["POST"], response_class=HTMLResponse)
        self.router.add_api_route(
            "/taste/partials/events", self.events_partial, methods=["GET"], response_class=HTMLResponse
        )

    async def taste(self, request: Request) -> HTMLResponse:
        """Render the taste profile page."""
        token = require_login(request)
        if isinstance(token, RedirectResponse):
            return token  # type: ignore[return-value]

        api: ExplorerApiClient = request.app.state.api
        error: str | None = None
        taste_data: dict[str, Any] = {}

        try:
            taste_data = await api.get_taste_profile(token)
        except ApiError as e:
            if e.status_code == 401:
                return RedirectResponse(url="/login", status_code=303)  # type: ignore[return-value]
            error = e.detail

        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "taste.html",
            {
                "request": request,
                "active_page": "taste",
                "data": taste_data,
                "error": error,
            },
        )

    async def update(self, request: Request) -> HTMLResponse:
        """Handle profile update form submission (HTMX)."""
        token = require_login(request)
        if isinstance(token, RedirectResponse):
            return token  # type: ignore[return-value]

        api: ExplorerApiClient = request.app.state.api
        form = await request.form()

        action = str(form.get("action", ""))
        field = str(form.get("field", ""))
        value = str(form.get("value", "")).strip()

        # Build the patch based on the action
        patch: dict[str, Any] = {}
        reason: str | None = None

        if action == "add" and field and value:
            # Fetch current profile to append to existing list
            try:
                taste_data = await api.get_taste_profile(token)
                profile = taste_data.get("profile", {}).get("profile", {})
            except ApiError:
                profile = {}
            current_list: list[str] = profile.get(field, [])
            if isinstance(current_list, list) and value not in current_list:
                patch[field] = [*current_list, value]
                reason = f"Added '{value}' to {field}"

        elif action == "remove" and field and value:
            try:
                taste_data = await api.get_taste_profile(token)
                profile = taste_data.get("profile", {}).get("profile", {})
            except ApiError:
                profile = {}
            current_list = profile.get(field, [])
            if isinstance(current_list, list) and value in current_list:
                patch[field] = [item for item in current_list if item != value]
                reason = f"Removed '{value}' from {field}"

        elif action == "set" and field and value:
            patch[field] = value
            reason = f"Set {field} to '{value}'"

        if patch:
            try:
                await api.update_taste_profile(token, patch, reason)
            except ApiError:
                pass  # Error will be shown on the redirected page

        return RedirectResponse(url="/taste", status_code=303)  # type: ignore[return-value]

    async def clear(self, request: Request) -> HTMLResponse:
        """Handle clear profile button (POST with confirmation)."""
        token = require_login(request)
        if isinstance(token, RedirectResponse):
            return token  # type: ignore[return-value]

        api: ExplorerApiClient = request.app.state.api

        try:
            await api.clear_taste_profile(token)
        except ApiError:
            pass  # Error will show on redirect

        return RedirectResponse(url="/taste", status_code=303)  # type: ignore[return-value]

    async def events_partial(self, request: Request) -> HTMLResponse:
        """HTMX partial for paginated preference events."""
        token = require_login(request)
        if isinstance(token, RedirectResponse):
            return token  # type: ignore[return-value]

        api: ExplorerApiClient = request.app.state.api
        limit = safe_int(request.query_params.get("limit"), 20)
        offset = safe_int(request.query_params.get("offset"), 0)

        events_data: dict[str, Any] = {"items": [], "total": 0, "limit": limit, "offset": offset}

        try:
            events_data = await api.get_preference_events(token, limit=limit, offset=offset)
        except ApiError:
            pass

        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "partials/_taste_events.html",
            {
                "request": request,
                "events": events_data,
            },
        )


_instance = TasteRouter()
router = _instance.router
