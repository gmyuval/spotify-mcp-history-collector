"""Admin authentication dependency — class-based provider.

Provides two authentication mechanisms:

1. **Admin token/basic auth** — existing mechanism for admin endpoints.
   Uses ``require_admin`` dependency.
2. **RBAC permission check** — for user-facing endpoints (Phase 4+).
   Uses ``require_permission("codename")`` factory to create dependencies
   that verify the authenticated user holds a specific permission.
"""

import base64
import logging
import secrets
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import PermissionChecker
from app.settings import AppSettings, get_settings

logger = logging.getLogger(__name__)

_permission_checker = PermissionChecker()


class AdminAuthProvider:
    """Provides admin authentication as a FastAPI dependency.

    Modes:
    - "token": Expects ``Authorization: Bearer <ADMIN_TOKEN>``
    - "basic": Expects ``Authorization: Basic <base64(user:pass)>``
    - "" (empty/unset): Auth disabled — all requests pass through (dev mode)
    """

    async def require_admin(
        self,
        request: Request,
        settings: Annotated[AppSettings, Depends(get_settings)],
    ) -> None:
        """Validate admin authentication based on ADMIN_AUTH_MODE.

        Raises HTTPException(401) on authentication failure.
        """
        mode = settings.ADMIN_AUTH_MODE.strip().lower()

        if not mode:
            return

        auth_header = request.headers.get("Authorization", "")

        if mode == "token":
            self._validate_token(auth_header, settings.ADMIN_TOKEN)
        elif mode == "basic":
            self._validate_basic(auth_header, settings.ADMIN_USERNAME, settings.ADMIN_PASSWORD)
        else:
            raise HTTPException(status_code=500, detail=f"Unknown ADMIN_AUTH_MODE: {mode}")

    @staticmethod
    def _validate_token(auth_header: str, expected_token: str) -> None:
        if not expected_token:
            raise HTTPException(status_code=500, detail="ADMIN_TOKEN not configured")

        if not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

        provided = auth_header[7:]  # Strip "Bearer "
        if not secrets.compare_digest(provided, expected_token):
            raise HTTPException(status_code=401, detail="Invalid token")

    @staticmethod
    def _validate_basic(auth_header: str, expected_username: str, expected_password: str) -> None:
        if not expected_username or not expected_password:
            raise HTTPException(status_code=500, detail="ADMIN_USERNAME/ADMIN_PASSWORD not configured")

        if not auth_header.startswith("Basic "):
            raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            username, password = decoded.split(":", 1)
        except Exception as exc:
            raise HTTPException(status_code=401, detail="Invalid Basic auth encoding") from exc

        if not (
            secrets.compare_digest(username, expected_username) and secrets.compare_digest(password, expected_password)
        ):
            raise HTTPException(status_code=401, detail="Invalid credentials")


class PermissionDependencyFactory:
    """Creates FastAPI dependencies that enforce RBAC permission checks.

    The returned dependency expects ``request.state.user_id`` and
    ``request.state.db_session`` to be set by upstream middleware (JWT
    auth middleware, added in Phase 4).  Until that middleware exists,
    these dependencies will raise 401.

    Usage::

        @router.get("/protected", dependencies=[Depends(require_permission("own_data.view"))])
        async def protected_endpoint(): ...
    """

    def __init__(self, checker: PermissionChecker) -> None:
        self._checker = checker

    def __call__(self, codename: str) -> Callable[..., Coroutine[Any, Any, int]]:
        """Return an async dependency that checks for *codename* and returns the user_id."""

        async def _dependency(request: Request) -> int:
            user_id: int | None = getattr(request.state, "user_id", None)
            if user_id is None:
                raise HTTPException(status_code=401, detail="Authentication required")

            db_session: AsyncSession | None = getattr(request.state, "db_session", None)
            if db_session is None:
                raise HTTPException(status_code=500, detail="Database session not available")

            has_perm = await self._checker.has_permission(user_id, codename, db_session)
            if not has_perm:
                logger.warning("Permission denied: user %d lacks '%s'", user_id, codename)
                raise HTTPException(status_code=403, detail=f"Permission required: {codename}")

            return user_id

        return _dependency


_provider = AdminAuthProvider()
require_admin = _provider.require_admin

_perm_factory = PermissionDependencyFactory(_permission_checker)
require_permission = _perm_factory
