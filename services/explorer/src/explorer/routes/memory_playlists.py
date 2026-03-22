"""Memory playlists page — assistant-tracked playlists from the playlist ledger."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from explorer.api_client import (
    ApiError,
    ExplorerApiClient,
    MemoryPlaylistDetail,
    PaginatedMemoryPlaylistEvents,
    PaginatedMemoryPlaylists,
)
from explorer.routes._helpers import require_login, safe_int


class MemoryPlaylistsRouter:
    """Memory playlist listing, detail, and event partial views."""

    def __init__(self) -> None:
        self.router = APIRouter()
        self.router.add_api_route("/", self.list_playlists, methods=["GET"], response_class=HTMLResponse)
        self.router.add_api_route("/{playlist_id}", self.playlist_detail, methods=["GET"], response_class=HTMLResponse)
        self.router.add_api_route(
            "/{playlist_id}/partials/events",
            self.events_partial,
            methods=["GET"],
            response_class=HTMLResponse,
        )

    async def list_playlists(self, request: Request) -> HTMLResponse:
        """Render memory playlists grid with pagination."""
        token = require_login(request)
        if isinstance(token, RedirectResponse):
            return token  # type: ignore[return-value]

        api: ExplorerApiClient = request.app.state.api
        error: str | None = None
        limit = safe_int(request.query_params.get("limit"), 20)
        offset = safe_int(request.query_params.get("offset"), 0)
        playlists_data: PaginatedMemoryPlaylists = {"items": [], "total": 0, "limit": limit, "offset": offset}

        try:
            playlists_data = await api.get_memory_playlists(token, limit=limit, offset=offset)
        except ApiError as e:
            if e.status_code == 401:
                return RedirectResponse(url="/login", status_code=303)  # type: ignore[return-value]
            error = e.detail

        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            request,
            "memory_playlists.html",
            {
                "active_page": "playlists",
                "data": playlists_data,
                "error": error,
            },
        )

    async def playlist_detail(self, request: Request, playlist_id: str) -> HTMLResponse:
        """Render memory playlist detail with track IDs and mutation events."""
        token = require_login(request)
        if isinstance(token, RedirectResponse):
            return token  # type: ignore[return-value]

        api: ExplorerApiClient = request.app.state.api
        error: str | None = None
        playlist: MemoryPlaylistDetail | None = None

        try:
            playlist = await api.get_memory_playlist(token, playlist_id)
        except ApiError as e:
            if e.status_code == 401:
                return RedirectResponse(url="/login", status_code=303)  # type: ignore[return-value]
            error = e.detail

        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            request,
            "memory_playlist_detail.html",
            {
                "active_page": "playlists",
                "playlist": playlist,
                "error": error,
            },
        )

    async def events_partial(self, request: Request, playlist_id: str) -> HTMLResponse:
        """HTMX partial returning paginated mutation events for a memory playlist."""
        token = require_login(request)
        if isinstance(token, RedirectResponse):
            return token  # type: ignore[return-value]

        api: ExplorerApiClient = request.app.state.api
        limit = safe_int(request.query_params.get("limit"), 20)
        offset = safe_int(request.query_params.get("offset"), 0)
        events_data: PaginatedMemoryPlaylistEvents = {"items": [], "total": 0, "limit": limit, "offset": offset}

        try:
            events_data = await api.get_memory_playlist_events(token, playlist_id, limit=limit, offset=offset)
        except ApiError as e:
            if e.status_code == 401:
                return RedirectResponse(url="/login", status_code=303)  # type: ignore[return-value]

        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            request,
            "partials/_memory_playlist_events.html",
            {
                "events": events_data,
                "playlist_id": playlist_id,
            },
        )


_instance = MemoryPlaylistsRouter()
router = _instance.router
