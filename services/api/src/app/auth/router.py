"""Spotify OAuth HTTP endpoints — class-based router delegating to OAuthService."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.crypto import TokenEncryptor
from app.auth.exceptions import InvalidStateError, SpotifyAPIError
from app.auth.jwt import JWTExpiredError, JWTInvalidError, JWTService
from app.auth.schemas import JWTTokenResponse, RefreshTokenRequest
from app.auth.service import OAuthService
from app.dependencies import db_manager
from app.settings import AppSettings, get_settings
from shared.db.models.user import User

logger = logging.getLogger(__name__)


class AuthRouter:
    """Class-based router for Spotify OAuth and JWT endpoints."""

    @staticmethod
    def _get_oauth_service(
        settings: Annotated[AppSettings, Depends(get_settings)],
    ) -> OAuthService:
        """FastAPI dependency that provides an OAuthService instance."""
        return OAuthService(settings)

    @staticmethod
    def _get_jwt_service(
        settings: Annotated[AppSettings, Depends(get_settings)],
    ) -> JWTService:
        """FastAPI dependency that provides a JWTService instance."""
        return JWTService(settings)

    def __init__(self) -> None:
        self.router = APIRouter()
        self.router.add_api_route("/login", self.login, methods=["GET"])
        self.router.add_api_route(
            "/callback",
            self.callback,
            methods=["GET"],
            response_model=None,
        )
        self.router.add_api_route("/refresh", self.refresh, methods=["POST"])
        self.router.add_api_route(
            "/logout",
            self.logout,
            methods=["POST"],
            response_model=None,
        )

    async def login(
        self,
        service: Annotated[OAuthService, Depends(AuthRouter._get_oauth_service)],
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
        service: Annotated[OAuthService, Depends(AuthRouter._get_oauth_service)],
        jwt_service: Annotated[JWTService, Depends(AuthRouter._get_jwt_service)],
    ) -> Response:
        """Handle Spotify OAuth callback: exchange code, upsert user, issue JWT."""
        try:
            result, user_id = await service.handle_callback(code, state, session)
        except InvalidStateError as exc:
            raise HTTPException(status_code=400, detail="Invalid or expired state parameter") from exc
        except SpotifyAPIError as exc:
            raise HTTPException(status_code=502, detail=exc.detail) from exc

        access_token, refresh_token = jwt_service.create_token_pair(user_id)

        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            redirect = RedirectResponse(url="/users", status_code=303)
            self._set_auth_cookies(redirect, access_token, refresh_token, jwt_service)
            return redirect

        result.access_token = access_token
        result.refresh_token = refresh_token
        result.expires_in = jwt_service.access_expire_seconds
        json_response = JSONResponse(content=result.model_dump())
        self._set_auth_cookies(json_response, access_token, refresh_token, jwt_service)
        return json_response

    async def refresh(
        self,
        request: Request,
        jwt_service: Annotated[JWTService, Depends(AuthRouter._get_jwt_service)],
        session: Annotated[AsyncSession, Depends(db_manager.dependency)],
        body: RefreshTokenRequest | None = None,
    ) -> JWTTokenResponse:
        """Refresh an expired access token using a valid refresh token.

        Accepts the refresh token from:
        - Request body JSON: {"refresh_token": "..."}
        - HTTP-only cookie: refresh_token
        """
        token = self._extract_refresh_token(request, body)
        if token is None:
            raise HTTPException(status_code=401, detail="No refresh token provided")

        try:
            user_id = jwt_service.decode_refresh_token(token)
        except JWTExpiredError as exc:
            raise HTTPException(status_code=401, detail="Refresh token has expired") from exc
        except JWTInvalidError as exc:
            raise HTTPException(status_code=401, detail="Invalid refresh token") from exc

        # Verify user still exists
        result = await session.execute(select(User.id).where(User.id == user_id))
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=401, detail="User not found")

        access_token = jwt_service.create_access_token(user_id)
        return JWTTokenResponse(
            access_token=access_token,
            expires_in=jwt_service.access_expire_seconds,
        )

    async def logout(
        self,
        jwt_service: Annotated[JWTService, Depends(AuthRouter._get_jwt_service)],
    ) -> Response:
        """Clear authentication cookies."""
        response = JSONResponse(content={"message": "Logged out"})
        response.delete_cookie("access_token", path="/", domain=jwt_service.cookie_domain)
        response.delete_cookie("refresh_token", path="/auth/refresh", domain=jwt_service.cookie_domain)
        return response

    @staticmethod
    def _set_auth_cookies(
        response: Response,
        access_token: str,
        refresh_token: str,
        jwt_service: JWTService,
    ) -> None:
        """Set HTTP-only secure cookies for both tokens."""
        response.set_cookie(
            key="access_token",
            value=access_token,
            max_age=jwt_service.access_expire_seconds,
            httponly=True,
            secure=jwt_service.cookie_secure,
            samesite="lax",
            path="/",
            domain=jwt_service.cookie_domain,
        )
        response.set_cookie(
            key="refresh_token",
            value=refresh_token,
            max_age=jwt_service.refresh_expire_seconds,
            httponly=True,
            secure=jwt_service.cookie_secure,
            samesite="lax",
            path="/auth/refresh",
            domain=jwt_service.cookie_domain,
        )

    @staticmethod
    def _extract_refresh_token(request: Request, body: RefreshTokenRequest | None) -> str | None:
        """Extract refresh token from request body or cookie."""
        if body is not None:
            return body.refresh_token
        return request.cookies.get("refresh_token")

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
