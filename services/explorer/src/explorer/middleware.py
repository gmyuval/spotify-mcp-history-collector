"""Middleware that bridges Google OAuth (via oauth2-proxy) to JWT sessions.

In production, Caddy's forward_auth sends requests through oauth2-proxy,
which sets X-Auth-Request-Email on authenticated requests. This middleware
detects that header and exchanges the Google email for JWT tokens via the
API's /auth/exchange-google endpoint, then sets cookies so downstream
route handlers work with the existing JWT-based auth flow.
"""

import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from explorer.api_client import ExplorerApiClient
from explorer.settings import ExplorerSettings

logger = logging.getLogger(__name__)

# Paths that should never trigger the Google→JWT bridge
_SKIP_PATHS = frozenset({"/healthz", "/oauth2/sign_out"})
_SKIP_PREFIXES = ("/static/",)


class GoogleAuthMiddleware(BaseHTTPMiddleware):
    """Auto-bridge Google OAuth to JWT when X-Auth-Request-Email is present."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        # Skip health checks and static assets
        if path in _SKIP_PATHS or any(path.startswith(p) for p in _SKIP_PREFIXES):
            return await call_next(request)

        google_email = request.headers.get("X-Auth-Request-Email")
        access_token = request.cookies.get("access_token")

        # If Google-authenticated but no JWT cookie, exchange email for tokens
        if google_email and not access_token:
            settings: ExplorerSettings = request.app.state.settings
            api: ExplorerApiClient = request.app.state.api

            if not settings.INTERNAL_API_KEY:
                logger.error("INTERNAL_API_KEY not configured — cannot exchange Google email for JWT")
                return await call_next(request)

            tokens = await api.exchange_google_email(google_email, settings.INTERNAL_API_KEY)
            if tokens:
                access_token_val = tokens.get("access_token")
                refresh_token_val = tokens.get("refresh_token")
                user_id = tokens.get("user_id")

                if not isinstance(access_token_val, str) or not isinstance(refresh_token_val, str) or user_id is None:
                    logger.warning("Exchange response missing required token fields")
                    return await call_next(request)

                try:
                    expires_in = int(tokens.get("expires_in", 900))
                except TypeError, ValueError:
                    expires_in = 900

                # Redirect to the same URL so the browser stores the cookies
                redirect_url = str(request.url.path)
                if request.url.query:
                    redirect_url += f"?{request.url.query}"
                response = RedirectResponse(url=redirect_url, status_code=303)
                response.set_cookie(
                    key="access_token",
                    value=access_token_val,
                    max_age=expires_in,
                    httponly=True,
                    secure=True,
                    samesite="lax",
                    path="/",
                )
                response.set_cookie(
                    key="refresh_token",
                    value=refresh_token_val,
                    max_age=7 * 86400,  # 7 days
                    httponly=True,
                    secure=True,
                    samesite="lax",
                    path="/",
                )
                logger.info("Bridged Google auth to JWT for user %s", user_id)
                return response

            logger.warning("Failed to exchange Google email for JWT")
            # Fall through — route handler will redirect to /login

        return await call_next(request)
