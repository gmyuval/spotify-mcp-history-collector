"""Settings page — API token management for Claude Desktop / Claude Code."""

import secrets
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from explorer.api_client import ApiError, ExplorerApiClient
from explorer.routes._helpers import require_login

# Short-lived in-memory store for newly created tokens.
# Keyed by random nonce; each entry is consumed (popped) on first read.
_pending_tokens: dict[str, dict[str, Any]] = {}

_PENDING_TOKEN_MAX_AGE_S = 300  # 5 minutes
_PENDING_TOKEN_MAX_ENTRIES = 100


def _cleanup_pending_tokens() -> None:
    """Remove expired entries and cap total size."""
    now = time.monotonic()
    expired = [k for k, v in _pending_tokens.items() if now - v["created_at"] > _PENDING_TOKEN_MAX_AGE_S]
    for k in expired:
        _pending_tokens.pop(k, None)
    # If still over limit, remove oldest entries
    if len(_pending_tokens) > _PENDING_TOKEN_MAX_ENTRIES:
        by_age = sorted(_pending_tokens.items(), key=lambda kv: kv[1]["created_at"])
        for k, _ in by_age[: len(_pending_tokens) - _PENDING_TOKEN_MAX_ENTRIES]:
            _pending_tokens.pop(k, None)


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

        try:
            tokens_data = await api.get_tokens(token)
        except ApiError as e:
            if e.status_code == 401:
                return RedirectResponse(url="/login", status_code=303)  # type: ignore[return-value]
            error = e.detail

        # Consume the nonce only after page data is ready — avoids burning the
        # single-use token if the API call above fails.
        new_token: str | None = None
        new_token_name: str | None = None
        nonce = request.query_params.get("nonce")
        if nonce and error is None:
            _cleanup_pending_tokens()
            pending = _pending_tokens.pop(nonce, None)
            if pending:
                new_token = pending["token"]
                new_token_name = pending["name"]

        # Surface create/revoke errors passed via query param
        if error is None:
            error = request.query_params.get("error")

        return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
            request,
            "settings/tokens.html",
            {
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
            raw_token = result.get("token", "")
            # Store token in short-lived memory, redirect with opaque nonce only
            _cleanup_pending_tokens()
            nonce = secrets.token_urlsafe(32)
            _pending_tokens[nonce] = {
                "token": raw_token,
                "name": name,
                "created_at": time.monotonic(),
            }
            return RedirectResponse(  # type: ignore[return-value]
                url=f"/settings/tokens?nonce={nonce}",
                status_code=303,
            )
        except ApiError as e:
            if e.status_code == 401:
                return RedirectResponse(url="/login", status_code=303)  # type: ignore[return-value]
            from urllib.parse import quote

            return RedirectResponse(  # type: ignore[return-value]
                url=f"/settings/tokens?error={quote(e.detail)}",
                status_code=303,
            )

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
        except ApiError as e:
            if e.status_code == 401:
                return RedirectResponse(url="/login", status_code=303)  # type: ignore[return-value]
            from urllib.parse import quote

            return RedirectResponse(  # type: ignore[return-value]
                url=f"/settings/tokens?error={quote(e.detail)}",
                status_code=303,
            )

        return RedirectResponse(url="/settings/tokens", status_code=303)  # type: ignore[return-value]


_instance = SettingsRouter()
router = _instance.router
