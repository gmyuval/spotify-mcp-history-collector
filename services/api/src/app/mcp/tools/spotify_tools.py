"""MCP tool handlers for live Spotify API queries — class-based."""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import TokenManager
from app.cache.service import SpotifyCacheService
from app.mcp.registry import registry
from app.mcp.schemas import MCPToolParam
from app.settings import get_settings
from shared.spotify.client import SpotifyClient

logger = logging.getLogger(__name__)

_USER_PARAM = MCPToolParam(name="user_id", type="int", description="User ID (must have active OAuth)")


class SpotifyToolHandlers:
    """Registers and handles live Spotify API MCP tools.

    Integrates a :class:`SpotifyCacheService` so that ``get_track``,
    ``get_artist``, and ``get_album`` serve cached data when available
    (within the configured TTL) and fall through to the Spotify API on
    cache miss.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._cache = SpotifyCacheService(cache_ttl_hours=settings.SPOTIFY_CACHE_TTL_HOURS)
        self._register()

    def _register(self) -> None:
        registry.register(
            name="spotify.get_top",
            description="Spotify's native top artists or tracks for the user (requires active OAuth)",
            category="spotify",
            parameters=[
                _USER_PARAM,
                MCPToolParam(
                    name="entity", type="str", description="'artists' or 'tracks'", required=False, default="artists"
                ),
                MCPToolParam(
                    name="time_range",
                    type="str",
                    description="'short_term' (4w), 'medium_term' (6m), or 'long_term' (years)",
                    required=False,
                    default="medium_term",
                ),
                MCPToolParam(name="limit", type="int", description="Max results (1-50)", required=False, default=20),
            ],
        )(self.get_top)

        registry.register(
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
        )(self.search)

        registry.register(
            name="spotify.get_track",
            description="Get detailed info for a Spotify track by ID (name, artists, album, duration, popularity)",
            category="spotify",
            parameters=[
                _USER_PARAM,
                MCPToolParam(name="track_id", type="str", description="Spotify track ID"),
            ],
        )(self.get_track)

        registry.register(
            name="spotify.get_artist",
            description="Get detailed info for a Spotify artist by ID (genres, popularity, followers, images)",
            category="spotify",
            parameters=[
                _USER_PARAM,
                MCPToolParam(name="artist_id", type="str", description="Spotify artist ID"),
            ],
        )(self.get_artist)

        registry.register(
            name="spotify.get_album",
            description="Get album details and full track listing by album ID",
            category="spotify",
            parameters=[
                _USER_PARAM,
                MCPToolParam(name="album_id", type="str", description="Spotify album ID"),
            ],
        )(self.get_album)

    async def _get_client(self, user_id: int, session: AsyncSession) -> SpotifyClient:
        """Create a SpotifyClient with token management for the given user."""
        settings = get_settings()
        token_mgr = TokenManager(settings)
        access_token = await token_mgr.get_valid_token(user_id, session)

        async def _on_token_expired() -> str:
            return await token_mgr.refresh_access_token(user_id, session)

        return SpotifyClient(access_token, on_token_expired=_on_token_expired)

    async def get_top(self, args: dict[str, Any], session: AsyncSession) -> Any:
        client = await self._get_client(args["user_id"], session)

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

    async def search(self, args: dict[str, Any], session: AsyncSession) -> Any:
        client = await self._get_client(args["user_id"], session)

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

    async def get_track(self, args: dict[str, Any], session: AsyncSession) -> Any:
        track_id: str = args["track_id"]

        # Check cache first
        cached = await self._cache.get_entity("track", track_id, session)
        if cached is not None:
            return cached

        # Cache miss — fetch from API
        client = await self._get_client(args["user_id"], session)
        track = await client.get_track(track_id)
        result = {
            "id": track.id,
            "name": track.name,
            "artists": [{"id": a.id, "name": a.name} for a in track.artists],
            "album": {"id": track.album.id, "name": track.album.name} if track.album else None,
            "duration_ms": track.duration_ms,
            "popularity": track.popularity,
            "explicit": track.explicit,
            "external_urls": track.external_urls,
        }

        await self._cache.put_entity("track", track_id, result, session)
        return result

    async def get_artist(self, args: dict[str, Any], session: AsyncSession) -> Any:
        artist_id: str = args["artist_id"]

        cached = await self._cache.get_entity("artist", artist_id, session)
        if cached is not None:
            return cached

        client = await self._get_client(args["user_id"], session)
        artist = await client.get_artist(artist_id)
        result = {
            "id": artist.id,
            "name": artist.name,
            "genres": artist.genres,
            "popularity": artist.popularity,
            "followers": artist.followers,
            "images": [{"url": img.url, "height": img.height, "width": img.width} for img in (artist.images or [])],
            "external_urls": artist.external_urls,
        }

        await self._cache.put_entity("artist", artist_id, result, session)
        return result

    async def get_album(self, args: dict[str, Any], session: AsyncSession) -> Any:
        album_id: str = args["album_id"]

        cached = await self._cache.get_entity("album", album_id, session)
        if cached is not None:
            return cached

        client = await self._get_client(args["user_id"], session)
        album = await client.get_album(album_id)
        tracks_list = []
        if album.tracks:
            for t in album.tracks.items:
                tracks_list.append(
                    {
                        "id": t.id,
                        "name": t.name,
                        "track_number": t.track_number,
                        "duration_ms": t.duration_ms,
                        "artists": [{"id": a.id, "name": a.name} for a in t.artists],
                    }
                )
        result = {
            "id": album.id,
            "name": album.name,
            "album_type": album.album_type,
            "release_date": album.release_date,
            "total_tracks": album.total_tracks,
            "artists": [{"id": a.id, "name": a.name} for a in album.artists],
            "genres": album.genres,
            "popularity": album.popularity,
            "label": album.label,
            "tracks": tracks_list,
            "images": [{"url": img.url} for img in (album.images or [])],
            "external_urls": album.external_urls,
        }

        await self._cache.put_entity("album", album_id, result, session)
        return result


_instance = SpotifyToolHandlers()
