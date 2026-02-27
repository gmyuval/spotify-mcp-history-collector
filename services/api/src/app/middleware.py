"""Security and observability middleware for the API service."""

import logging
import time
import uuid
from collections import defaultdict

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from app.constants import Routes

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to every response."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "0"
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory sliding-window rate limiter.

    Keyed by client IP for auth endpoints and by Authorization header for MCP
    endpoints.
    """

    def __init__(
        self,
        app: ASGIApp,
        auth_limit: int = 10,
        mcp_limit: int = 60,
        window_seconds: int = 60,
    ) -> None:
        super().__init__(app)
        self.auth_limit = auth_limit
        self.mcp_limit = mcp_limit
        self.window = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        if path.startswith(f"{Routes.AUTH.prefix}/"):
            key = f"auth:{self._client_ip(request)}"
            limit = self.auth_limit
        elif path == f"{Routes.MCP.prefix}/call" and request.method == "POST":
            token = request.headers.get("authorization", "anon")
            key = f"mcp:{token}"
            limit = self.mcp_limit
        else:
            return await call_next(request)

        now = time.monotonic()
        self._prune(key, now)

        if len(self._hits[key]) >= limit:
            return Response(
                content='{"detail":"Rate limit exceeded. Try again later."}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": str(self.window)},
            )

        self._hits[key].append(now)
        return await call_next(request)

    def _prune(self, key: str, now: float) -> None:
        cutoff = now - self.window
        self._hits[key] = [t for t in self._hits[key] if t > cutoff]

    @staticmethod
    def _client_ip(request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Assign a unique request ID to every request.

    Sets ``request.state.request_id`` and adds an ``X-Request-ID`` response
    header so log entries can be correlated with responses.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
