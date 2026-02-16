"""Spotify OAuth HTTP endpoints — class-based router delegating to OAuthService."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.crypto import TokenEncryptor
from app.auth.exceptions import InvalidStateError, SpotifyAPIError
from app.auth.schemas import AuthCallbackResponse
from app.auth.service import OAuthService
from app.dependencies import db_manager
from app.settings import AppSettings, get_settings
from shared.db.models.user import User

logger = logging.getLogger(__name__)


def _get_oauth_service(
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> OAuthService:
    """FastAPI dependency that provides an OAuthService instance."""
    return OAuthService(settings)


class AuthRouter:
    """Class-based router for Spotify OAuth endpoints."""

    def __init__(self) -> None:
        self.router = APIRouter()
        self.router.add_api_route("/login", self.login, methods=["GET"])
        self.router.add_api_route(
            "/callback",
            self.callback,
            methods=["GET"],
            response_model=None,
        )

    async def login(
        self,
        service: Annotated[OAuthService, Depends(_get_oauth_service)],
        settings: Annotated[AppSettings, Depends(get_settings)],
        session: Annotated[AsyncSession, Depends(db_manager.dependency)],
        user_id: int | None = Query(default=None, description="User ID for re-auth with custom credentials"),
    ) -> RedirectResponse:
        """Redirect user to Spotify authorization page.

        When ``user_id`` is provided, the user's custom Spotify app credentials
        (if configured) are used for the authorization URL, and the user_id is
        embedded in the OAuth state for the callback to use.
        """
        client_id: str | None = None
        if user_id is not None:
            client_id = await self._resolve_custom_client_id(user_id, settings, session)

        url = service.get_authorization_url(client_id=client_id, user_id=user_id)
        return RedirectResponse(url=url)

    async def callback(
        self,
        request: Request,
        code: Annotated[str, Query()],
        state: Annotated[str, Query()],
        session: Annotated[AsyncSession, Depends(db_manager.dependency)],
        service: Annotated[OAuthService, Depends(_get_oauth_service)],
    ) -> AuthCallbackResponse | RedirectResponse:
        """Handle Spotify OAuth callback: exchange code, upsert user and tokens."""
        try:
            result = await service.handle_callback(code, state, session)
        except InvalidStateError as exc:
            raise HTTPException(status_code=400, detail="Invalid or expired state parameter") from exc
        except SpotifyAPIError as exc:
            raise HTTPException(status_code=502, detail=exc.detail) from exc

        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            return RedirectResponse(url="/users", status_code=303)
        return result

    @staticmethod
    async def _resolve_custom_client_id(user_id: int, settings: AppSettings, session: AsyncSession) -> str | None:
        """Load a user's custom client_id if configured, verifying the secret is also set."""
        result = await session.execute(
            select(User.custom_spotify_client_id, User.encrypted_custom_client_secret).where(User.id == user_id)
        )
        row = result.one_or_none()
        if row and row.custom_spotify_client_id and row.encrypted_custom_client_secret:
            # Verify the encrypted secret is decryptable (fail-fast on bad key)
            encryptor = TokenEncryptor(settings.TOKEN_ENCRYPTION_KEY)
            try:
                encryptor.decrypt(row.encrypted_custom_client_secret)
            except Exception:
                logger.warning("Custom client secret for user %d is not decryptable", user_id)
                return None
            client_id: str = row.custom_spotify_client_id
            return client_id
        return None


_instance = AuthRouter()
router = _instance.router
