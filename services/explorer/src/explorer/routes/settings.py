"""Settings page — API token management for Claude Desktop / Claude Code."""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from explorer.api_client import ApiError, ExplorerApiClient
from explorer.routes._helpers import require_login


class SettingsRouter:
    """Token management settings page."""

    def __init__(self) -> None:
        self.router = APIRouter()
        self.router.add_api_route("/settings/tokens", self.tokens, methods=["GET"], response_class=HTMLResponse)
        self.router.add_api_route(
            "/settings/tokens/create", self.create_token, methods=["POST"], response_class=HTMLResponse
        )
        self.router.add_api_route(
            "/settings/tokens/revoke", self.revoke_token, methods=["POST"], response_class=HTMLResponse
        )

    async def tokens(self, request: Request) -> HTMLResponse:
        """Render the token management page."""
        token = require_login(request)
        if isinstance(token, RedirectResponse):
            return token  # type: ignore[return-value]

        api: ExplorerApiClient = request.app.state.api
        error: str | None = None
        tokens_data: dict[str, Any] = {"items": []}

        # Check for a newly created token to display
        new_token: str | None = request.query_params.get("new_token")
        new_token_name: str | None = request.query_params.get("new_token_name")

        try:
            tokens_data = await api.get_tokens(token)
        except ApiError as e:
            if e.status_code == 401:
                return RedirectResponse(url="/login", status_code=303)  # type: ignore[return-value]
            error = e.detail

        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            "settings/tokens.html",
            {
                "request": request,
                "active_page": "settings",
                "tokens": tokens_data.get("items", []),
                "error": error,
                "new_token": new_token,
                "new_token_name": new_token_name,
            },
        )

    async def create_token(self, request: Request) -> HTMLResponse:
        """Handle token creation form submission."""
        token = require_login(request)
        if isinstance(token, RedirectResponse):
            return token  # type: ignore[return-value]

        api: ExplorerApiClient = request.app.state.api
        form = await request.form()
        name = str(form.get("name", "")).strip()

        if not name:
            return RedirectResponse(url="/settings/tokens", status_code=303)  # type: ignore[return-value]

        try:
            result = await api.create_token(token, name)
            # Pass the newly created token via query params so it can be shown once
            raw_token = result.get("token", "")
            return RedirectResponse(  # type: ignore[return-value]
                url=f"/settings/tokens?new_token={raw_token}&new_token_name={name}",
                status_code=303,
            )
        except ApiError as e:
            if e.status_code == 401:
                return RedirectResponse(url="/login", status_code=303)  # type: ignore[return-value]
            return RedirectResponse(url="/settings/tokens", status_code=303)  # type: ignore[return-value]

    async def revoke_token(self, request: Request) -> HTMLResponse:
        """Handle token revocation."""
        token = require_login(request)
        if isinstance(token, RedirectResponse):
            return token  # type: ignore[return-value]

        api: ExplorerApiClient = request.app.state.api
        form = await request.form()
        token_id_str = str(form.get("token_id", ""))

        try:
            token_id = int(token_id_str)
            await api.revoke_token(token, token_id)
        except ValueError, TypeError:
            pass
        except ApiError:
            pass

        return RedirectResponse(url="/settings/tokens", status_code=303)  # type: ignore[return-value]


_instance = SettingsRouter()
router = _instance.router
