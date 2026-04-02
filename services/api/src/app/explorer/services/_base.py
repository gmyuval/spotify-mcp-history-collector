"""Base class for explorer sub-services with shared infrastructure."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.settings_service import _settings_service
from app.auth.tokens import TokenManager
from app.settings import get_settings
from shared.musicbrainz.client import MusicBrainzClient
from shared.spotify.client import SpotifyClient


class BaseExplorerService:
    """Shared infrastructure for all explorer sub-services.

    Provides Spotify client construction, MusicBrainz client extraction,
    and access to the dynamic admin settings store.
    """

    settings = _settings_service

    async def _get_spotify_client(self, user_id: int, session: AsyncSession) -> SpotifyClient:
        """Create a SpotifyClient with token management for the given user."""
        app_settings = get_settings()
        token_mgr = TokenManager(app_settings)
        access_token = await token_mgr.get_valid_token(user_id, session)

        async def _on_token_expired() -> str:
            return await token_mgr.refresh_access_token(user_id, session)

        return SpotifyClient(access_token, on_token_expired=_on_token_expired)

    @staticmethod
    def _get_mb_client(request: object | None) -> MusicBrainzClient | None:
        """Extract MusicBrainzClient from the request's app state, if available."""
        if request is None:
            return None
        app = getattr(request, "app", None)
        if app is None:
            return None
        state = getattr(app, "state", None)
        if state is None:
            return None
        client = getattr(state, "mb_client", None)
        if isinstance(client, MusicBrainzClient):
            return client
        return None
