"""Auth routes — login redirect and logout."""

from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from explorer.settings import ExplorerSettings


class AuthRouter:
    """Handles login/logout for the explorer frontend."""

    def __init__(self) -> None:
        self.router = APIRouter()
        self.router.add_api_route("/login", self.login_page, methods=["GET"], response_class=HTMLResponse)
        self.router.add_api_route("/login/redirect", self.login_redirect, methods=["GET"])
        self.router.add_api_route("/logout", self.logout, methods=["POST"], response_model=None)

    async def login_page(self, request: Request) -> HTMLResponse:
        """Show login page."""
        # If already logged in, redirect to dashboard
        if request.cookies.get("access_token"):
            return RedirectResponse(url="/", status_code=303)  # type: ignore[return-value]
        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "login.html", {"request": request}
        )

    async def login_redirect(self, request: Request) -> RedirectResponse:
        """Redirect to API's Spotify OAuth with next= back to explorer."""
        settings: ExplorerSettings = request.app.state.settings
        next_url = f"{settings.EXPLORER_BASE_URL}/"
        login_url = f"{settings.API_PUBLIC_URL}/auth/login?next={quote(next_url, safe='')}"
        return RedirectResponse(url=login_url, status_code=303)

    async def logout(self, request: Request) -> Response:
        """Clear auth cookies and redirect to login."""
        response = RedirectResponse(url="/login", status_code=303)
        response.delete_cookie("access_token", path="/")
        response.delete_cookie("refresh_token", path="/")
        return response


_instance = AuthRouter()
router = _instance.router
