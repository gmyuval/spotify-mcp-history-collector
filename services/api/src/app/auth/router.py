"""Spotify OAuth HTTP endpoints — thin routing layer delegating to OAuthService."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.exceptions import InvalidStateError, SpotifyAPIError
from app.auth.schemas import AuthCallbackResponse
from app.auth.service import OAuthService
from app.dependencies import db_manager
from app.settings import AppSettings, get_settings

router = APIRouter()


def get_oauth_service(
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> OAuthService:
    """FastAPI dependency that provides an OAuthService instance."""
    return OAuthService(settings)


@router.get("/login")
async def login(
    service: Annotated[OAuthService, Depends(get_oauth_service)],
) -> RedirectResponse:
    """Redirect user to Spotify authorization page."""
    url = service.get_authorization_url()
    return RedirectResponse(url=url)


@router.get("/callback")
async def callback(
    code: Annotated[str, Query()],
    state: Annotated[str, Query()],
    session: Annotated[AsyncSession, Depends(db_manager.dependency)],
    service: Annotated[OAuthService, Depends(get_oauth_service)],
) -> AuthCallbackResponse:
    """Handle Spotify OAuth callback: exchange code, upsert user and tokens."""
    try:
        return await service.handle_callback(code, state, session)
    except InvalidStateError as exc:
        raise HTTPException(status_code=400, detail="Invalid or expired state parameter") from exc
    except SpotifyAPIError as exc:
        raise HTTPException(status_code=502, detail=exc.detail) from exc
