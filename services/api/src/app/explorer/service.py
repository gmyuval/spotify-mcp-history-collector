"""Explorer service — orchestrates queries for user-facing endpoints."""

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.exceptions import TokenNotFoundError, TokenRefreshError
from app.auth.tokens import TokenManager
from app.cache.service import SpotifyCacheService
from app.explorer.enrichment_cache import cache as enrichment_cache
from app.explorer.schemas import (
    AlbumDetail,
    AlbumTrackItem,
    ArtistBrowserItem,
    ArtistDetail,
    ArtistSummary,
    AudioFeaturesData,
    DashboardData,
    MemoryPlaylistDetail,
    MemoryPlaylistEventItem,
    MemoryPlaylistSummary,
    MemoryPlaylistTrack,
    PaginatedArtists,
    PaginatedHistory,
    PaginatedMemoryPlaylistEvents,
    PaginatedMemoryPlaylists,
    PaginatedPreferenceEvents,
    PaginatedTracks,
    PlayHistoryItem,
    PlaylistDetail,
    PlaylistSummary,
    PlaylistTrackArtist,
    PlaylistTrackItem,
    PreferenceEventItem,
    RecentPlayItem,
    SpotifyAlbumEnrichment,
    SpotifyArtistEnrichment,
    SpotifyImage,
    SpotifyTrackEnrichment,
    TasteProfileResponse,
    TasteProfileWithEvents,
    TrackArtistRef,
    TrackBrowserItem,
    TrackDetail,
    TrackDetailArtist,
    TrackSummary,
    UserProfile,
)
from app.history.queries import HistoryQueries
from app.settings import get_settings
from shared.db.enums import PlaylistSnapshotSource
from shared.db.models.cache import CachedPlaylist, CachedPlaylistTrack
from shared.db.models.memory import MemoryPlaylist, PlaylistEvent, PlaylistSnapshot, PreferenceEvent, TasteProfile
from shared.db.models.music import Artist, Play, Track, TrackArtist
from shared.db.models.user import SpotifyToken, User
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


class ExplorerService:
    """Stateless service providing data for the explorer frontend."""

    # Playlist cache TTL — auto-refresh if older than this
    _PLAYLIST_CACHE_TTL: timedelta = timedelta(hours=1)
    # Spotify API page size for playlist listing (max allowed is 50)
    _PLAYLIST_FETCH_PAGE_SIZE: int = 50
    # Safety cap: stop fetching after this many playlists to avoid runaway pagination
    _PLAYLIST_FETCH_MAX: int = 500

    async def get_dashboard(self, user_id: int, session: AsyncSession, days: int = 30) -> DashboardData:
        """Return all-time summary stats + top artists and top tracks for the given window."""
        # All-time stats for summary cards
        stats = await HistoryQueries.play_stats(user_id, session, days=99999)
        # Top lists for the selected time window
        top_artists_raw = await HistoryQueries.top_artists(user_id, session, days=days, limit=10)
        top_tracks_raw = await HistoryQueries.top_tracks(user_id, session, days=days, limit=10)

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

    async def get_tracks(
        self,
        user_id: int,
        session: AsyncSession,
        limit: int = 50,
        offset: int = 0,
        sort: str = "play_count",
        q: str | None = None,
        days: int | None = None,
    ) -> PaginatedTracks:
        """Return paginated track browser with optional search, sort, and time window."""
        rows, total = await HistoryQueries.tracks_list(
            user_id, session, limit=limit, offset=offset, sort=sort, q=q, days=days
        )
        return PaginatedTracks(
            items=[TrackBrowserItem(**r) for r in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_artists(
        self,
        user_id: int,
        session: AsyncSession,
        limit: int = 50,
        offset: int = 0,
        sort: str = "play_count",
        q: str | None = None,
        days: int | None = None,
    ) -> PaginatedArtists:
        """Return paginated artist browser with optional search, sort, and time window."""
        rows, total = await HistoryQueries.artists_list(
            user_id, session, limit=limit, offset=offset, sort=sort, q=q, days=days
        )
        return PaginatedArtists(
            items=[ArtistBrowserItem(**r) for r in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    # ── Entity detail ────────────────────────────────────────────

    async def get_track_detail(self, user_id: int, track_id: int, session: AsyncSession) -> TrackDetail | None:
        """Return detailed track info with play stats, audio features, and recent plays."""
        # User-scoped: only return tracks that the user has actually played
        stats_result = await session.execute(
            select(
                func.count(),
                func.min(Play.played_at),
                func.max(Play.played_at),
                func.coalesce(func.sum(Play.ms_played), 0),
            ).where(Play.user_id == user_id, Play.track_id == track_id)
        )
        play_count, first_played, last_played, total_ms = stats_result.one()

        if play_count == 0:
            return None

        result = await session.execute(
            select(Track)
            .where(Track.id == track_id)
            .options(selectinload(Track.artists), selectinload(Track.audio_features))
        )
        track = result.scalar_one_or_none()
        if track is None:
            return None

        # Recent plays (limit 20)
        recent_result = await session.execute(
            select(Play.played_at, Play.ms_played, Play.context_type)
            .where(Play.user_id == user_id, Play.track_id == track_id)
            .order_by(desc(Play.played_at))
            .limit(20)
        )
        recent_plays = [
            RecentPlayItem(played_at=row.played_at, ms_played=row.ms_played, context_type=row.context_type)
            for row in recent_result.all()
        ]

        # Audio features
        audio_features: AudioFeaturesData | None = None
        if track.audio_features is not None:
            af = track.audio_features
            audio_features = AudioFeaturesData(
                danceability=af.danceability,
                energy=af.energy,
                valence=af.valence,
                acousticness=af.acousticness,
                instrumentalness=af.instrumentalness,
                speechiness=af.speechiness,
                tempo=af.tempo,
                loudness=af.loudness,
                key=af.key,
                mode=af.mode,
                time_signature=af.time_signature,
                liveness=af.liveness,
            )

        # Artists
        artists = [TrackArtistRef(artist_id=a.id, name=a.name) for a in track.artists]

        # Spotify enrichment (optional, non-blocking)
        spotify_enrichment: SpotifyTrackEnrichment | None = None
        if track.spotify_track_id:
            spotify_enrichment = await self._enrich_track_spotify(track.spotify_track_id, user_id, session)

        return TrackDetail(
            track_id=track.id,
            name=track.name,
            spotify_track_id=track.spotify_track_id,
            duration_ms=track.duration_ms,
            album_name=track.album_name,
            album_spotify_id=track.album_spotify_id,
            artists=artists,
            play_count=play_count,
            first_played=first_played,
            last_played=last_played,
            total_ms_played=total_ms,
            audio_features=audio_features,
            recent_plays=recent_plays,
            spotify=spotify_enrichment,
        )

    async def get_artist_detail(self, user_id: int, artist_id: int, session: AsyncSession) -> ArtistDetail | None:
        """Return detailed artist info with play stats and top tracks."""
        # User-scoped: verify the user has plays for this artist before loading
        stats_result = await session.execute(
            select(
                func.count(),
                func.count(func.distinct(Play.track_id)),
                func.coalesce(func.sum(Play.ms_played), 0),
                func.min(Play.played_at),
                func.max(Play.played_at),
            )
            .select_from(Play)
            .join(TrackArtist, TrackArtist.track_id == Play.track_id)
            .where(Play.user_id == user_id, TrackArtist.artist_id == artist_id)
        )
        play_count, unique_tracks, total_ms, first_played, last_played = stats_result.one()

        if play_count == 0:
            return None

        result = await session.execute(select(Artist).where(Artist.id == artist_id))
        artist = result.scalar_one_or_none()
        if artist is None:
            return None

        # Top tracks by play count (limit 20)
        top_tracks_result = await session.execute(
            select(
                Track.id.label("track_id"),
                Track.name.label("name"),
                func.count().label("play_count"),
            )
            .select_from(Play)
            .join(Track, Track.id == Play.track_id)
            .join(TrackArtist, TrackArtist.track_id == Play.track_id)
            .where(Play.user_id == user_id, TrackArtist.artist_id == artist_id)
            .group_by(Track.id, Track.name)
            .order_by(desc(func.count()))
            .limit(20)
        )
        top_tracks = [
            TrackDetailArtist(track_id=row.track_id, name=row.name, play_count=row.play_count)
            for row in top_tracks_result.all()
        ]

        # Spotify enrichment (optional, non-blocking)
        spotify_enrichment: SpotifyArtistEnrichment | None = None
        if artist.spotify_artist_id:
            spotify_enrichment = await self._enrich_artist_spotify(artist.spotify_artist_id, user_id, session)

        return ArtistDetail(
            artist_id=artist.id,
            name=artist.name,
            spotify_artist_id=artist.spotify_artist_id,
            play_count=play_count,
            unique_tracks=unique_tracks,
            total_ms_played=total_ms,
            first_played=first_played,
            last_played=last_played,
            top_tracks=top_tracks,
            spotify=spotify_enrichment,
        )

    async def get_album_detail(self, user_id: int, album_spotify_id: str, session: AsyncSession) -> AlbumDetail | None:
        """Return album detail with per-track play stats."""
        # User-scoped: only return albums where the user has played at least one track
        user_track_ids_result = await session.execute(
            select(func.distinct(Play.track_id))
            .join(Track, Track.id == Play.track_id)
            .where(Play.user_id == user_id, Track.album_spotify_id == album_spotify_id)
        )
        user_played_track_ids = set(user_track_ids_result.scalars().all())
        if not user_played_track_ids:
            return None

        # Find all tracks with this album_spotify_id
        tracks_result = await session.execute(
            select(Track).where(Track.album_spotify_id == album_spotify_id).options(selectinload(Track.artists))
        )
        tracks = list(tracks_result.scalars().all())

        album_name = tracks[0].album_name or ""
        # Collect unique artist names from all tracks
        artist_name_set: set[str] = set()
        for t in tracks:
            for a in t.artists:
                artist_name_set.add(a.name)

        track_ids = [t.id for t in tracks]

        # Per-track play counts for this user
        play_counts_result = await session.execute(
            select(Play.track_id, func.count().label("play_count"))
            .where(Play.user_id == user_id, Play.track_id.in_(track_ids))
            .group_by(Play.track_id)
        )
        play_counts: dict[int, int] = {row.track_id: row.play_count for row in play_counts_result.all()}

        album_tracks = [
            AlbumTrackItem(
                track_id=t.id,
                name=t.name,
                play_count=play_counts.get(t.id, 0),
                duration_ms=t.duration_ms,
            )
            for t in tracks
        ]

        total_play_count = sum(item.play_count for item in album_tracks)
        unique_track_count = sum(1 for item in album_tracks if item.play_count > 0)

        # Spotify enrichment (optional, non-blocking)
        spotify_enrichment: SpotifyAlbumEnrichment | None = None
        spotify_enrichment = await self._enrich_album_spotify(album_spotify_id, user_id, session)

        return AlbumDetail(
            album_spotify_id=album_spotify_id,
            name=album_name,
            artist_names=sorted(artist_name_set),
            play_count=total_play_count,
            unique_tracks=unique_track_count,
            tracks=album_tracks,
            spotify=spotify_enrichment,
        )

    # ── Spotify enrichment helpers ─────────────────────────────

    async def _get_spotify_client(self, user_id: int, session: AsyncSession) -> SpotifyClient:
        """Create a SpotifyClient with token management for the given user."""
        settings = get_settings()
        token_mgr = TokenManager(settings)
        access_token = await token_mgr.get_valid_token(user_id, session)

        async def _on_token_expired() -> str:
            return await token_mgr.refresh_access_token(user_id, session)

        return SpotifyClient(access_token, on_token_expired=_on_token_expired)

    async def _enrich_track_spotify(
        self, spotify_track_id: str, user_id: int, session: AsyncSession
    ) -> SpotifyTrackEnrichment | None:
        """Fetch track enrichment from Spotify API with caching."""
        cache_key = f"track:{spotify_track_id}"
        cached: SpotifyTrackEnrichment | None = enrichment_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            client = await self._get_spotify_client(user_id, session)
            sp_track = await client.get_track(spotify_track_id)
            images = []
            if sp_track.album and sp_track.album.images:
                images = [
                    SpotifyImage(url=img.url, height=img.height, width=img.width) for img in sp_track.album.images
                ]
            result = SpotifyTrackEnrichment(
                images=images,
                popularity=sp_track.popularity,
                isrc=sp_track.external_ids.isrc if sp_track.external_ids else None,
                preview_url=sp_track.preview_url,
                external_url=sp_track.external_urls.get("spotify") if sp_track.external_urls else None,
            )
            enrichment_cache.put(cache_key, result)
            return result
        except (TokenNotFoundError, TokenRefreshError, httpx.HTTPError) as exc:
            logger.debug("Spotify enrichment failed for track %s: %s", spotify_track_id, exc)
            return None

    async def _enrich_artist_spotify(
        self, spotify_artist_id: str, user_id: int, session: AsyncSession
    ) -> SpotifyArtistEnrichment | None:
        """Fetch artist enrichment from Spotify API with caching."""
        cache_key = f"artist:{spotify_artist_id}"
        cached: SpotifyArtistEnrichment | None = enrichment_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            client = await self._get_spotify_client(user_id, session)
            sp_artist = await client.get_artist(spotify_artist_id)
            images = []
            if sp_artist.images:
                images = [SpotifyImage(url=img.url, height=img.height, width=img.width) for img in sp_artist.images]
            followers_total = None
            if sp_artist.followers and isinstance(sp_artist.followers, dict):
                followers_total = sp_artist.followers.get("total")
            result = SpotifyArtistEnrichment(
                images=images,
                genres=sp_artist.genres,
                popularity=sp_artist.popularity,
                followers=followers_total,
                external_url=sp_artist.external_urls.get("spotify") if sp_artist.external_urls else None,
            )
            enrichment_cache.put(cache_key, result)
            return result
        except (TokenNotFoundError, TokenRefreshError, httpx.HTTPError) as exc:
            logger.debug("Spotify enrichment failed for artist %s: %s", spotify_artist_id, exc)
            return None

    async def _enrich_album_spotify(
        self, album_spotify_id: str, user_id: int, session: AsyncSession
    ) -> SpotifyAlbumEnrichment | None:
        """Fetch album enrichment from Spotify API with caching."""
        cache_key = f"album:{album_spotify_id}"
        cached: SpotifyAlbumEnrichment | None = enrichment_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            client = await self._get_spotify_client(user_id, session)
            sp_album = await client.get_album(album_spotify_id)
            images = []
            if sp_album.images:
                images = [SpotifyImage(url=img.url, height=img.height, width=img.width) for img in sp_album.images]
            result = SpotifyAlbumEnrichment(
                images=images,
                release_date=sp_album.release_date,
                label=sp_album.label,
                total_tracks=sp_album.total_tracks,
                external_url=sp_album.external_urls.get("spotify") if sp_album.external_urls else None,
            )
            enrichment_cache.put(cache_key, result)
            return result
        except (TokenNotFoundError, TokenRefreshError, httpx.HTTPError) as exc:
            logger.debug("Spotify enrichment failed for album %s: %s", album_spotify_id, exc)
            return None

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

            # Preload all existing rows in one query to avoid N+1 selects
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

            # Remove playlists the user unfollowed / that disappeared from Spotify
            stale_stmt = delete(CachedPlaylist).where(CachedPlaylist.user_id == user_id)
            if fetched_ids:
                stale_stmt = stale_stmt.where(~CachedPlaylist.spotify_playlist_id.in_(fetched_ids))
            await session.execute(stale_stmt)

            await session.flush()

            # Re-query to return fresh sorted list
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
