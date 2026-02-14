"""Spotify OAuth HTTP endpoints — class-based router delegating to OAuthService."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.exceptions import InvalidStateError, SpotifyAPIError
from app.auth.schemas import AuthCallbackResponse
from app.auth.service import OAuthService
from app.dependencies import db_manager
from app.settings import AppSettings, get_settings


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
        self.router.add_api_route("/callback", self.callback, methods=["GET"])

    async def login(
        self,
        service: Annotated[OAuthService, Depends(_get_oauth_service)],
    ) -> RedirectResponse:
        """Redirect user to Spotify authorization page."""
        url = service.get_authorization_url()
        return RedirectResponse(url=url)

    async def callback(
        self,
        code: Annotated[str, Query()],
        state: Annotated[str, Query()],
        session: Annotated[AsyncSession, Depends(db_manager.dependency)],
        service: Annotated[OAuthService, Depends(_get_oauth_service)],
    ) -> AuthCallbackResponse:
        """Handle Spotify OAuth callback: exchange code, upsert user and tokens."""
        try:
            return await service.handle_callback(code, state, session)
        except InvalidStateError as exc:
            raise HTTPException(status_code=400, detail="Invalid or expired state parameter") from exc
        except SpotifyAPIError as exc:
            raise HTTPException(status_code=502, detail=exc.detail) from exc


_instance = AuthRouter()
router = _instance.router
