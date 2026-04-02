"""Playlist cache, detail, and track fetching."""

import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.exceptions import TokenNotFoundError, TokenRefreshError
from app.auth.tokens import TokenManager
from app.cache.service import SpotifyCacheService
from app.explorer.schemas import (
    PlaylistDetail,
    PlaylistSummary,
    PlaylistTrackItem,
)
from app.explorer.services._base import BaseExplorerService
from app.settings import get_settings
from shared.db.models.cache import CachedPlaylist
from shared.db.models.operations import SyncCheckpoint
from shared.spotify.client import SpotifyClient
from shared.spotify.embed import SpotifyEmbedClient
from shared.spotify.exceptions import (
    SpotifyAuthError,
    SpotifyClientError,
    SpotifyEmbedError,
    SpotifyRateLimitError,
    SpotifyRequestError,
)
from shared.spotify.models import SpotifyPlaylistSimplified, SpotifyPlaylistTrackItem

logger = logging.getLogger(__name__)


class PlaylistService(BaseExplorerService):
    """Manages playlist caching, metadata refresh, and track fetching."""

    # Spotify API page size for playlist listing (max allowed by Spotify is 50)
    _PLAYLIST_FETCH_PAGE_SIZE: int = 50

    @staticmethod
    def _playlist_to_summary(p: CachedPlaylist) -> PlaylistSummary:
        return PlaylistSummary(
            id=p.id,
            spotify_playlist_id=p.spotify_playlist_id,
            name=p.name or "",
            description=p.description,
            total_tracks=p.total_tracks or 0,
            owner_display_name=p.owner_display_name,
            external_url=p.external_url,
        )

    async def get_playlists(self, user_id: int, session: AsyncSession) -> list[PlaylistSummary]:
        """Return all cached playlists for the user.

        Auto-fetches from Spotify if the cache is older than the configured TTL.
        """
        ttl_minutes: int = await self.settings.get("explorer.playlist_cache_ttl_minutes", 60, session)
        cache_ttl = timedelta(minutes=ttl_minutes)

        checkpoint_result = await session.execute(
            select(SyncCheckpoint.playlist_cache_synced_at).where(SyncCheckpoint.user_id == user_id)
        )
        synced_at = checkpoint_result.scalar_one_or_none()

        if synced_at is not None:
            if synced_at.tzinfo is None:
                synced_at = synced_at.replace(tzinfo=UTC)
            cache_stale = datetime.now(UTC) - synced_at > cache_ttl
        else:
            cache_stale = True

        result = await session.execute(
            select(CachedPlaylist).where(CachedPlaylist.user_id == user_id).order_by(CachedPlaylist.name)
        )
        playlists: list[CachedPlaylist] = list(result.scalars().all())

        if cache_stale:
            refreshed = await self._fetch_playlists_from_spotify(user_id, session)
            if refreshed is not None:
                playlists = refreshed

        return [self._playlist_to_summary(p) for p in playlists]

    async def refresh_playlists(self, user_id: int, session: AsyncSession) -> list[PlaylistSummary]:
        """Force-refresh playlists from Spotify API regardless of cache age."""
        refreshed = await self._fetch_playlists_from_spotify(user_id, session)
        if refreshed is None:
            result = await session.execute(
                select(CachedPlaylist).where(CachedPlaylist.user_id == user_id).order_by(CachedPlaylist.name)
            )
            refreshed = list(result.scalars().all())
        return [self._playlist_to_summary(p) for p in refreshed]

    async def _fetch_playlists_from_spotify(self, user_id: int, session: AsyncSession) -> list[CachedPlaylist] | None:
        """Fetch user playlists from Spotify API and upsert metadata into cached_playlists.

        Returns the updated list ordered by name, or None if Spotify is unreachable.
        Does NOT fetch tracks — only playlist metadata.
        """
        try:
            client = await self._get_spotify_client(user_id, session)
            fetch_max: int = await self.settings.get("explorer.playlist_fetch_max", 500, session)

            offset = 0
            all_items: list[SpotifyPlaylistSimplified] = []
            while offset < fetch_max:
                response = await client.get_user_playlists(limit=self._PLAYLIST_FETCH_PAGE_SIZE, offset=offset)
                all_items.extend(response.items)
                if len(response.items) < self._PLAYLIST_FETCH_PAGE_SIZE or response.next is None:
                    break
                offset += self._PLAYLIST_FETCH_PAGE_SIZE

            existing_rows_result = await session.execute(
                select(CachedPlaylist).where(CachedPlaylist.user_id == user_id)
            )
            existing_by_id: dict[str, CachedPlaylist] = {
                row.spotify_playlist_id: row for row in existing_rows_result.scalars() if row.spotify_playlist_id
            }

            fetched_ids: set[str] = set()
            now = datetime.now(UTC)
            for item in all_items:
                if not item.id:
                    continue
                fetched_ids.add(item.id)
                total_tracks = (item.tracks or {}).get("total", 0)
                external_url = (item.external_urls or {}).get("spotify")
                owner_id = item.owner.id if item.owner else None
                owner_name = item.owner.display_name if item.owner else None

                existing = existing_by_id.get(item.id)
                if existing is not None:
                    existing.name = item.name
                    existing.description = item.description
                    existing.public = item.public
                    existing.snapshot_id = item.snapshot_id
                    existing.total_tracks = total_tracks
                    existing.external_url = external_url
                    existing.owner_id = owner_id
                    existing.owner_display_name = owner_name
                    existing.fetched_at = now
                else:
                    session.add(
                        CachedPlaylist(
                            spotify_playlist_id=item.id,
                            user_id=user_id,
                            name=item.name,
                            description=item.description,
                            public=item.public,
                            snapshot_id=item.snapshot_id,
                            total_tracks=total_tracks,
                            external_url=external_url,
                            owner_id=owner_id,
                            owner_display_name=owner_name,
                            fetched_at=now,
                        )
                    )

            stale_stmt = delete(CachedPlaylist).where(CachedPlaylist.user_id == user_id)
            if fetched_ids:
                stale_stmt = stale_stmt.where(~CachedPlaylist.spotify_playlist_id.in_(fetched_ids))
            await session.execute(stale_stmt)

            cp_result = await session.execute(select(SyncCheckpoint).where(SyncCheckpoint.user_id == user_id))
            checkpoint = cp_result.scalar_one_or_none()
            if checkpoint is None:
                checkpoint = SyncCheckpoint(user_id=user_id, playlist_cache_synced_at=now)
                session.add(checkpoint)
            else:
                checkpoint.playlist_cache_synced_at = now

            await session.flush()

            result = await session.execute(
                select(CachedPlaylist).where(CachedPlaylist.user_id == user_id).order_by(CachedPlaylist.name)
            )
            return list(result.scalars().all())

        except (
            TokenNotFoundError,
            TokenRefreshError,
            SpotifyAuthError,
            SpotifyClientError,
            SpotifyRateLimitError,
            SpotifyRequestError,
        ):
            logger.warning("Failed to fetch playlists from Spotify for user %d", user_id, exc_info=True)
            return None

    async def get_playlist_detail(
        self, user_id: int, spotify_playlist_id: str, session: AsyncSession
    ) -> PlaylistDetail | None:
        """Return playlist with tracks, or None if not found for this user."""
        result = await session.execute(
            select(CachedPlaylist)
            .where(CachedPlaylist.user_id == user_id, CachedPlaylist.spotify_playlist_id == spotify_playlist_id)
            .options(selectinload(CachedPlaylist.tracks))
        )
        playlist = result.scalar_one_or_none()
        if playlist is None:
            return None
        return PlaylistDetail(
            id=playlist.id,
            spotify_playlist_id=playlist.spotify_playlist_id,
            name=playlist.name or "",
            description=playlist.description,
            total_tracks=playlist.total_tracks or 0,
            owner_display_name=playlist.owner_display_name,
            external_url=playlist.external_url,
            tracks=[
                PlaylistTrackItem(
                    position=t.position,
                    spotify_track_id=t.spotify_track_id,
                    track_name=t.track_name,
                    artists_json=json.loads(t.artists_json) if t.artists_json else [],
                    added_at=t.added_at,
                )
                for t in sorted(playlist.tracks, key=lambda t: t.position)
            ],
        )

    async def fetch_playlist_tracks(
        self, user_id: int, spotify_playlist_id: str, session: AsyncSession
    ) -> PlaylistDetail | None:
        """Fetch tracks from Spotify API (with embed fallback for 403) and cache them."""
        result = await session.execute(
            select(CachedPlaylist).where(
                CachedPlaylist.user_id == user_id,
                CachedPlaylist.spotify_playlist_id == spotify_playlist_id,
            )
        )
        playlist = result.scalar_one_or_none()
        if playlist is None:
            return None

        settings = get_settings()
        token_mgr = TokenManager(settings)
        access_token = await token_mgr.get_valid_token(user_id, session)

        async def _on_token_expired() -> str:
            return await token_mgr.refresh_access_token(user_id, session)

        client = SpotifyClient(access_token, on_token_expired=_on_token_expired)

        pl = await client.get_playlist(spotify_playlist_id)

        tracks: list[dict[str, object]] = []
        _need_embed = False

        def _parse_api_tracks(items: list[SpotifyPlaylistTrackItem]) -> list[dict[str, object]]:
            parsed: list[dict[str, object]] = []
            for item in items:
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
                        {"id": None, "name": None, "artists": [], "added_at": item.added_at, "unavailable": True}
                    )
            return parsed

        try:
            tracks = _parse_api_tracks(await client.get_playlist_all_tracks(spotify_playlist_id))
        except SpotifyRequestError as exc:
            if exc.status_code != 403:
                raise
            logger.warning(
                "Spotify 403 for playlist %s tracks — force-refreshing token and retrying",
                spotify_playlist_id,
            )
            try:
                new_token = await token_mgr.refresh_access_token(user_id, session)
                retry_client = SpotifyClient(new_token, on_token_expired=_on_token_expired)
                tracks = _parse_api_tracks(await retry_client.get_playlist_all_tracks(spotify_playlist_id))
                logger.info(
                    "Token-refresh retry succeeded for playlist %s (%d tracks)", spotify_playlist_id, len(tracks)
                )
            except SpotifyRequestError as retry_exc:
                if retry_exc.status_code != 403:
                    raise
                _need_embed = True

        if _need_embed:
            logger.info("Trying embed fallback for playlist %s", spotify_playlist_id)
            embed_client = SpotifyEmbedClient()
            try:
                embed_items = await embed_client.fetch_playlist_tracks(spotify_playlist_id)
                for ei in embed_items:
                    if ei.track_id:
                        tracks.append(
                            {"id": ei.track_id, "name": ei.name, "artists": [{"name": a} for a in ei.artists]}
                        )
                    else:
                        tracks.append(
                            {
                                "id": None,
                                "name": ei.name or None,
                                "artists": [{"name": a} for a in ei.artists],
                                "unavailable": True,
                            }
                        )
                logger.info("Embed fallback returned %d tracks for playlist %s", len(tracks), spotify_playlist_id)
            except SpotifyEmbedError as embed_exc:
                logger.warning("Embed fallback also failed for playlist %s: %s", spotify_playlist_id, embed_exc)
                raise SpotifyRequestError(
                    403, "Playlist tracks are restricted and embed fallback failed"
                ) from embed_exc

        playlist_data = {
            "id": pl.id,
            "name": pl.name,
            "description": pl.description,
            "public": pl.public,
            "owner": pl.owner.display_name if pl.owner else None,
            "tracks_total": pl.tracks.total if pl.tracks else 0,
            "snapshot_id": pl.snapshot_id,
            "external_urls": pl.external_urls,
        }

        cache = SpotifyCacheService(cache_ttl_hours=settings.SPOTIFY_CACHE_TTL_HOURS)
        await cache.put_playlist(user_id, playlist_data, tracks, session)
        await session.commit()

        logger.info("Fetched %d tracks for playlist %s", len(tracks), spotify_playlist_id)
        return await self.get_playlist_detail(user_id, spotify_playlist_id, session)
