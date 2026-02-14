"""Admin authentication dependency — class-based provider."""

import base64
import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from app.settings import AppSettings, get_settings


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


_provider = AdminAuthProvider()
require_admin = _provider.require_admin
