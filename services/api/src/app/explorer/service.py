"""Explorer service — analytics, browsing, and profile queries."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.explorer.schemas import (
    ArtistBrowserItem,
    ArtistSummary,
    DashboardData,
    DiscoveryData,
    DiscoveryDay,
    GenreData,
    GenreItem,
    HeatmapCell,
    HeatmapData,
    PaginatedArtists,
    PaginatedHistory,
    PaginatedTracks,
    PlayHistoryItem,
    TimelineBucket,
    TimelineData,
    TrackBrowserItem,
    TrackSummary,
    UserProfile,
)
from app.history.queries import HistoryQueries
from shared.db.models.user import SpotifyToken, User


class ExplorerService:
    """Stateless service providing analytics, browsing, and profile data."""

    # ── Analytics ────────────────────────────────────────────────

    async def get_dashboard(self, user_id: int, session: AsyncSession, days: int = 30) -> DashboardData:
        """Return all-time summary stats + top artists and top tracks for the given window."""
        stats = await HistoryQueries.play_stats(user_id, session, days=99999)
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

    async def get_heatmap(self, user_id: int, session: AsyncSession, days: int = 90) -> HeatmapData:
        """Return weekday x hour heatmap data."""
        rows = await HistoryQueries.heatmap(user_id, session, days=days)
        return HeatmapData(cells=[HeatmapCell(**r) for r in rows])

    async def get_timeline(
        self, user_id: int, session: AsyncSession, days: int = 90, bucket: str = "week"
    ) -> TimelineData:
        """Return plays aggregated by time bucket."""
        rows = await HistoryQueries.timeline(user_id, session, days=days, bucket=bucket)
        return TimelineData(
            buckets=[TimelineBucket(**r) for r in rows],
            bucket_size=bucket,
        )

    async def get_genres(self, user_id: int, session: AsyncSession, days: int = 90) -> GenreData:
        """Return genre distribution by play count."""
        rows = await HistoryQueries.genre_distribution(user_id, session, days=days)
        return GenreData(genres=[GenreItem(**r) for r in rows])

    async def get_discovery(self, user_id: int, session: AsyncSession, days: int = 90) -> DiscoveryData:
        """Return daily new vs repeat track play counts."""
        rows = await HistoryQueries.discovery_rate(user_id, session, days=days)
        return DiscoveryData(days=[DiscoveryDay(**r) for r in rows])

    # ── Browsing ─────────────────────────────────────────────────

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

    # ── Profile ──────────────────────────────────────────────────

    async def get_profile(self, user_id: int, session: AsyncSession) -> UserProfile:
        """Return user profile with all-time listening stats."""
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one()

        token_result = await session.execute(select(SpotifyToken.id).where(SpotifyToken.user_id == user_id))
        has_token = token_result.scalar_one_or_none() is not None

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
