"""JWT authentication middleware — extracts user context from tokens."""

import logging
import sys

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from app.auth.api_tokens import ApiTokenService
from app.auth.jwt import JWTError, JWTService
from app.constants import Routes
from app.dependencies import db_manager
from app.settings import get_settings
from shared.logging.context import log_context

logger = logging.getLogger(__name__)

# Paths that should never trigger JWT processing
_SKIP_PREFIXES = (Routes.HEALTH, "/docs", "/openapi.json", "/redoc")
_SKIP_EXACT = frozenset({"/", f"{Routes.AUTH.prefix}/login", f"{Routes.AUTH.prefix}/callback"})

# API token prefix for quick identification
_API_TOKEN_PREFIX = "smcp_"


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """Extract JWT or API token from Authorization header or cookie, set request.state.

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
        """Process each request, extracting JWT or API token if present."""
        # Initialize state to unauthenticated
        request.state.user_id = None
        request.state.db_session = None

        path = request.url.path
        if self._should_skip(path):
            return await call_next(request)

        # Check for API token (smcp_...) first — requires DB lookup
        api_token = self._extract_api_token(request)
        if api_token is not None:
            return await self._handle_api_token(api_token, request, call_next)

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

        return await self._with_session(user_id, request, call_next)

    async def _handle_api_token(self, raw_token: str, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Validate an API token via DB lookup and set user context."""
        try:
            session_cm = db_manager.session()
            session = await session_cm.__aenter__()
        except Exception:
            logger.debug("Could not open DB session for API token validation")
            return await call_next(request)

        try:
            user_id = await ApiTokenService.validate(raw_token, session)
            if user_id is None:
                # Invalid or revoked token — proceed unauthenticated
                return await call_next(request)

            request.state.user_id = user_id
            request.state.db_session = session

            async with log_context(user_id=user_id):
                response = await call_next(request)
                return response
        finally:
            request.state.db_session = None
            await session_cm.__aexit__(*sys.exc_info())

    async def _with_session(self, user_id: int, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Open a DB session for the authenticated user and proceed."""
        async with log_context(user_id=user_id):
            try:
                session_cm = db_manager.session()
                session = await session_cm.__aenter__()
            except Exception:
                logger.debug("Could not open DB session for user %d; proceeding without", user_id)
                return await call_next(request)

            try:
                request.state.db_session = session
                response = await call_next(request)
                return response
            finally:
                request.state.db_session = None
                await session_cm.__aexit__(*sys.exc_info())

    @staticmethod
    def _should_skip(path: str) -> bool:
        """Check whether a path should bypass JWT processing."""
        if path in _SKIP_EXACT:
            return True
        return any(path.startswith(prefix) for prefix in _SKIP_PREFIXES)

    @staticmethod
    def _extract_api_token(request: Request) -> str | None:
        """Extract an API token (smcp_...) from the Bearer header."""
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            candidate = auth_header[7:]
            if candidate.startswith(_API_TOKEN_PREFIX):
                return candidate
        return None

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
