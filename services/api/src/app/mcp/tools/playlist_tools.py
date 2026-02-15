"""MCP tool handlers for Spotify playlist operations — class-based."""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import TokenManager
from app.mcp.registry import registry
from app.mcp.schemas import MCPToolParam
from app.settings import get_settings
from shared.db.models.user import SpotifyToken
from shared.spotify.client import SpotifyClient

logger = logging.getLogger(__name__)

_USER_PARAM = MCPToolParam(name="user_id", type="int", description="User ID (must have active OAuth)")

_PLAYLIST_WRITE_SCOPES = {"playlist-modify-public", "playlist-modify-private"}


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

        registry.register(
            name="spotify.create_playlist",
            description="Create a new Spotify playlist for the user",
            category="spotify",
            parameters=[
                _USER_PARAM,
                MCPToolParam(name="name", type="str", description="Playlist name"),
                MCPToolParam(
                    name="description", type="str", description="Playlist description", required=False, default=""
                ),
                MCPToolParam(
                    name="public",
                    type="bool",
                    description="Whether the playlist is public",
                    required=False,
                    default=True,
                ),
            ],
        )(self.create_playlist)

        registry.register(
            name="spotify.add_tracks",
            description="Add tracks to a playlist (max 100 per call). Pass Spotify track IDs.",
            category="spotify",
            parameters=[
                _USER_PARAM,
                MCPToolParam(name="playlist_id", type="str", description="Spotify playlist ID"),
                MCPToolParam(name="track_ids", type="list[str]", description="List of Spotify track IDs to add"),
            ],
        )(self.add_tracks)

        registry.register(
            name="spotify.remove_tracks",
            description="Remove tracks from a playlist (max 100 per call). Pass Spotify track IDs.",
            category="spotify",
            parameters=[
                _USER_PARAM,
                MCPToolParam(name="playlist_id", type="str", description="Spotify playlist ID"),
                MCPToolParam(name="track_ids", type="list[str]", description="List of Spotify track IDs to remove"),
            ],
        )(self.remove_tracks)

        registry.register(
            name="spotify.update_playlist",
            description="Update a playlist's name, description, or visibility",
            category="spotify",
            parameters=[
                _USER_PARAM,
                MCPToolParam(name="playlist_id", type="str", description="Spotify playlist ID"),
                MCPToolParam(name="name", type="str", description="New playlist name", required=False),
                MCPToolParam(name="description", type="str", description="New playlist description", required=False),
                MCPToolParam(name="public", type="bool", description="Set public/private", required=False),
            ],
        )(self.update_playlist)

    async def _get_client(self, user_id: int, session: AsyncSession) -> SpotifyClient:
        """Create a SpotifyClient with token management for the given user."""
        settings = get_settings()
        token_mgr = TokenManager(settings)
        access_token = await token_mgr.get_valid_token(user_id, session)

        async def _on_token_expired() -> str:
            return await token_mgr.refresh_access_token(user_id, session)

        return SpotifyClient(access_token, on_token_expired=_on_token_expired)

    async def _check_write_scopes(self, user_id: int, session: AsyncSession) -> str | None:
        """Check that the user's token has playlist-modify scopes. Returns error message or None."""
        result = await session.execute(select(SpotifyToken.scope).where(SpotifyToken.user_id == user_id))
        scope_str = result.scalar_one_or_none()
        if scope_str is None:
            return "No token found for this user. Please authorize via /auth/login."
        granted = set(scope_str.split())
        missing = _PLAYLIST_WRITE_SCOPES - granted
        if missing:
            return (
                f"Missing required scopes: {', '.join(sorted(missing))}. "
                "Please re-authorize via /auth/login to grant playlist write permissions."
            )
        return None

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
        result = {
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
        # --- TEMPORARY DEBUG: raw Spotify response info ---
        try:
            from shared.spotify.constants import PLAYLIST_URL

            # Raw request WITHOUT market
            raw_resp = await client._request("GET", f"{PLAYLIST_URL}/{args['playlist_id']}")  # noqa: SLF001
            raw_json = raw_resp.json()
            raw_tracks = raw_json.get("tracks", "_MISSING_")
            # Raw request WITH market
            raw_resp2 = await client._request(  # noqa: SLF001
                "GET", f"{PLAYLIST_URL}/{args['playlist_id']}", params={"market": "from_token"}
            )
            raw_json2 = raw_resp2.json()
            raw_tracks2 = raw_json2.get("tracks", "_MISSING_")
            debug: dict[str, Any] = {
                "raw_top_keys": sorted(raw_json.keys()),
                "raw_has_tracks_key": "tracks" in raw_json,
                "raw_tracks_keys": list(raw_tracks.keys()) if isinstance(raw_tracks, dict) else str(raw_tracks)[:200],
                "with_market_tracks_total": raw_tracks2.get("total") if isinstance(raw_tracks2, dict) else None,
                "with_market_items_count": len(raw_tracks2.get("items", [])) if isinstance(raw_tracks2, dict) else None,
                "with_market_tracks_keys": list(raw_tracks2.keys())
                if isinstance(raw_tracks2, dict)
                else str(raw_tracks2)[:200],
            }
            result["_debug"] = debug
        except Exception:
            pass
        # --- END TEMPORARY DEBUG ---
        return result

    async def create_playlist(self, args: dict[str, Any], session: AsyncSession) -> Any:
        scope_error = await self._check_write_scopes(args["user_id"], session)
        if scope_error:
            raise ValueError(scope_error)
        client = await self._get_client(args["user_id"], session)
        pl = await client.create_playlist(
            name=args["name"],
            description=args.get("description", ""),
            public=args.get("public", True),
        )
        return {
            "id": pl.id,
            "name": pl.name,
            "description": pl.description,
            "public": pl.public,
            "external_urls": pl.external_urls,
        }

    async def add_tracks(self, args: dict[str, Any], session: AsyncSession) -> Any:
        scope_error = await self._check_write_scopes(args["user_id"], session)
        if scope_error:
            raise ValueError(scope_error)
        track_ids: list[str] = args["track_ids"]
        if not track_ids:
            raise ValueError("track_ids must not be empty.")
        if len(track_ids) > 100:
            raise ValueError("Maximum 100 tracks per call.")
        uris = [f"spotify:track:{tid}" for tid in track_ids]
        client = await self._get_client(args["user_id"], session)
        result = await client.add_tracks_to_playlist(args["playlist_id"], uris)
        return {"snapshot_id": result.snapshot_id, "tracks_added": len(track_ids)}

    async def remove_tracks(self, args: dict[str, Any], session: AsyncSession) -> Any:
        scope_error = await self._check_write_scopes(args["user_id"], session)
        if scope_error:
            raise ValueError(scope_error)
        track_ids: list[str] = args["track_ids"]
        if not track_ids:
            raise ValueError("track_ids must not be empty.")
        if len(track_ids) > 100:
            raise ValueError("Maximum 100 tracks per call.")
        uris = [f"spotify:track:{tid}" for tid in track_ids]
        client = await self._get_client(args["user_id"], session)
        result = await client.remove_tracks_from_playlist(args["playlist_id"], uris)
        return {"snapshot_id": result.snapshot_id, "tracks_removed": len(track_ids)}

    async def update_playlist(self, args: dict[str, Any], session: AsyncSession) -> Any:
        scope_error = await self._check_write_scopes(args["user_id"], session)
        if scope_error:
            raise ValueError(scope_error)
        name = args.get("name")
        description = args.get("description")
        public = args.get("public")
        if name is None and description is None and public is None:
            raise ValueError("At least one of name, description, or public must be provided.")
        client = await self._get_client(args["user_id"], session)
        await client.update_playlist_details(
            args["playlist_id"],
            name=name,
            description=description,
            public=public,
        )
        return {"updated": True, "playlist_id": args["playlist_id"]}


_instance = PlaylistToolHandlers()
