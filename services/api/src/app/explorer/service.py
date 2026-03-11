"""Explorer service — orchestrates queries for user-facing endpoints."""

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.tokens import TokenManager
from app.cache.service import SpotifyCacheService
from app.explorer.schemas import (
    ArtistSummary,
    DashboardData,
    MemoryPlaylistDetail,
    MemoryPlaylistEventItem,
    MemoryPlaylistSummary,
    MemoryPlaylistTrack,
    PaginatedHistory,
    PaginatedMemoryPlaylistEvents,
    PaginatedMemoryPlaylists,
    PaginatedPreferenceEvents,
    PlayHistoryItem,
    PlaylistDetail,
    PlaylistSummary,
    PlaylistTrackArtist,
    PlaylistTrackItem,
    PreferenceEventItem,
    TasteProfileResponse,
    TasteProfileWithEvents,
    TrackSummary,
    UserProfile,
)
from app.history.queries import HistoryQueries
from app.settings import get_settings
from shared.db.enums import PlaylistSnapshotSource
from shared.db.models.cache import CachedPlaylist, CachedPlaylistTrack
from shared.db.models.memory import MemoryPlaylist, PlaylistEvent, PlaylistSnapshot, PreferenceEvent, TasteProfile
from shared.db.models.music import Track
from shared.db.models.user import SpotifyToken, User
from shared.spotify.client import SpotifyClient
from shared.spotify.embed import SpotifyEmbedClient
from shared.spotify.exceptions import SpotifyEmbedError, SpotifyRequestError
from shared.spotify.models import SpotifyPlaylistSimplified, SpotifyPlaylistTrackItem

logger = logging.getLogger(__name__)


class ExplorerService:
    """Stateless service providing data for the explorer frontend."""

    # Playlist cache TTL — auto-refresh if older than this
    _PLAYLIST_CACHE_TTL: timedelta = timedelta(hours=1)
    # Spotify API page size for playlist listing (max allowed is 50)
    _PLAYLIST_FETCH_PAGE_SIZE: int = 50
    # Safety cap: stop fetching after this many playlists to avoid runaway pagination
    _PLAYLIST_FETCH_MAX: int = 500

    async def get_dashboard(self, user_id: int, session: AsyncSession) -> DashboardData:
        """Return all-time summary stats + 30-day top artists and top tracks."""
        # All-time stats for summary cards
        stats = await HistoryQueries.play_stats(user_id, session, days=99999)
        # 30-day top lists
        top_artists_raw = await HistoryQueries.top_artists(user_id, session, days=30, limit=5)
        top_tracks_raw = await HistoryQueries.top_tracks(user_id, session, days=30, limit=5)

        total_ms: int = stats["total_ms_played"]  # type: ignore[assignment]
        return DashboardData(
            total_plays=stats["total_plays"],
            listening_hours=round(total_ms / 3_600_000, 1),
            unique_tracks=stats["unique_tracks"],
            unique_artists=stats["unique_artists"],
            top_artists=[ArtistSummary(**r) for r in top_artists_raw],
            top_tracks=[TrackSummary(**r) for r in top_tracks_raw],
        )

    async def get_history(
        self,
        user_id: int,
        session: AsyncSession,
        limit: int = 50,
        offset: int = 0,
        q: str | None = None,
    ) -> PaginatedHistory:
        """Return paginated play history with optional text search."""
        rows, total = await HistoryQueries.recent_plays(user_id, session, limit=limit, offset=offset, q=q)
        return PaginatedHistory(
            items=[PlayHistoryItem(**r) for r in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

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

        Auto-fetches from Spotify if the cache is empty or older than 1 hour.
        """
        result = await session.execute(
            select(CachedPlaylist).where(CachedPlaylist.user_id == user_id).order_by(CachedPlaylist.name)
        )
        playlists: list[CachedPlaylist] = list(result.scalars().all())

        def _as_utc(dt: datetime) -> datetime:
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)

        cache_stale = not playlists or (
            datetime.now(UTC) - _as_utc(max(p.fetched_at for p in playlists)) > self._PLAYLIST_CACHE_TTL
        )
        if cache_stale:
            refreshed = await self._fetch_playlists_from_spotify(user_id, session)
            if refreshed is not None:
                playlists = refreshed

        return [self._playlist_to_summary(p) for p in playlists]

    async def refresh_playlists(self, user_id: int, session: AsyncSession) -> list[PlaylistSummary]:
        """Force-refresh playlists from Spotify API regardless of cache age."""
        refreshed = await self._fetch_playlists_from_spotify(user_id, session)
        if refreshed is None:
            # Spotify unavailable — return whatever is in the DB
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
            settings = get_settings()
            token_mgr = TokenManager(settings)
            access_token = await token_mgr.get_valid_token(user_id, session)

            async def _on_token_expired() -> str:
                return await token_mgr.refresh_access_token(user_id, session)

            client = SpotifyClient(access_token, on_token_expired=_on_token_expired)

            # Page through all playlists (Spotify max 50 per request, cap at _PLAYLIST_FETCH_MAX total)
            offset = 0
            all_items: list[SpotifyPlaylistSimplified] = []
            while offset < self._PLAYLIST_FETCH_MAX:
                response = await client.get_user_playlists(limit=self._PLAYLIST_FETCH_PAGE_SIZE, offset=offset)
                all_items.extend(response.items)
                if len(response.items) < self._PLAYLIST_FETCH_PAGE_SIZE or response.next is None:
                    break
                offset += self._PLAYLIST_FETCH_PAGE_SIZE

            now = datetime.now(UTC)
            for item in all_items:
                if not item.id:
                    continue
                existing_result = await session.execute(
                    select(CachedPlaylist).where(
                        CachedPlaylist.user_id == user_id,
                        CachedPlaylist.spotify_playlist_id == item.id,
                    )
                )
                existing = existing_result.scalar_one_or_none()
                total_tracks = (item.tracks or {}).get("total", 0)
                external_url = (item.external_urls or {}).get("spotify")
                owner_id = item.owner.id if item.owner else None
                owner_name = item.owner.display_name if item.owner else None

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

            await session.flush()

            # Re-query to return fresh sorted list
            result = await session.execute(
                select(CachedPlaylist).where(CachedPlaylist.user_id == user_id).order_by(CachedPlaylist.name)
            )
            return list(result.scalars().all())

        except Exception:
            logger.warning("Failed to fetch playlists from Spotify for user %d", user_id, exc_info=True)
            return None

    async def get_profile(self, user_id: int, session: AsyncSession) -> UserProfile:
        """Return user profile with all-time listening stats."""
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one()

        # Check if Spotify token exists
        token_result = await session.execute(select(SpotifyToken.id).where(SpotifyToken.user_id == user_id))
        has_token = token_result.scalar_one_or_none() is not None

        # All-time stats
        stats = await HistoryQueries.play_stats(user_id, session, days=99999)
        total_ms: int = stats["total_ms_played"]  # type: ignore[assignment]

        return UserProfile(
            user_id=user.id,
            spotify_user_id=user.spotify_user_id,
            display_name=user.display_name,
            email=user.email,
            country=user.country,
            product=user.product,
            created_at=user.created_at,
            has_spotify_token=has_token,
            total_plays=stats["total_plays"],
            unique_tracks=stats["unique_tracks"],
            unique_artists=stats["unique_artists"],
            listening_hours=round(total_ms / 3_600_000, 1),
        )

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
        # Verify playlist exists in cache
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

        # Fetch full playlist metadata
        pl = await client.get_playlist(spotify_playlist_id)

        # Fetch tracks with 403 → token-refresh → embed fallback chain
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

        # Build playlist data dict for cache
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

    # ── Taste profile ──────────────────────────────────────────────

    async def get_taste_profile(self, user_id: int, session: AsyncSession) -> TasteProfileWithEvents:
        """Return taste profile with the 10 most recent preference events."""
        profile = await session.get(TasteProfile, user_id)
        if profile is None:
            profile_resp = TasteProfileResponse(user_id=user_id, profile={}, version=0, updated_at=None)
        else:
            profile_resp = TasteProfileResponse(
                user_id=profile.user_id,
                profile=profile.profile_json,
                version=profile.version,
                updated_at=profile.updated_at.isoformat(),
            )

        # Recent preference events (newest first, limit 10)
        stmt = (
            select(PreferenceEvent)
            .where(PreferenceEvent.user_id == user_id)
            .order_by(desc(PreferenceEvent.timestamp))
            .limit(10)
        )
        result = await session.execute(stmt)
        events = [
            PreferenceEventItem(
                event_id=str(e.event_id),
                timestamp=e.timestamp.isoformat(),
                source=e.source,
                type=e.type,
                payload=e.payload_json,
            )
            for e in result.scalars().all()
        ]

        return TasteProfileWithEvents(profile=profile_resp, recent_events=events)

    async def update_taste_profile(
        self, user_id: int, patch: dict[str, object], reason: str | None, session: AsyncSession
    ) -> TasteProfileResponse:
        """Apply a JSON merge-patch to the taste profile, creating it if needed."""
        profile = await session.get(TasteProfile, user_id)
        if profile is None:
            profile = TasteProfile(user_id=user_id, profile_json=patch, version=1)
            session.add(profile)
        else:
            profile.profile_json = {**profile.profile_json, **patch}
            profile.version += 1

        if reason:
            event = PreferenceEvent(
                event_id=uuid.uuid4(),
                user_id=user_id,
                source="user",
                type="note",
                payload_json={"action": "profile_update", "reason": reason, "patch_keys": list(patch.keys())},
            )
            session.add(event)

        await session.flush()

        return TasteProfileResponse(
            user_id=profile.user_id,
            profile=profile.profile_json,
            version=profile.version,
            updated_at=profile.updated_at.isoformat(),
        )

    async def clear_taste_profile(self, user_id: int, session: AsyncSession) -> None:
        """Delete the user's taste profile row, resetting it to version 0."""
        await session.execute(delete(TasteProfile).where(TasteProfile.user_id == user_id))
        await session.flush()

    async def get_preference_events(
        self, user_id: int, session: AsyncSession, limit: int = 20, offset: int = 0
    ) -> PaginatedPreferenceEvents:
        """Return paginated preference events, newest first."""
        # Count total
        count_stmt = select(func.count()).select_from(PreferenceEvent).where(PreferenceEvent.user_id == user_id)
        total = (await session.execute(count_stmt)).scalar_one()

        # Fetch page
        stmt = (
            select(PreferenceEvent)
            .where(PreferenceEvent.user_id == user_id)
            .order_by(desc(PreferenceEvent.timestamp))
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        items = [
            PreferenceEventItem(
                event_id=str(e.event_id),
                timestamp=e.timestamp.isoformat(),
                source=e.source,
                type=e.type,
                payload=e.payload_json,
            )
            for e in result.scalars().all()
        ]

        return PaginatedPreferenceEvents(items=items, total=total, limit=limit, offset=offset)

    # ── Memory playlists ──────────────────────────────────────────

    @staticmethod
    def _is_ai_created(pl: MemoryPlaylist, snapshot: PlaylistSnapshot | None) -> bool:
        """Check whether a memory playlist was AI-created (vs backfilled/imported).

        A playlist is considered AI-created when ``created_by`` is absent
        (legacy records) or equals ``"assistant"``.
        """
        # Backfill snapshot source → not AI
        if snapshot is not None and snapshot.source == PlaylistSnapshotSource.BACKFILL:
            return False
        # Check seed_context for origin.created_by
        ctx = pl.seed_context if isinstance(pl.seed_context, dict) else {}
        origin = ctx.get("origin")
        if isinstance(origin, dict):
            created_by = origin.get("created_by")
            if isinstance(created_by, str) and created_by != "assistant":
                return False
        # Flat created_by at top level
        created_by_top = ctx.get("created_by")
        if isinstance(created_by_top, str) and created_by_top != "assistant":
            return False
        return True

    async def get_memory_playlists(
        self, user_id: int, session: AsyncSession, limit: int = 20, offset: int = 0
    ) -> PaginatedMemoryPlaylists:
        """Return paginated AI-created memory playlists (excludes backfilled/imported ones)."""
        # Fetch all memory playlists for the user (typically a small set)
        stmt = (
            select(MemoryPlaylist)
            .where(MemoryPlaylist.user_id == user_id)
            .order_by(desc(MemoryPlaylist.updated_at), desc(MemoryPlaylist.playlist_id))
        )
        result = await session.execute(stmt)
        all_playlists = result.scalars().all()

        # Batch-load snapshots
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

        # Filter to AI-created only and build items
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

        # Resolve track IDs to names/artists from cached_playlist_tracks or tracks table
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

        # 1) Try cached_playlist_tracks (best source — has artists_json)
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

        # 2) For remaining IDs, try the tracks table
        missing_ids = [tid for tid in track_ids if tid not in cache_by_id]
        tracks_by_id: dict[str, Track] = {}
        if missing_ids:
            tracks_stmt = select(Track).where(Track.spotify_track_id.in_(missing_ids))
            tracks_result = await session.execute(tracks_stmt)
            for t in tracks_result.scalars():
                if t.spotify_track_id:
                    tracks_by_id[t.spotify_track_id] = t

        # 3) Build resolved list preserving original order
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
