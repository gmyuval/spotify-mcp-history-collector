"""MCP tool handlers for Spotify playlist operations — class-based."""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import TokenManager
from app.cache.service import SpotifyCacheService
from app.mcp.registry import registry
from app.mcp.schemas import MCPToolParam
from app.settings import get_settings
from shared.db.models.user import SpotifyToken
from shared.spotify.client import SpotifyClient
from shared.spotify.embed import SpotifyEmbedClient
from shared.spotify.exceptions import SpotifyEmbedError, SpotifyRequestError

logger = logging.getLogger(__name__)

_USER_PARAM = MCPToolParam(name="user_id", type="int", description="User ID (must have active OAuth)")

_PLAYLIST_WRITE_SCOPES = {"playlist-modify-public", "playlist-modify-private"}


class PlaylistToolHandlers:
    """Registers and handles playlist-related MCP tools.

    Integrates a :class:`SpotifyCacheService` for playlist caching:

    - **list_playlists:** Always fetches fresh from API, caches summaries
      (including snapshot_ids) for use by ``get_playlist``.
    - **get_playlist:** Compares live snapshot_id against cached value;
      serves from cache on match, re-fetches on mismatch.
    - **Write operations:** Always hit the API, then invalidate the
      affected playlist's cache.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._cache = SpotifyCacheService(cache_ttl_hours=settings.SPOTIFY_CACHE_TTL_HOURS)
        self._embed_client = SpotifyEmbedClient()
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

    async def _force_refresh_token(self, user_id: int, session: AsyncSession) -> str:
        """Force-refresh the Spotify access token for a user. Extracted for testability."""
        return await TokenManager(get_settings()).refresh_access_token(user_id, session)

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
        playlists = [
            {
                "id": p.id,
                "name": p.name,
                "public": p.public,
                "tracks_total": p.tracks.get("total") if p.tracks else None,
                "owner": p.owner.display_name if p.owner else None,
                "snapshot_id": p.snapshot_id,
            }
            for p in resp.items
        ]

        # Update cache with latest playlist summaries (stores snapshot_ids)
        await self._cache.put_playlist_list(args["user_id"], playlists, session)

        # Strip snapshot_id from client response (internal use only)
        return [{k: v for k, v in pl.items() if k != "snapshot_id"} for pl in playlists]

    async def get_playlist(self, args: dict[str, Any], session: AsyncSession) -> Any:
        user_id: int = args["user_id"]
        playlist_id: str = args["playlist_id"]

        # Check if we have a cached version with a matching snapshot_id
        cached_snapshots = await self._cache.get_cached_playlist_snapshot_ids(user_id, session)
        cached_snapshot = cached_snapshots.get(playlist_id)

        # Try to fetch playlist metadata from Spotify API.
        # GET /playlists/{id} may return 403 in some Spotify developer modes;
        # if so, fall back to cached metadata from list_playlists.
        client = await self._get_client(user_id, session)
        pl = None
        try:
            pl = await client.get_playlist(playlist_id)
        except SpotifyRequestError as exc:
            if exc.status_code == 403:
                logger.warning(
                    "Spotify returned 403 for GET /playlists/%s, falling back to cached metadata",
                    playlist_id,
                )
            else:
                raise

        if pl is not None and cached_snapshot and pl.snapshot_id == cached_snapshot:
            # Snapshot matches — try serving from cache.
            # Accept cache hit if tracks are populated or playlist is legitimately empty.
            # Do NOT serve from cache when the cached result was tracks_restricted —
            # re-authorization may have fixed access, so always retry the live API.
            cached_data = await self._cache.get_cached_playlist(user_id, playlist_id, session)
            if cached_data is not None and not cached_data.get("tracks_restricted"):
                cached_tracks = cached_data.get("tracks", [])
                cached_total = cached_data.get("tracks_total") or 0
                # Serve from cache only if tracks look complete and healthy.
                # Skip cache when count mismatches total, or when excessive
                # duplicates indicate a stale cache from earlier pagination bugs
                # (e.g. 300 cached tracks that are really 100 × 3 duplicates).
                _cache_ok = cached_total == 0 or len(cached_tracks) == cached_total
                if _cache_ok and cached_tracks:
                    _cached_ids = [t.get("id") for t in cached_tracks if t.get("id")]
                    _unique_count = len(set(_cached_ids))
                    _dup_ratio = 1 - (_unique_count / len(_cached_ids)) if _cached_ids else 0
                    if _dup_ratio > 0.3:
                        _cache_ok = False
                        logger.warning(
                            "Cache for %s has %.0f%% duplicate tracks (%d unique / %d total)"
                            " — likely stale, re-fetching",
                            playlist_id,
                            _dup_ratio * 100,
                            _unique_count,
                            len(_cached_ids),
                        )
                if _cache_ok:
                    logger.debug("Playlist cache hit for %s (snapshot matched)", playlist_id)
                    return self._with_fidelity_metrics(cached_data)
                logger.info(
                    "Stale cache for %s: %d cached tracks vs %d total — re-fetching",
                    playlist_id,
                    len(cached_tracks),
                    cached_total,
                )

        # If metadata was 403, resolve cached metadata now — fail fast before
        # attempting the tracks endpoint (which will also 403).
        cached_metadata: dict[str, Any] | None = None
        if pl is None:
            cached_metadata = await self._cache.get_cached_playlist(user_id, playlist_id, session)
            if cached_metadata is None:
                raise ValueError(
                    "Spotify returned 403 for playlist metadata and no cached metadata is available. "
                    "Call spotify.list_playlists first to populate the cache, then retry."
                )

        # Fetch all tracks via pagination (uses GET /playlists/{id}/items).
        # On 403: force-refresh the token once (picks up new scopes from re-auth) and
        # retry. If still 403, fall back to the embed endpoint. If embed also fails,
        # mark as restricted.
        tracks: list[dict[str, Any]] = []
        tracks_source = "api"
        tracks_restricted = False
        _need_embed = False  # set to True when both API attempts return 403

        def _parse_track_items(all_track_items: list[Any]) -> list[dict[str, Any]]:
            parsed: list[dict[str, Any]] = []
            for item in all_track_items:
                if item.track:
                    parsed.append(
                        {
                            "id": item.track.id,
                            "name": item.track.name,
                            "artists": [{"id": a.id, "name": a.name} for a in item.track.artists],
                            "added_at": item.added_at,
                        }
                    )
                else:
                    parsed.append(
                        {
                            "id": None,
                            "name": None,
                            "artists": [],
                            "added_at": item.added_at,
                            "unavailable": True,
                        }
                    )
            return parsed

        try:
            tracks = _parse_track_items(await client.get_playlist_all_tracks(playlist_id))
        except SpotifyRequestError as exc:
            if exc.status_code != 403:
                raise
            logger.warning(
                "Spotify returned 403 for GET /playlists/%s/items (detail: %s) — "
                "force-refreshing token and retrying once",
                playlist_id,
                exc.detail,
            )
            # Force-refresh the access token to pick up any new scopes from re-authorization,
            # then retry the items endpoint once before falling back to embed.
            try:
                await self._force_refresh_token(user_id, session)
                _retry_client = await self._get_client(user_id, session)
                tracks = _parse_track_items(await _retry_client.get_playlist_all_tracks(playlist_id))
                logger.info(
                    "Token-refresh retry succeeded for playlist %s (%d tracks)",
                    playlist_id,
                    len(tracks),
                )
            except SpotifyRequestError as retry_exc:
                if retry_exc.status_code != 403:
                    raise
                logger.warning(
                    "Spotify returned 403 after token refresh for GET /playlists/%s/items "
                    "(detail: %s) — using tracks from metadata response",
                    playlist_id,
                    retry_exc.detail,
                )
                # Fallback: use tracks already embedded in the GET /playlists/{id}
                # response (up to 100). The separate /tracks endpoint is blocked in
                # Spotify's development mode, but the main playlist endpoint works.
                if pl is not None and pl.tracks and pl.tracks.items:
                    tracks = _parse_track_items(pl.tracks.items)
                    tracks_source = "api_metadata"
                    logger.info(
                        "Using %d tracks from metadata response for playlist %s (total reported: %s)",
                        len(tracks),
                        playlist_id,
                        pl.tracks.total,
                    )
                else:
                    _need_embed = True

        if _need_embed:
            try:
                embed_items = await self._embed_client.fetch_playlist_tracks(playlist_id)
                for embed_item in embed_items:
                    if embed_item.track_id:
                        tracks.append(
                            {
                                "id": embed_item.track_id,
                                "name": embed_item.name,
                                "artists": [{"name": a} for a in embed_item.artists],
                                "duration_ms": embed_item.duration_ms,
                            }
                        )
                    else:
                        tracks.append(
                            {
                                "id": None,
                                "name": embed_item.name or None,
                                "artists": [{"name": a} for a in embed_item.artists],
                                "duration_ms": embed_item.duration_ms,
                                "unavailable": True,
                            }
                        )
                tracks_source = "embed"
                logger.info(
                    "Embed fallback returned %d tracks for playlist %s",
                    len(tracks),
                    playlist_id,
                )
            except SpotifyEmbedError as embed_exc:
                logger.warning(
                    "Embed fallback also failed for playlist %s: %s",
                    playlist_id,
                    embed_exc,
                )
                tracks_restricted = True
                tracks_source = "restricted"

        # Determine if restricted playlist is private — embed only works for public playlists.
        # pl.public is bool | None; treat None as non-public (private or collaborative).
        _is_private = False
        if tracks_restricted:
            if pl is not None:
                _is_private = not pl.public
            elif cached_metadata is not None:
                _is_private = not cached_metadata.get("public")

        # Track fidelity metrics
        tracks_returned = len(tracks)
        tracks_unavailable = sum(1 for t in tracks if t.get("unavailable"))

        # Build result from live API metadata or cached metadata fallback
        if pl is not None:
            result: dict[str, Any] = {
                "id": pl.id,
                "name": pl.name,
                "description": pl.description,
                "public": pl.public,
                "owner": pl.owner.display_name if pl.owner else None,
                "tracks_total": pl.tracks.total if pl.tracks else 0,
                "tracks": tracks,
                "tracks_source": tracks_source,
                "snapshot_id": pl.snapshot_id,
                "external_urls": pl.external_urls,
            }
        else:
            # cached_metadata is guaranteed non-None (checked above)
            assert cached_metadata is not None
            result = {
                "id": playlist_id,
                "name": cached_metadata.get("name", ""),
                "description": cached_metadata.get("description"),
                "public": cached_metadata.get("public"),
                "owner": cached_metadata.get("owner"),
                "tracks_total": cached_metadata.get("tracks_total", 0),
                "tracks": tracks,
                "tracks_source": tracks_source,
                "snapshot_id": cached_metadata.get("snapshot_id"),
                "external_urls": cached_metadata.get("external_urls", {}),
            }

        # Add fidelity metrics (same logic as _with_fidelity_metrics, but we already
        # have tracks_returned/tracks_unavailable computed above so apply directly)
        result["tracks_returned"] = tracks_returned
        if tracks_unavailable:
            result["tracks_unavailable"] = tracks_unavailable
        tracks_total = result.get("tracks_total", 0)
        if tracks_returned != tracks_total and not tracks_restricted:
            mismatch_msg = (
                f"Spotify reports {tracks_total} tracks but {tracks_returned} were returned. "
                f"{tracks_unavailable} unavailable placeholder(s) included."
            )
            if tracks_source in ("api_metadata", "embed"):
                mismatch_msg += (
                    " The Spotify Web API in development mode limits track retrieval to ~100 "
                    "for this playlist. You can use memory.backfill_playlist with the track_ids "
                    "parameter to log the complete track list if you have it."
                )
            result["tracks_mismatch_warning"] = mismatch_msg

        if tracks_restricted:
            result["tracks_restricted"] = True
            # Check whether the user's stored token includes playlist-read-private.
            # If it doesn't, a re-authorization will fix this — no need to use backfill.
            _scope_result = await session.execute(select(SpotifyToken.scope).where(SpotifyToken.user_id == user_id))
            _scope_str = _scope_result.scalar_one_or_none() or ""
            _has_read_private = "playlist-read-private" in _scope_str.split()

            if not _has_read_private:
                result["tracks_restricted_reason"] = (
                    "Your Spotify authorization is missing the 'playlist-read-private' scope. "
                    "Please re-authorize via /auth/login to enable private playlist access."
                )
            elif _is_private:
                result["tracks_restricted_reason"] = (
                    "Private playlist: Spotify returned 403 for this playlist's tracks even "
                    "though your token has playlist-read-private. This can happen in Spotify's "
                    "development mode for playlists not accessible to the app. "
                    "If you have the track IDs, use memory.backfill_playlist with track_ids and "
                    "name parameters to log this playlist manually."
                )
            else:
                result["tracks_restricted_reason"] = (
                    "Spotify returned 403 for this playlist's tracks. The playlist may be private "
                    "or restricted. If you have the track IDs, use memory.backfill_playlist with "
                    "track_ids and name parameters to log this playlist manually."
                )

        # Cache the full playlist with tracks
        await self._cache.put_playlist(user_id, result, tracks, session)
        return result

    @staticmethod
    def _with_fidelity_metrics(result: dict[str, Any]) -> dict[str, Any]:
        """Inject tracks_returned / tracks_unavailable / tracks_mismatch_warning.

        Applied to both live responses and cache-hit responses so the output
        shape is always consistent.
        """
        tracks: list[dict[str, Any]] = result.get("tracks", [])
        tracks_returned = len(tracks)
        tracks_unavailable = sum(1 for t in tracks if t.get("unavailable"))
        result["tracks_returned"] = tracks_returned
        if tracks_unavailable:
            result["tracks_unavailable"] = tracks_unavailable
        else:
            result.pop("tracks_unavailable", None)
        tracks_total: int = result.get("tracks_total") or 0
        if tracks_returned != tracks_total and not result.get("tracks_restricted"):
            result["tracks_mismatch_warning"] = (
                f"Spotify reports {tracks_total} tracks but {tracks_returned} were returned. "
                f"{tracks_unavailable} unavailable placeholder(s) included."
            )
        else:
            result.pop("tracks_mismatch_warning", None)
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
        # Invalidate playlist list cache so next list_playlists picks up the new one
        await self._cache.invalidate_all_playlists(args["user_id"], session)

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

        # Invalidate this playlist's cache
        await self._cache.invalidate_playlist(args["user_id"], args["playlist_id"], session)

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

        # Invalidate this playlist's cache
        await self._cache.invalidate_playlist(args["user_id"], args["playlist_id"], session)

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
        # Invalidate this playlist's cache
        await self._cache.invalidate_playlist(args["user_id"], args["playlist_id"], session)

        return {"updated": True, "playlist_id": args["playlist_id"]}


_instance = PlaylistToolHandlers()
