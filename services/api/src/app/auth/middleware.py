"""JWT authentication middleware — extracts user context from tokens."""

import logging

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from app.auth.jwt import JWTError, JWTService
from app.dependencies import db_manager
from app.settings import get_settings

logger = logging.getLogger(__name__)

# Paths that should never trigger JWT processing
_SKIP_PREFIXES = ("/healthz", "/docs", "/openapi.json", "/redoc")
_SKIP_EXACT = frozenset({"/", "/auth/login", "/auth/callback"})


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """Extract JWT from Authorization header or cookie, set request.state.

    Sets on every request (even if no token):
    - ``request.state.user_id``: int | None
    - ``request.state.db_session``: AsyncSession | None (for permission checks)

    This middleware is intentionally permissive: it NEVER rejects requests.
    Endpoints that require authentication use the ``require_permission``
    dependency or the existing ``require_admin`` dependency.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Process each request, extracting JWT if present."""
        # Initialize state to unauthenticated
        request.state.user_id = None
        request.state.db_session = None

        path = request.url.path
        if self._should_skip(path):
            return await call_next(request)

        token = self._extract_token(request)
        if token is None:
            return await call_next(request)

        settings = get_settings()
        jwt_service = JWTService(settings)

        try:
            user_id = jwt_service.decode_access_token(token)
        except JWTError:
            # Token is invalid or expired — treat as unauthenticated.
            return await call_next(request)

        request.state.user_id = user_id

        # Provide a DB session for permission checks via request.state.db_session.
        try:
            async with db_manager.session() as session:
                request.state.db_session = session
                response = await call_next(request)
            request.state.db_session = None
            return response
        except Exception:
            logger.debug("Could not open DB session for user %d; proceeding without", user_id)
            return await call_next(request)

    @staticmethod
    def _should_skip(path: str) -> bool:
        """Check whether a path should bypass JWT processing."""
        if path in _SKIP_EXACT:
            return True
        return any(path.startswith(prefix) for prefix in _SKIP_PREFIXES)

    @staticmethod
    def _extract_token(request: Request) -> str | None:
        """Extract JWT from Bearer header or access_token cookie.

        Bearer header takes precedence over cookies. JWTs are distinguished
        from static admin tokens by the presence of dots (header.payload.signature).
        """
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            candidate = auth_header[7:]
            # JWTs contain dots; static admin tokens don't.
            if "." in candidate:
                return candidate
            return None

        # Fall back to HTTP-only cookie
        return request.cookies.get("access_token")
