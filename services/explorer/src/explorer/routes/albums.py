"""Album detail page."""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from explorer.api_client import ApiError, ExplorerApiClient
from explorer.routes._helpers import require_login

logger = logging.getLogger(__name__)


class AlbumsRouter:
    """Album detail page."""

    def __init__(self) -> None:
        self.router = APIRouter()
        self.router.add_api_route(
            "/{album_spotify_id}", self.album_detail, methods=["GET"], response_class=HTMLResponse
        )

    async def album_detail(self, request: Request, album_spotify_id: str) -> HTMLResponse:
        """Album detail page with track listing and stats."""
        token = require_login(request)
        if isinstance(token, RedirectResponse):
            return token  # type: ignore[return-value]

        api: ExplorerApiClient = request.app.state.api
        try:
            data = await api.get_album_detail(token, album_spotify_id)
        except ApiError as e:
            if e.status_code == 401:
                return RedirectResponse(url="/login", status_code=303)  # type: ignore[return-value]
            if e.status_code == 404:
                return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
                    "error.html",
                    {
                        "request": request,
                        "active_page": "tracks",
                        "error_title": "Album Not Found",
                        "error_message": "This album does not exist or you have no listening data for it.",
                        "back_url": "/tracks",
                        "back_label": "Back to Tracks",
                    },
                    status_code=404,
                )
            logger.warning("Error loading album %s: %s (status %d)", album_spotify_id, e.detail, e.status_code)
            return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
                "error.html",
                {
                    "request": request,
                    "active_page": "tracks",
                    "error_title": "Error Loading Album",
                    "error_message": "An unexpected error occurred. Please try again later.",
                    "back_url": "/tracks",
                    "back_label": "Back to Tracks",
                },
                status_code=e.status_code,
            )

        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "album_detail.html",
            {"request": request, "active_page": "tracks", "album": data},
        )


_instance = AlbumsRouter()
router = _instance.router
