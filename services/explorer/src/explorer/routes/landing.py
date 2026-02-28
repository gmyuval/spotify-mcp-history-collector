"""Landing page — public, no auth required."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse


class LandingRouter:
    """Public landing page for the explorer."""

    def __init__(self) -> None:
        self.router = APIRouter()
        self.router.add_api_route("/", self.landing, methods=["GET"], response_class=HTMLResponse)

    async def landing(self, request: Request) -> HTMLResponse:
        """Render the public landing page."""
        authenticated = request.cookies.get("access_token") is not None
        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "landing.html", {"request": request, "authenticated": authenticated}
        )


_instance = LandingRouter()
router = _instance.router
