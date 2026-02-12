"""MCP tool handlers for live Spotify API queries."""

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


@registry.register(
    name="spotify.get_top",
    description="Spotify's native top artists or tracks for the user (requires active OAuth)",
    category="spotify",
    parameters=[
        _USER_PARAM,
        MCPToolParam(name="entity", type="str", description="'artists' or 'tracks'", required=False, default="artists"),
        MCPToolParam(
            name="time_range",
            type="str",
            description="'short_term' (4w), 'medium_term' (6m), or 'long_term' (years)",
            required=False,
            default="medium_term",
        ),
        MCPToolParam(name="limit", type="int", description="Max results (1-50)", required=False, default=20),
    ],
)
async def get_top(args: dict[str, Any], session: AsyncSession) -> Any:
    settings = get_settings()
    token_mgr = TokenManager(settings)
    user_id = args["user_id"]
    access_token = await token_mgr.get_valid_token(user_id, session)

    async def _on_token_expired() -> str:
        return await token_mgr.refresh_access_token(user_id, session)

    client = SpotifyClient(access_token, on_token_expired=_on_token_expired)

    entity = args.get("entity", "artists")
    if entity not in {"artists", "tracks"}:
        raise ValueError("entity must be 'artists' or 'tracks'")

    time_range = args.get("time_range", "medium_term")
    if time_range not in {"short_term", "medium_term", "long_term"}:
        raise ValueError("time_range must be 'short_term', 'medium_term', or 'long_term'")

    limit = max(1, min(args.get("limit", 20), 50))

    if entity == "tracks":
        tracks_resp = await client.get_top_tracks(time_range=time_range, limit=limit)
        return [{"name": t.name, "id": t.id, "artists": [a.name for a in t.artists]} for t in tracks_resp.items]
    else:
        artists_resp = await client.get_top_artists(time_range=time_range, limit=limit)
        return [{"name": a.name, "id": a.id, "genres": a.genres or []} for a in artists_resp.items]


@registry.register(
    name="spotify.search",
    description="Search Spotify for tracks, artists, or albums (requires active OAuth)",
    category="spotify",
    parameters=[
        _USER_PARAM,
        MCPToolParam(name="q", type="str", description="Search query"),
        MCPToolParam(
            name="type",
            type="str",
            description="'track', 'artist', or 'album'",
            required=False,
            default="track",
        ),
        MCPToolParam(name="limit", type="int", description="Max results (1-50)", required=False, default=10),
    ],
)
async def search(args: dict[str, Any], session: AsyncSession) -> Any:
    settings = get_settings()
    token_mgr = TokenManager(settings)
    user_id = args["user_id"]
    access_token = await token_mgr.get_valid_token(user_id, session)

    async def _on_token_expired() -> str:
        return await token_mgr.refresh_access_token(user_id, session)

    client = SpotifyClient(access_token, on_token_expired=_on_token_expired)

    search_type = args.get("type", "track")
    if search_type not in {"track", "artist", "album"}:
        raise ValueError("type must be 'track', 'artist', or 'album'")

    limit = max(1, min(args.get("limit", 10), 50))

    resp = await client.search(
        args["q"],
        search_type=search_type,
        limit=limit,
    )
    results: list[dict[str, Any]] = []
    if resp.tracks:
        for t in resp.tracks.items:
            results.append({"type": "track", "name": t.name, "id": t.id, "artists": [a.name for a in t.artists]})
    if resp.artists:
        for a in resp.artists.items:
            results.append({"type": "artist", "name": a.name, "id": a.id})
    if resp.albums:
        for al in resp.albums.items:
            results.append({"type": "album", "name": al.name, "id": al.id})
    return results
