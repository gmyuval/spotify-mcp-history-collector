"""Token lifecycle management — retrieval and refresh of Spotify access tokens."""

import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.crypto import TokenEncryptor
from app.auth.exceptions import TokenNotFoundError, TokenRefreshError
from app.auth.schemas import SpotifyTokenResponse
from app.constants import SPOTIFY_TOKEN_URL
from app.settings import AppSettings
from shared.db.models.user import SpotifyToken, User

logger = logging.getLogger(__name__)


class TokenManager:
    """Manages the Spotify access-token lifecycle, including transparent refresh.

    When refreshing tokens, automatically resolves per-user Spotify app
    credentials (if configured) and falls back to system defaults.
    """

    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._encryptor = TokenEncryptor(settings.TOKEN_ENCRYPTION_KEY)

    async def get_valid_token(self, user_id: int, session: AsyncSession) -> str:
        """Return a valid access token for the user, refreshing if needed.

        Raises:
            TokenNotFoundError: If no token record exists for the user.
            TokenRefreshError: If the Spotify token endpoint returns an error.
        """
        token_record = await self._load_token(user_id, session)

        buffer = timedelta(seconds=self._settings.TOKEN_EXPIRY_BUFFER_SECONDS)
        if (
            token_record.access_token
            and token_record.token_expires_at
            and token_record.token_expires_at > datetime.now(UTC) + buffer
        ):
            return token_record.access_token

        return await self.refresh_access_token(user_id, session)

    async def refresh_access_token(self, user_id: int, session: AsyncSession) -> str:
        """Force-refresh the Spotify access token for a user.

        Uses per-user Spotify app credentials when available, falling back
        to the system defaults from :class:`AppSettings`.

        Raises:
            TokenNotFoundError: If no token record exists for the user.
            TokenRefreshError: If the Spotify token endpoint returns an error.
        """
        token_record = await self._load_token(user_id, session)
        refresh_token = self._encryptor.decrypt(token_record.encrypted_refresh_token)
        client_id, client_secret = await self._resolve_credentials(user_id, session)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                SPOTIFY_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise TokenRefreshError(
                    user_id=user_id,
                    detail=f"Spotify returned HTTP {exc.response.status_code} during token refresh",
                ) from exc

        token_data = SpotifyTokenResponse.model_validate(response.json())

        token_record.access_token = token_data.access_token
        token_record.token_expires_at = datetime.now(UTC) + timedelta(seconds=token_data.expires_in)

        if token_data.refresh_token:
            token_record.encrypted_refresh_token = self._encryptor.encrypt(token_data.refresh_token)

        return token_data.access_token

    async def _resolve_credentials(self, user_id: int, session: AsyncSession) -> tuple[str, str]:
        """Resolve Spotify client credentials for a user.

        Returns per-user credentials if configured, otherwise system defaults.
        """
        result = await session.execute(
            select(User.custom_spotify_client_id, User.encrypted_custom_client_secret).where(User.id == user_id)
        )
        row = result.one_or_none()
        if row and row.custom_spotify_client_id and row.encrypted_custom_client_secret:
            client_secret = self._encryptor.decrypt(row.encrypted_custom_client_secret)
            logger.debug("Using custom Spotify credentials for user %d", user_id)
            return row.custom_spotify_client_id, client_secret
        return self._settings.SPOTIFY_CLIENT_ID, self._settings.SPOTIFY_CLIENT_SECRET

    async def _load_token(self, user_id: int, session: AsyncSession) -> SpotifyToken:
        """Load the SpotifyToken record for a user or raise."""
        result = await session.execute(select(SpotifyToken).where(SpotifyToken.user_id == user_id))
        token_record = result.scalar_one_or_none()
        if token_record is None:
            raise TokenNotFoundError(user_id)
        return token_record
