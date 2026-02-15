"""MCP tool handlers for Spotify playlist read operations — class-based."""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import TokenManager
from app.mcp.registry import registry
from app.mcp.schemas import MCPToolParam
from app.settings import get_settings
from shared.spotify.client import SpotifyClient

logger = logging.getLogger(__name__)

_USER_PARAM = MCPToolParam(name="user_id", type="int", description="User ID (must have active OAuth)")


class PlaylistToolHandlers:
    """Registers and handles playlist-related MCP tools."""

    def __init__(self) -> None:
        self._register()

    def _register(self) -> None:
        registry.register(
            name="spotify.list_playlists",
            description="List the user's Spotify playlists (name, id, track count, public/private)",
            category="spotify",
            parameters=[
                _USER_PARAM,
                MCPToolParam(name="limit", type="int", description="Max playlists (1-50)", required=False, default=50),
            ],
        )(self.list_playlists)

        registry.register(
            name="spotify.get_playlist",
            description="Get playlist details including track listing by playlist ID",
            category="spotify",
            parameters=[
                _USER_PARAM,
                MCPToolParam(name="playlist_id", type="str", description="Spotify playlist ID"),
            ],
        )(self.get_playlist)

    async def _get_client(self, user_id: int, session: AsyncSession) -> SpotifyClient:
        """Create a SpotifyClient with token management for the given user."""
        settings = get_settings()
        token_mgr = TokenManager(settings)
        access_token = await token_mgr.get_valid_token(user_id, session)

        async def _on_token_expired() -> str:
            return await token_mgr.refresh_access_token(user_id, session)

        return SpotifyClient(access_token, on_token_expired=_on_token_expired)

    async def list_playlists(self, args: dict[str, Any], session: AsyncSession) -> Any:
        client = await self._get_client(args["user_id"], session)
        limit = max(1, min(args.get("limit", 50), 50))
        resp = await client.get_user_playlists(limit=limit)
        return [
            {
                "id": p.id,
                "name": p.name,
                "public": p.public,
                "tracks_total": p.tracks.get("total") if p.tracks else None,
                "owner": p.owner.display_name if p.owner else None,
            }
            for p in resp.items
        ]

    async def get_playlist(self, args: dict[str, Any], session: AsyncSession) -> Any:
        client = await self._get_client(args["user_id"], session)
        pl = await client.get_playlist(args["playlist_id"])
        tracks = []
        if pl.tracks:
            for item in pl.tracks.items:
                if item.track:
                    tracks.append(
                        {
                            "id": item.track.id,
                            "name": item.track.name,
                            "artists": [{"id": a.id, "name": a.name} for a in item.track.artists],
                            "added_at": item.added_at,
                        }
                    )
        return {
            "id": pl.id,
            "name": pl.name,
            "description": pl.description,
            "public": pl.public,
            "owner": pl.owner.display_name if pl.owner else None,
            "tracks_total": pl.tracks.total if pl.tracks else 0,
            "tracks": tracks,
            "snapshot_id": pl.snapshot_id,
            "external_urls": pl.external_urls,
        }


_instance = PlaylistToolHandlers()
