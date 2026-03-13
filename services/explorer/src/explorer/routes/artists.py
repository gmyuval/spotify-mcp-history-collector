"""Artists browser page — paginated artist listing with search and sort."""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from explorer.api_client import ApiError, ExplorerApiClient
from explorer.routes._helpers import require_login, safe_int


class ArtistsRouter:
    """Paginated artist browser with search, sort, and optional time window."""

    def __init__(self) -> None:
        self.router = APIRouter()
        self.router.add_api_route("/", self.artists, methods=["GET"], response_class=HTMLResponse)
        self.router.add_api_route(
            "/partials/artists-table", self.artists_table_partial, methods=["GET"], response_class=HTMLResponse
        )
        self.router.add_api_route("/{artist_id}", self.artist_detail, methods=["GET"], response_class=HTMLResponse)

    async def _fetch_artists(self, request: Request, token: str) -> dict[str, Any]:
        """Shared logic for fetching artists data from the API."""
        api: ExplorerApiClient = request.app.state.api
        limit = safe_int(request.query_params.get("limit"), 50)
        offset = safe_int(request.query_params.get("offset"), 0)
        sort = request.query_params.get("sort", "play_count")
        q = request.query_params.get("q", "")
        days_str = request.query_params.get("days")
        days = safe_int(days_str, 0) if days_str else None

        data = await api.get_artists(token, limit=limit, offset=offset, sort=sort, q=q or None, days=days)
        return {"data": data, "limit": limit, "offset": offset, "sort": sort, "q": q, "days": days}

    async def artists(self, request: Request) -> HTMLResponse:
        """Render the full artists browser page."""
        token = require_login(request)
        if isinstance(token, RedirectResponse):
            return token  # type: ignore[return-value]

        error: str | None = None
        context: dict[str, Any] = {
            "data": {"items": [], "total": 0, "limit": 50, "offset": 0},
            "limit": 50,
            "offset": 0,
            "sort": "play_count",
            "q": "",
            "days": None,
        }

        try:
            context = await self._fetch_artists(request, token)
        except ApiError as e:
            if e.status_code == 401:
                return RedirectResponse(url="/login", status_code=303)  # type: ignore[return-value]
            error = e.detail

        data = context["data"]
        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "artists.html",
            {
                "request": request,
                "active_page": "artists",
                "items": data.get("items", []),
                "total": data.get("total", 0),
                "limit": context["limit"],
                "offset": context["offset"],
                "sort": context["sort"],
                "q": context["q"],
                "days": context["days"],
                "error": error,
            },
        )

    async def artists_table_partial(self, request: Request) -> HTMLResponse:
        """HTMX partial — artists table body with pagination."""
        token = require_login(request)
        if isinstance(token, RedirectResponse):
            return token  # type: ignore[return-value]

        try:
            context = await self._fetch_artists(request, token)
        except ApiError as e:
            if e.status_code == 401:
                return RedirectResponse(url="/login", status_code=303)  # type: ignore[return-value]
            context = {
                "data": {"items": [], "total": 0},
                "limit": 50,
                "offset": 0,
                "sort": "play_count",
                "q": "",
                "days": None,
            }

        data = context["data"]
        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "partials/_artists_table.html",
            {
                "request": request,
                "items": data.get("items", []),
                "total": data.get("total", 0),
                "limit": context["limit"],
                "offset": context["offset"],
                "sort": context["sort"],
                "q": context["q"],
                "days": context["days"],
            },
        )

    async def artist_detail(self, request: Request, artist_id: int) -> HTMLResponse:
        """Placeholder for artist detail page (Phase 4)."""
        token = require_login(request)
        if isinstance(token, RedirectResponse):
            return token  # type: ignore[return-value]

        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "coming_soon.html",
            {"request": request, "active_page": "artists", "entity_type": "Artist", "back_url": "/artists"},
        )


_instance = ArtistsRouter()
router = _instance.router
