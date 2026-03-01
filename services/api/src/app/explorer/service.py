"""Explorer service — orchestrates queries for user-facing endpoints."""

import uuid

from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.explorer.schemas import (
    ArtistSummary,
    DashboardData,
    PaginatedHistory,
    PaginatedPreferenceEvents,
    PlayHistoryItem,
    PlaylistDetail,
    PlaylistSummary,
    PlaylistTrackItem,
    PreferenceEventItem,
    TasteProfileResponse,
    TasteProfileWithEvents,
    TrackSummary,
    UserProfile,
)
from app.history.queries import HistoryQueries
from shared.db.models.cache import CachedPlaylist
from shared.db.models.memory import PreferenceEvent, TasteProfile
from shared.db.models.user import SpotifyToken, User


class ExplorerService:
    """Stateless service providing data for the explorer frontend."""

    async def get_dashboard(self, user_id: int, session: AsyncSession) -> DashboardData:
        """Return 30-day dashboard stats: play counts, top artists, and top tracks."""
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
        """Return paginated play history with optional text search."""
        rows, total = await HistoryQueries.recent_plays(user_id, session, limit=limit, offset=offset, q=q)
        return PaginatedHistory(
            items=[PlayHistoryItem(**r) for r in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_playlists(self, user_id: int, session: AsyncSession) -> list[PlaylistSummary]:
        """Return all cached playlists for the user, ordered by name."""
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
                    artists_json=t.artists_json,
                    added_at=t.added_at,
                )
                for t in sorted(playlist.tracks, key=lambda t: t.position)
            ],
        )

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
