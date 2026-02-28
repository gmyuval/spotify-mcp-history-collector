"""Explorer service — orchestrates queries for user-facing endpoints."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.explorer.schemas import (
    ArtistSummary,
    DashboardData,
    PaginatedHistory,
    PlayHistoryItem,
    PlaylistDetail,
    PlaylistSummary,
    PlaylistTrackItem,
    TrackSummary,
    UserProfile,
)
from app.history.queries import HistoryQueries
from shared.db.models.cache import CachedPlaylist
from shared.db.models.user import SpotifyToken, User


class ExplorerService:
    """Stateless service providing data for the explorer frontend."""

    async def get_dashboard(self, user_id: int, session: AsyncSession) -> DashboardData:
        stats = await HistoryQueries.play_stats(user_id, session, days=30)
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
        rows, total = await HistoryQueries.recent_plays(user_id, session, limit=limit, offset=offset, q=q)
        return PaginatedHistory(
            items=[PlayHistoryItem(**r) for r in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_playlists(self, user_id: int, session: AsyncSession) -> list[PlaylistSummary]:
        result = await session.execute(
            select(CachedPlaylist).where(CachedPlaylist.user_id == user_id).order_by(CachedPlaylist.name)
        )
        playlists = result.scalars().all()
        return [
            PlaylistSummary(
                id=p.id,
                spotify_playlist_id=p.spotify_playlist_id,
                name=p.name or "",
                description=p.description,
                total_tracks=p.total_tracks or 0,
                owner_display_name=p.owner_display_name,
                external_url=p.external_url,
            )
            for p in playlists
        ]

    async def get_profile(self, user_id: int, session: AsyncSession) -> UserProfile:
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
                    artists_json=t.artists_json,
                    added_at=t.added_at,
                )
                for t in sorted(playlist.tracks, key=lambda t: t.position)
            ],
        )
