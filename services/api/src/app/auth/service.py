"""OAuth service — business logic for the Spotify authorization flow."""

import logging
from datetime import UTC, datetime, timedelta

import httpx
from cryptography.fernet import InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.crypto import TokenEncryptor
from app.auth.exceptions import InvalidStateError, SpotifyAPIError
from app.auth.permissions import PermissionChecker
from app.auth.schemas import (
    AuthCallbackResponse,
    SpotifyProfile,
    SpotifyProfileSummary,
    SpotifyTokenResponse,
)
from app.auth.state import OAuthStateManager
from app.constants import SPOTIFY_AUTHORIZE_URL, SPOTIFY_ME_URL, SPOTIFY_SCOPES, SPOTIFY_TOKEN_URL
from app.settings import AppSettings
from shared.db.enums import SyncStatus
from shared.db.models.operations import SyncCheckpoint
from shared.db.models.user import SpotifyToken, User

logger = logging.getLogger(__name__)


class OAuthService:
    """Handles the Spotify OAuth authorization flow.

    Encapsulates state generation/verification, token exchange, user upsert,
    and sync-checkpoint creation.

    Supports per-user Spotify app credentials for re-authorization flows:
    when a ``user_id`` is supplied to :meth:`get_authorization_url`, the
    service loads the user's custom credentials (if configured) and uses
    them for the authorization URL and subsequent token exchange.
    """

    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._state_manager = OAuthStateManager(
            key=settings.TOKEN_ENCRYPTION_KEY,
            ttl_seconds=settings.OAUTH_STATE_TTL_SECONDS,
        )
        self._encryptor = TokenEncryptor(settings.TOKEN_ENCRYPTION_KEY)
        self._permission_checker = PermissionChecker()

    def get_authorization_url(
        self,
        client_id: str | None = None,
        user_id: int | None = None,
        next_url: str | None = None,
    ) -> str:
        """Build the full Spotify authorization redirect URL.

        Parameters:
            client_id: Override client_id (e.g. from per-user credentials).
                Falls back to the system default.
            user_id: If provided, embedded in the OAuth state so the callback
                can resolve per-user credentials for token exchange.
            next_url: If provided, the callback will redirect here after
                successful authentication.
        """
        from urllib.parse import urlencode

        uid_part = str(user_id) if user_id is not None else ""
        next_part = next_url or ""
        payload = f"{uid_part}|{next_part}" if next_part else uid_part
        state = self._state_manager.generate(payload=payload)
        params = {
            "client_id": client_id or self._settings.SPOTIFY_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": self._settings.SPOTIFY_REDIRECT_URI,
            "scope": SPOTIFY_SCOPES,
            "state": state,
        }
        return f"{SPOTIFY_AUTHORIZE_URL}?{urlencode(params)}"

    async def handle_callback(
        self, code: str, state: str, session: AsyncSession
    ) -> tuple[AuthCallbackResponse, int, str | None]:
        """Process the OAuth callback: validate state, exchange code, upsert user.

        Returns a tuple of (response, user_id, next_url) so the router can
        issue a JWT and redirect appropriately.

        If the state contains an embedded ``user_id`` (from a re-auth flow),
        per-user credentials are used for the token exchange.

        Raises:
            InvalidStateError: If the state parameter is invalid or expired.
            SpotifyAPIError: If any Spotify API call fails.
        """
        if not self._state_manager.verify(state):
            raise InvalidStateError("Invalid or expired state parameter")

        # Parse state payload: user_id and/or next_url
        reauth_user_id, next_url = self._parse_state_payload(state)
        client_id, client_secret = await self._resolve_callback_credentials(reauth_user_id, session)

        token_response, profile = await self._exchange_and_fetch_profile(code, client_id, client_secret)
        user, is_new = await self._upsert_user(profile, session)
        await self._upsert_token(user.id, token_response, session)

        if is_new:
            await self._create_sync_checkpoint(user.id, session)
            await self._assign_default_role(user.id, session)

        response = AuthCallbackResponse(
            message="Authorization successful",
            user=SpotifyProfileSummary(
                spotify_user_id=profile.id,
                display_name=profile.display_name,
            ),
            is_new_user=is_new,
        )
        return response, user.id, next_url

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_state_payload(self, state: str) -> tuple[int | None, str | None]:
        """Parse user_id and next_url from the OAuth state payload.

        Payload format: ``{user_id}|{next_url}`` where either part may be empty.
        Legacy format (just ``{user_id}``) is also supported.
        """
        payload = self._state_manager.extract_payload(state)
        if payload is None:
            return None, None
        if "|" in payload:
            uid_str, next_url = payload.split("|", 1)
            user_id = int(uid_str) if uid_str else None
            return user_id, next_url or None
        try:
            return int(payload), None
        except ValueError:
            return None, None

    async def _resolve_callback_credentials(self, user_id: int | None, session: AsyncSession) -> tuple[str, str]:
        """Resolve Spotify credentials for the token exchange.

        If *user_id* is provided, check for custom per-user credentials.
        Falls back to system defaults.
        """
        if user_id is not None:
            result = await session.execute(
                select(User.custom_spotify_client_id, User.encrypted_custom_client_secret).where(User.id == user_id)
            )
            row = result.one_or_none()
            if row and row.custom_spotify_client_id and row.encrypted_custom_client_secret:
                try:
                    client_secret = self._encryptor.decrypt(row.encrypted_custom_client_secret)
                except InvalidToken:
                    logger.warning(
                        "Failed to decrypt custom Spotify credentials for user %d; encryption key may have rotated",
                        user_id,
                    )
                    raise SpotifyAPIError(
                        action="resolve credentials",
                        status_code=500,
                        detail="Stored custom Spotify credentials are invalid. Please reconfigure.",
                    ) from None
                logger.debug("Using custom Spotify credentials for re-auth of user %d", user_id)
                return row.custom_spotify_client_id, client_secret
        return self._settings.SPOTIFY_CLIENT_ID, self._settings.SPOTIFY_CLIENT_SECRET

    async def _exchange_and_fetch_profile(
        self, code: str, client_id: str, client_secret: str
    ) -> tuple[SpotifyTokenResponse, SpotifyProfile]:
        """Exchange the authorization code for tokens and fetch the user profile."""
        async with httpx.AsyncClient() as client:
            token_resp = await client.post(
                SPOTIFY_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self._settings.SPOTIFY_REDIRECT_URI,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
            )
            self._check_spotify_response(token_resp, "exchange authorization code")
            token_data = SpotifyTokenResponse.model_validate(token_resp.json())

            profile_resp = await client.get(
                SPOTIFY_ME_URL,
                headers={"Authorization": f"Bearer {token_data.access_token}"},
            )
            self._check_spotify_response(profile_resp, "fetch user profile")
            profile = SpotifyProfile.model_validate(profile_resp.json())

        return token_data, profile

    @staticmethod
    def _check_spotify_response(response: httpx.Response, action: str) -> None:
        """Raise SpotifyAPIError with a descriptive message if the response is not OK."""
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 429:
                detail = f"Rate limited by Spotify while trying to {action}. Please try again later."
            elif status >= 500:
                detail = f"Spotify server error while trying to {action}. This is likely a transient issue."
            elif status == 401:
                detail = f"Spotify authentication failed while trying to {action}. Check client credentials."
            elif status == 400:
                detail = f"Spotify rejected the request to {action}. The authorization code may have expired."
            else:
                detail = f"Spotify returned HTTP {status} while trying to {action}."
            raise SpotifyAPIError(action=action, status_code=status, detail=detail) from exc

    @staticmethod
    async def _upsert_user(profile: SpotifyProfile, session: AsyncSession) -> tuple[User, bool]:
        """Insert or update a User record from a Spotify profile. Returns (user, is_new)."""
        result = await session.execute(select(User).where(User.spotify_user_id == profile.id))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                spotify_user_id=profile.id,
                display_name=profile.display_name,
                email=profile.email,
                country=profile.country,
                product=profile.product,
            )
            session.add(user)
            await session.flush()
            return user, True

        user.display_name = profile.display_name
        user.email = profile.email
        user.country = profile.country
        user.product = profile.product
        return user, False

    async def _upsert_token(
        self,
        user_id: int,
        token_response: SpotifyTokenResponse,
        session: AsyncSession,
    ) -> None:
        """Insert or update a SpotifyToken record from a token response."""
        if token_response.refresh_token is None:
            raise SpotifyAPIError(
                action="token exchange",
                status_code=200,
                detail="Spotify did not return a refresh token.",
            )

        encrypted_refresh = self._encryptor.encrypt(token_response.refresh_token)
        expires_at = datetime.now(UTC) + timedelta(seconds=token_response.expires_in)

        result = await session.execute(select(SpotifyToken).where(SpotifyToken.user_id == user_id))
        token_record = result.scalar_one_or_none()
        if token_record is None:
            token_record = SpotifyToken(
                user_id=user_id,
                encrypted_refresh_token=encrypted_refresh,
                access_token=token_response.access_token,
                token_expires_at=expires_at,
                scope=token_response.scope,
            )
            session.add(token_record)
        else:
            token_record.encrypted_refresh_token = encrypted_refresh
            token_record.access_token = token_response.access_token
            token_record.token_expires_at = expires_at
            token_record.scope = token_response.scope

    @staticmethod
    async def _create_sync_checkpoint(user_id: int, session: AsyncSession) -> None:
        """Create an initial SyncCheckpoint for a newly registered user."""
        checkpoint = SyncCheckpoint(user_id=user_id, status=SyncStatus.IDLE)
        session.add(checkpoint)

    async def _assign_default_role(self, user_id: int, session: AsyncSession) -> None:
        """Assign the 'user' role to a newly created user."""
        try:
            await self._permission_checker.assign_role(user_id, "user", session)
            logger.info("Assigned default 'user' role to new user %d", user_id)
        except ValueError:
            logger.warning("Default 'user' role not found — skipping role assignment for user %d", user_id)
