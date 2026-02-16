"""Collector token management — retrieval and refresh of Spotify access tokens."""

import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from collector.settings import CollectorSettings
from shared.crypto import TokenEncryptor
from shared.db.models.user import SpotifyToken, User
from shared.spotify.constants import SPOTIFY_TOKEN_URL

logger = logging.getLogger(__name__)


class CollectorTokenManager:
    """Manages the Spotify access-token lifecycle for the collector service.

    When refreshing tokens, automatically resolves per-user Spotify app
    credentials (if configured) and falls back to system defaults.
    """

    def __init__(self, settings: CollectorSettings) -> None:
        self._settings = settings
        self._encryptor = TokenEncryptor(settings.TOKEN_ENCRYPTION_KEY)

    async def get_valid_token(self, user_id: int, session: AsyncSession) -> str:
        """Return a valid access token for the user, refreshing if needed.

        Raises:
            ValueError: If no token record exists for the user.
            RuntimeError: If the Spotify token endpoint returns an error.
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
        to the system defaults from :class:`CollectorSettings`.

        Raises:
            ValueError: If no token record exists for the user.
            RuntimeError: If the Spotify token endpoint returns an error.
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
            if response.status_code != 200:
                raise RuntimeError(f"Token refresh failed for user {user_id}: HTTP {response.status_code}")

        data = response.json()
        access_token: str = data["access_token"]
        token_record.access_token = access_token
        token_record.token_expires_at = datetime.now(UTC) + timedelta(seconds=data["expires_in"])

        if data.get("refresh_token"):
            token_record.encrypted_refresh_token = self._encryptor.encrypt(data["refresh_token"])

        return access_token

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
            raise ValueError(f"No token found for user_id={user_id}")
        return token_record
