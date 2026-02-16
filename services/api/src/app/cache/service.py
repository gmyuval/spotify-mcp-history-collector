"""Spotify API cache service — OOP wrapper for cache read/write/invalidation."""

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models.cache import CachedPlaylist, CachedPlaylistTrack, SpotifyEntityCache

logger = logging.getLogger(__name__)


class SpotifyCacheService:
    """Manages Spotify API response caching in PostgreSQL.

    - **Playlists:** Uses Spotify's ``snapshot_id`` for invalidation.
    - **Entities (track/artist/album):** Uses a configurable TTL.
    """

    def __init__(self, *, cache_ttl_hours: int = 24) -> None:
        self._cache_ttl = timedelta(hours=cache_ttl_hours)

    # ------------------------------------------------------------------
    # Entity cache (track / artist / album)
    # ------------------------------------------------------------------

    async def get_entity(
        self,
        entity_type: str,
        spotify_id: str,
        session: AsyncSession,
    ) -> dict[str, Any] | None:
        """Return cached entity data if within TTL, else ``None``."""
        result = await session.execute(
            select(SpotifyEntityCache).where(
                SpotifyEntityCache.entity_type == entity_type,
                SpotifyEntityCache.spotify_id == spotify_id,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None

        if self._is_expired(row.fetched_at):
            logger.debug("Cache expired for %s:%s", entity_type, spotify_id)
            return None

        logger.debug("Cache hit for %s:%s", entity_type, spotify_id)
        cached_data: dict[str, Any] = json.loads(row.data_json)
        return cached_data

    async def put_entity(
        self,
        entity_type: str,
        spotify_id: str,
        data: dict[str, Any],
        session: AsyncSession,
    ) -> None:
        """Upsert an entity into the cache."""
        result = await session.execute(
            select(SpotifyEntityCache).where(
                SpotifyEntityCache.entity_type == entity_type,
                SpotifyEntityCache.spotify_id == spotify_id,
            )
        )
        row = result.scalar_one_or_none()
        now = datetime.now(UTC)
        data_str = json.dumps(data)

        if row is not None:
            row.data_json = data_str
            row.fetched_at = now
        else:
            session.add(
                SpotifyEntityCache(
                    entity_type=entity_type,
                    spotify_id=spotify_id,
                    data_json=data_str,
                    fetched_at=now,
                )
            )
        await session.flush()

    # ------------------------------------------------------------------
    # Playlist cache
    # ------------------------------------------------------------------

    async def get_cached_playlists(
        self,
        user_id: int,
        session: AsyncSession,
    ) -> list[dict[str, Any]] | None:
        """Return cached playlist list for a user if any exist, else ``None``.

        The caller compares snapshot_ids from the live API response to decide
        whether individual playlists need refreshing.
        """
        result = await session.execute(select(CachedPlaylist).where(CachedPlaylist.user_id == user_id))
        rows = result.scalars().all()
        if not rows:
            return None

        return [self._playlist_row_to_dict(row) for row in rows]

    async def get_cached_playlist_snapshot_ids(
        self,
        user_id: int,
        session: AsyncSession,
    ) -> dict[str, str]:
        """Return ``{spotify_playlist_id: snapshot_id}`` for all cached playlists of a user."""
        result = await session.execute(
            select(CachedPlaylist.spotify_playlist_id, CachedPlaylist.snapshot_id).where(
                CachedPlaylist.user_id == user_id
            )
        )
        return {row.spotify_playlist_id: row.snapshot_id or "" for row in result.all()}

    async def get_cached_playlist(
        self,
        user_id: int,
        playlist_id: str,
        session: AsyncSession,
    ) -> dict[str, Any] | None:
        """Return a single cached playlist with tracks, or ``None``."""
        result = await session.execute(
            select(CachedPlaylist).where(
                CachedPlaylist.user_id == user_id,
                CachedPlaylist.spotify_playlist_id == playlist_id,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None

        return await self._playlist_row_to_full_dict(row, session)

    async def put_playlist(
        self,
        user_id: int,
        playlist_data: dict[str, Any],
        tracks_data: list[dict[str, Any]],
        session: AsyncSession,
    ) -> None:
        """Upsert a playlist and its tracks into the cache."""
        spotify_id = playlist_data["id"]

        result = await session.execute(
            select(CachedPlaylist).where(
                CachedPlaylist.user_id == user_id,
                CachedPlaylist.spotify_playlist_id == spotify_id,
            )
        )
        existing = result.scalar_one_or_none()
        now = datetime.now(UTC)

        if existing is not None:
            existing.name = playlist_data.get("name", existing.name)
            existing.description = playlist_data.get("description")
            existing.owner_id = playlist_data.get("owner_id")
            existing.owner_display_name = playlist_data.get("owner")
            existing.public = playlist_data.get("public")
            existing.snapshot_id = playlist_data.get("snapshot_id")
            existing.total_tracks = playlist_data.get("tracks_total", 0)
            existing.external_url = (playlist_data.get("external_urls") or {}).get("spotify")
            existing.fetched_at = now
            playlist_row = existing

            # Delete old tracks before re-inserting
            await session.execute(
                delete(CachedPlaylistTrack).where(CachedPlaylistTrack.cached_playlist_id == existing.id)
            )
        else:
            playlist_row = CachedPlaylist(
                spotify_playlist_id=spotify_id,
                user_id=user_id,
                name=playlist_data.get("name", ""),
                description=playlist_data.get("description"),
                owner_id=playlist_data.get("owner_id"),
                owner_display_name=playlist_data.get("owner"),
                public=playlist_data.get("public"),
                snapshot_id=playlist_data.get("snapshot_id"),
                total_tracks=playlist_data.get("tracks_total", 0),
                external_url=(playlist_data.get("external_urls") or {}).get("spotify"),
                fetched_at=now,
            )
            session.add(playlist_row)
            await session.flush()

        # Insert track rows
        for i, track in enumerate(tracks_data):
            session.add(
                CachedPlaylistTrack(
                    cached_playlist_id=playlist_row.id,
                    spotify_track_id=track.get("id"),
                    track_name=track.get("name", ""),
                    artists_json=json.dumps(track.get("artists", [])),
                    added_at=track.get("added_at"),
                    position=i,
                )
            )
        await session.flush()

    async def put_playlist_list(
        self,
        user_id: int,
        playlists: list[dict[str, Any]],
        session: AsyncSession,
    ) -> None:
        """Cache a list of playlist summaries (from ``list_playlists``).

        Only stores metadata (no tracks). Tracks are fetched individually
        when ``get_playlist`` is called.
        """
        now = datetime.now(UTC)
        for pl_data in playlists:
            spotify_id = pl_data["id"]
            result = await session.execute(
                select(CachedPlaylist).where(
                    CachedPlaylist.user_id == user_id,
                    CachedPlaylist.spotify_playlist_id == spotify_id,
                )
            )
            existing = result.scalar_one_or_none()

            if existing is not None:
                existing.name = pl_data.get("name", existing.name)
                existing.public = pl_data.get("public")
                existing.total_tracks = pl_data.get("tracks_total")
                existing.owner_display_name = pl_data.get("owner")
                existing.snapshot_id = pl_data.get("snapshot_id")
                existing.fetched_at = now
            else:
                session.add(
                    CachedPlaylist(
                        spotify_playlist_id=spotify_id,
                        user_id=user_id,
                        name=pl_data.get("name", ""),
                        public=pl_data.get("public"),
                        total_tracks=pl_data.get("tracks_total"),
                        owner_display_name=pl_data.get("owner"),
                        snapshot_id=pl_data.get("snapshot_id"),
                        fetched_at=now,
                    )
                )
        await session.flush()

    async def invalidate_playlist(
        self,
        user_id: int,
        playlist_id: str,
        session: AsyncSession,
    ) -> None:
        """Remove a playlist from cache (e.g., after a write operation)."""
        result = await session.execute(
            select(CachedPlaylist).where(
                CachedPlaylist.user_id == user_id,
                CachedPlaylist.spotify_playlist_id == playlist_id,
            )
        )
        row = result.scalar_one_or_none()
        if row is not None:
            await session.delete(row)
            await session.flush()

    async def invalidate_all_playlists(
        self,
        user_id: int,
        session: AsyncSession,
    ) -> None:
        """Remove all cached playlists for a user."""
        await session.execute(delete(CachedPlaylist).where(CachedPlaylist.user_id == user_id))
        await session.flush()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _is_expired(self, fetched_at: datetime) -> bool:
        """Check whether a fetched_at timestamp has exceeded the TTL."""
        if fetched_at.tzinfo is None:
            # Defensive: treat naive as UTC (can happen in SQLite tests)
            fetched_at = fetched_at.replace(tzinfo=UTC)
        return datetime.now(UTC) - fetched_at > self._cache_ttl

    @staticmethod
    def _playlist_row_to_dict(row: CachedPlaylist) -> dict[str, Any]:
        """Convert a CachedPlaylist row to a summary dict."""
        return {
            "id": row.spotify_playlist_id,
            "name": row.name,
            "public": row.public,
            "tracks_total": row.total_tracks,
            "owner": row.owner_display_name,
            "snapshot_id": row.snapshot_id,
        }

    @staticmethod
    async def _playlist_row_to_full_dict(
        row: CachedPlaylist,
        session: AsyncSession,
    ) -> dict[str, Any]:
        """Convert a CachedPlaylist row + its tracks to a full dict."""
        result = await session.execute(
            select(CachedPlaylistTrack)
            .where(CachedPlaylistTrack.cached_playlist_id == row.id)
            .order_by(CachedPlaylistTrack.position)
        )
        track_rows = result.scalars().all()

        tracks = []
        for tr in track_rows:
            artists = json.loads(tr.artists_json) if tr.artists_json else []
            tracks.append(
                {
                    "id": tr.spotify_track_id,
                    "name": tr.track_name,
                    "artists": artists,
                    "added_at": tr.added_at,
                }
            )

        return {
            "id": row.spotify_playlist_id,
            "name": row.name,
            "description": row.description,
            "public": row.public,
            "owner": row.owner_display_name,
            "tracks_total": row.total_tracks,
            "tracks": tracks,
            "snapshot_id": row.snapshot_id,
            "external_urls": {"spotify": row.external_url} if row.external_url else {},
        }
