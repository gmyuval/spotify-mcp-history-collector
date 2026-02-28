"""Profile page — user account and Spotify connection management."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from explorer.api_client import ApiError, ExplorerApiClient
from explorer.routes._helpers import require_login
from explorer.settings import ExplorerSettings


class ProfileRouter:
    """Profile page with account info and Spotify connection management."""

    def __init__(self) -> None:
        self.router = APIRouter()
        self.router.add_api_route("/profile", self.profile, methods=["GET"], response_class=HTMLResponse)

    async def profile(self, request: Request) -> HTMLResponse:
        """Render user profile page."""
        token = require_login(request)
        if isinstance(token, RedirectResponse):
            return token  # type: ignore[return-value]

        api: ExplorerApiClient = request.app.state.api
        settings: ExplorerSettings = request.app.state.settings
        error: str | None = None
        profile_data: dict[str, object] = {}

        try:
            profile_data = await api.get_profile(token)
        except ApiError as e:
            if e.status_code == 401:
                return RedirectResponse(url="/login", status_code=303)  # type: ignore[return-value]
            error = e.detail

        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "profile.html",
            {
                "request": request,
                "active_page": "profile",
                "profile": profile_data,
                "api_public_url": settings.API_PUBLIC_URL,
                "explorer_base_url": settings.EXPLORER_BASE_URL,
                "error": error,
            },
        )


_instance = ProfileRouter()
router = _instance.router
