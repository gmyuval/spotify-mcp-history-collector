"""Memory playlists browsing, detail, and event history."""

import json
import logging
import uuid

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.explorer.schemas import (
    MemoryPlaylistDetail,
    MemoryPlaylistEventItem,
    MemoryPlaylistSummary,
    MemoryPlaylistTrack,
    PaginatedMemoryPlaylistEvents,
    PaginatedMemoryPlaylists,
    PlaylistTrackArtist,
)
from app.explorer.services._base import BaseExplorerService
from shared.db.enums import PlaylistSnapshotSource
from shared.db.models.cache import CachedPlaylist, CachedPlaylistTrack
from shared.db.models.memory import MemoryPlaylist, PlaylistEvent, PlaylistSnapshot
from shared.db.models.music import Track

logger = logging.getLogger(__name__)


class MemoryService(BaseExplorerService):
    """Manages AI-created memory playlists and their event history."""

    @staticmethod
    def _is_ai_created(pl: MemoryPlaylist, snapshot: PlaylistSnapshot | None) -> bool:
        """Check whether a memory playlist was AI-created (vs backfilled/imported).

        A playlist is considered AI-created when ``created_by`` is absent
        (legacy records) or equals ``"assistant"``.
        """
        if snapshot is not None and snapshot.source == PlaylistSnapshotSource.BACKFILL:
            return False
        ctx = pl.seed_context if isinstance(pl.seed_context, dict) else {}
        origin = ctx.get("origin")
        if isinstance(origin, dict):
            created_by = origin.get("created_by")
            if isinstance(created_by, str) and created_by != "assistant":
                return False
        created_by_top = ctx.get("created_by")
        if isinstance(created_by_top, str) and created_by_top != "assistant":
            return False
        return True

    async def get_memory_playlists(
        self, user_id: int, session: AsyncSession, limit: int = 20, offset: int = 0
    ) -> PaginatedMemoryPlaylists:
        """Return paginated AI-created memory playlists (excludes backfilled/imported ones)."""
        stmt = (
            select(MemoryPlaylist)
            .where(MemoryPlaylist.user_id == user_id)
            .order_by(desc(MemoryPlaylist.updated_at), desc(MemoryPlaylist.playlist_id))
        )
        result = await session.execute(stmt)
        all_playlists = result.scalars().all()

        snapshot_ids = [pl.latest_snapshot_id for pl in all_playlists if pl.latest_snapshot_id is not None]
        snapshots_by_key: dict[tuple[uuid.UUID, str], PlaylistSnapshot] = {}
        if snapshot_ids:
            playlist_ids = [pl.playlist_id for pl in all_playlists]
            snap_stmt = select(PlaylistSnapshot).where(
                PlaylistSnapshot.snapshot_id.in_(snapshot_ids),
                PlaylistSnapshot.playlist_id.in_(playlist_ids),
            )
            snap_result = await session.execute(snap_stmt)
            for snap in snap_result.scalars():
                snapshots_by_key[(snap.snapshot_id, snap.playlist_id)] = snap

        filtered: list[tuple[MemoryPlaylist, int]] = []
        for pl in all_playlists:
            pl_snap = snapshots_by_key.get((pl.latest_snapshot_id, pl.playlist_id)) if pl.latest_snapshot_id else None
            if not self._is_ai_created(pl, pl_snap):
                continue
            track_count = len(pl_snap.track_ids) if pl_snap else 0
            filtered.append((pl, track_count))

        total = len(filtered)
        page = filtered[offset : offset + limit]
        items = [
            MemoryPlaylistSummary(
                playlist_id=pl.playlist_id,
                name=pl.name,
                description=pl.description,
                created_at=pl.created_at.isoformat(),
                updated_at=pl.updated_at.isoformat(),
                intent_tags=pl.intent_tags,
                track_count=track_count,
            )
            for pl, track_count in page
        ]

        return PaginatedMemoryPlaylists(items=items, total=total, limit=limit, offset=offset)

    async def get_memory_playlist_detail(
        self, user_id: int, playlist_id: str, session: AsyncSession
    ) -> MemoryPlaylistDetail | None:
        """Return a single memory playlist with resolved track metadata and recent events."""
        pl = await session.get(MemoryPlaylist, playlist_id)
        if pl is None or pl.user_id != user_id:
            return None

        track_ids: list[str] = []
        if pl.latest_snapshot_id is not None:
            snap = await session.get(PlaylistSnapshot, pl.latest_snapshot_id)
            if snap is not None and snap.playlist_id == playlist_id:
                track_ids = [str(t) for t in snap.track_ids]

        tracks = await self._resolve_track_ids(track_ids, user_id, session)

        count_stmt = (
            select(func.count())
            .select_from(PlaylistEvent)
            .where(PlaylistEvent.playlist_id == playlist_id, PlaylistEvent.user_id == user_id)
        )
        total_events = (await session.execute(count_stmt)).scalar_one()

        events_stmt = (
            select(PlaylistEvent)
            .where(PlaylistEvent.playlist_id == playlist_id, PlaylistEvent.user_id == user_id)
            .order_by(desc(PlaylistEvent.timestamp), desc(PlaylistEvent.event_id))
            .limit(20)
        )
        result = await session.execute(events_stmt)
        events = [
            MemoryPlaylistEventItem(
                event_id=str(e.event_id),
                timestamp=e.timestamp.isoformat(),
                type=e.type,
                payload=e.payload_json,
            )
            for e in result.scalars().all()
        ]

        return MemoryPlaylistDetail(
            playlist_id=pl.playlist_id,
            name=pl.name,
            description=pl.description,
            created_at=pl.created_at.isoformat(),
            updated_at=pl.updated_at.isoformat(),
            intent_tags=pl.intent_tags,
            seed_context=pl.seed_context,
            tracks=tracks,
            recent_events=events,
            total_events=total_events,
        )

    async def _resolve_track_ids(
        self, track_ids: list[str], user_id: int, session: AsyncSession
    ) -> list[MemoryPlaylistTrack]:
        """Resolve Spotify track IDs to names/artists using cache or tracks table."""
        if not track_ids:
            return []

        cache_stmt = select(CachedPlaylistTrack).where(
            CachedPlaylistTrack.spotify_track_id.in_(track_ids),
            CachedPlaylistTrack.cached_playlist_id.in_(
                select(CachedPlaylist.id).where(CachedPlaylist.user_id == user_id)
            ),
        )
        cache_result = await session.execute(cache_stmt)
        cache_by_id: dict[str, CachedPlaylistTrack] = {}
        for ct in cache_result.scalars():
            if ct.spotify_track_id and ct.spotify_track_id not in cache_by_id:
                cache_by_id[ct.spotify_track_id] = ct

        missing_ids = [tid for tid in track_ids if tid not in cache_by_id]
        tracks_by_id: dict[str, Track] = {}
        if missing_ids:
            tracks_stmt = select(Track).where(Track.spotify_track_id.in_(missing_ids))
            tracks_result = await session.execute(tracks_stmt)
            for t in tracks_result.scalars():
                if t.spotify_track_id:
                    tracks_by_id[t.spotify_track_id] = t

        resolved: list[MemoryPlaylistTrack] = []
        for tid in track_ids:
            if tid in cache_by_id:
                ct = cache_by_id[tid]
                artists = []
                if ct.artists_json:
                    try:
                        artists = [PlaylistTrackArtist(**a) for a in json.loads(ct.artists_json)]
                    except json.JSONDecodeError, TypeError:
                        pass
                resolved.append(MemoryPlaylistTrack(spotify_track_id=tid, track_name=ct.track_name, artists=artists))
            elif tid in tracks_by_id:
                t = tracks_by_id[tid]
                resolved.append(MemoryPlaylistTrack(spotify_track_id=tid, track_name=t.name))
            else:
                resolved.append(MemoryPlaylistTrack(spotify_track_id=tid))
        return resolved

    async def get_memory_playlist_events(
        self,
        user_id: int,
        playlist_id: str,
        session: AsyncSession,
        limit: int = 20,
        offset: int = 0,
    ) -> PaginatedMemoryPlaylistEvents | None:
        """Return paginated events for a memory playlist, or None if not found."""
        pl = await session.get(MemoryPlaylist, playlist_id)
        if pl is None or pl.user_id != user_id:
            return None

        count_stmt = (
            select(func.count())
            .select_from(PlaylistEvent)
            .where(PlaylistEvent.playlist_id == playlist_id, PlaylistEvent.user_id == user_id)
        )
        total = (await session.execute(count_stmt)).scalar_one()

        stmt = (
            select(PlaylistEvent)
            .where(PlaylistEvent.playlist_id == playlist_id, PlaylistEvent.user_id == user_id)
            .order_by(desc(PlaylistEvent.timestamp), desc(PlaylistEvent.event_id))
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        items = [
            MemoryPlaylistEventItem(
                event_id=str(e.event_id),
                timestamp=e.timestamp.isoformat(),
                type=e.type,
                payload=e.payload_json,
            )
            for e in result.scalars().all()
        ]

        return PaginatedMemoryPlaylistEvents(items=items, total=total, limit=limit, offset=offset)
