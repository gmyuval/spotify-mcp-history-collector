"""Playlists page — cached playlist grid and detail view."""

from urllib.parse import quote, urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from explorer.api_client import ApiError, ExplorerApiClient
from explorer.routes._helpers import require_login


class PlaylistsRouter:
    """Playlist listing and detail views."""

    def __init__(self) -> None:
        self.router = APIRouter()
        self.router.add_api_route("/", self.playlists, methods=["GET"], response_class=HTMLResponse)
        self.router.add_api_route("/{spotify_playlist_id}/fetch-tracks", self.fetch_tracks, methods=["POST"])
        self.router.add_api_route(
            "/{spotify_playlist_id}", self.playlist_detail, methods=["GET"], response_class=HTMLResponse
        )

    async def playlists(self, request: Request) -> HTMLResponse:
        """Render playlists grid."""
        token = require_login(request)
        if isinstance(token, RedirectResponse):
            return token  # type: ignore[return-value]

        api: ExplorerApiClient = request.app.state.api
        error: str | None = None
        playlists: list[dict[str, object]] = []

        try:
            playlists = await api.get_playlists(token)
        except ApiError as e:
            if e.status_code == 401:
                return RedirectResponse(url="/login", status_code=303)  # type: ignore[return-value]
            error = e.detail

        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "playlists.html",
            {
                "request": request,
                "active_page": "playlists",
                "playlists": playlists,
                "error": error,
            },
        )

    async def playlist_detail(self, request: Request, spotify_playlist_id: str) -> HTMLResponse:
        """Render playlist detail with tracks."""
        # Guard against "memory" being matched as a playlist ID — redirect to AI playlists
        if spotify_playlist_id == "memory":
            return RedirectResponse(url="/playlists/memory/", status_code=301)  # type: ignore[return-value]

        token = require_login(request)
        if isinstance(token, RedirectResponse):
            return token  # type: ignore[return-value]

        api: ExplorerApiClient = request.app.state.api
        error: str | None = None
        playlist: dict[str, object] = {}

        try:
            playlist = await api.get_playlist(token, spotify_playlist_id)
        except ApiError as e:
            if e.status_code == 401:
                return RedirectResponse(url="/login", status_code=303)  # type: ignore[return-value]
            error = e.detail

        fetch_error = request.query_params.get("fetch_error")

        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "playlist_detail.html",
            {
                "request": request,
                "active_page": "playlists",
                "playlist": playlist,
                "error": error,
                "fetch_error": fetch_error,
            },
        )

    async def fetch_tracks(self, request: Request, spotify_playlist_id: str) -> RedirectResponse:
        """Fetch tracks from Spotify API and redirect back to playlist detail."""
        token = require_login(request)
        if isinstance(token, RedirectResponse):
            return token

        api: ExplorerApiClient = request.app.state.api
        try:
            await api.fetch_playlist_tracks(token, spotify_playlist_id)
        except ApiError as e:
            if e.status_code == 401:
                return RedirectResponse(url="/login", status_code=303)
            qs = urlencode({"fetch_error": e.detail})
            return RedirectResponse(url=f"/playlists/{quote(spotify_playlist_id)}?{qs}", status_code=303)
        return RedirectResponse(url=f"/playlists/{quote(spotify_playlist_id)}", status_code=303)


_instance = PlaylistsRouter()
router = _instance.router
