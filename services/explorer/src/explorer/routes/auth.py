"""Auth routes — login page and logout."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response


class AuthRouter:
    """Handles login/logout for the explorer frontend."""

    def __init__(self) -> None:
        self.router = APIRouter()
        self.router.add_api_route("/login", self.login_page, methods=["GET"], response_class=HTMLResponse)
        self.router.add_api_route("/logout", self.logout, methods=["POST"], response_model=None)

    async def login_page(self, request: Request) -> HTMLResponse:
        """Show login page.

        In production (behind oauth2-proxy), users rarely reach this page
        because the GoogleAuthMiddleware bridges Google auth to JWT automatically.
        This page serves as a fallback or when JWT exchange fails.
        """
        # If already logged in, redirect to dashboard
        if request.cookies.get("access_token"):
            return RedirectResponse(url="/dashboard", status_code=303)  # type: ignore[return-value]
        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "login.html", {"request": request}
        )

    async def logout(self, request: Request) -> Response:
        """Clear auth cookies and redirect to Google sign-out."""
        # Clear JWT cookies then redirect to oauth2-proxy sign-out
        # which clears the Google OAuth session and redirects to login
        response = RedirectResponse(url="/oauth2/sign_out?rd=/login", status_code=303)
        response.delete_cookie("access_token", path="/")
        response.delete_cookie("refresh_token", path="/")
        return response


_instance = AuthRouter()
router = _instance.router
