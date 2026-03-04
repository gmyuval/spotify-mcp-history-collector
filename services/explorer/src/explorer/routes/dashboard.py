"""Dashboard page — listening stats overview."""

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from explorer.api_client import ApiError, ExplorerApiClient, PaginatedMemoryPlaylists
from explorer.routes._helpers import require_login

logger = logging.getLogger(__name__)


class DashboardRouter:
    """Dashboard page showing user's listening stats."""

    def __init__(self) -> None:
        self.router = APIRouter()
        self.router.add_api_route("/dashboard", self.dashboard, methods=["GET"], response_class=HTMLResponse)

    async def dashboard(self, request: Request) -> HTMLResponse:
        """Render the main dashboard with stats, top artists, and top tracks."""
        token = require_login(request)
        if isinstance(token, RedirectResponse):
            return token  # type: ignore[return-value]

        api: ExplorerApiClient = request.app.state.api
        error: str | None = None
        dashboard_data: dict[str, object] = {}
        taste_data: dict[str, Any] = {}

        try:
            dashboard_data = await api.get_dashboard(token)
        except ApiError as e:
            if e.status_code == 401:
                return RedirectResponse(url="/login", status_code=303)  # type: ignore[return-value]
            error = e.detail

        try:
            taste_data = await api.get_taste_profile(token)
        except ApiError as e:
            if e.status_code == 401:
                return RedirectResponse(url="/login", status_code=303)  # type: ignore[return-value]
            # Taste profile is optional — don't error the page for non-auth failures

        memory_playlists_data: PaginatedMemoryPlaylists | None = None
        try:
            memory_playlists_data = await api.get_memory_playlists(token, limit=5, offset=0)
        except ApiError as e:
            if e.status_code == 401:
                return RedirectResponse(url="/login", status_code=303)  # type: ignore[return-value]
            # Memory playlists are optional — don't error the page for non-auth failures
            logger.warning("dashboard memory playlists fetch failed", extra={"status_code": e.status_code})

        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "dashboard.html",
            {
                "request": request,
                "active_page": "dashboard",
                "data": dashboard_data,
                "taste": taste_data,
                "memory_playlists": memory_playlists_data,
                "error": error,
            },
        )


_instance = DashboardRouter()
router = _instance.router
