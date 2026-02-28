"""User-facing explorer API endpoints — JWT-gated, own data only."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.auth import require_permission
from app.dependencies import db_manager
from app.explorer.schemas import (
    DashboardData,
    PaginatedHistory,
    PlaylistDetail,
    PlaylistSummary,
    TrackSummary,
    UserProfile,
)
from app.explorer.service import ExplorerService
from app.history.schemas import ArtistCount
from app.history.service import HistoryService

RequireOwnDataView = Annotated[int, Depends(require_permission("own_data.view"))]
DBSession = Annotated[AsyncSession, Depends(db_manager.dependency)]


class ExplorerRouter:
    """User-facing API endpoints for the explorer frontend."""

    def __init__(self) -> None:
        self._service = ExplorerService()
        self._history_service = HistoryService()
        self.router = APIRouter()
        self._register_routes()

    def _register_routes(self) -> None:
        r = self.router
        r.add_api_route("/dashboard", self.dashboard, methods=["GET"])
        r.add_api_route("/history", self.history, methods=["GET"])
        r.add_api_route("/top-artists", self.top_artists, methods=["GET"])
        r.add_api_route("/top-tracks", self.top_tracks, methods=["GET"])
        r.add_api_route("/profile", self.profile, methods=["GET"])
        r.add_api_route("/playlists", self.playlists, methods=["GET"])
        r.add_api_route("/playlists/{spotify_playlist_id}", self.playlist_detail, methods=["GET"])

    async def dashboard(self, user_id: RequireOwnDataView, session: DBSession) -> DashboardData:
        return await self._service.get_dashboard(user_id, session)

    async def history(
        self,
        user_id: RequireOwnDataView,
        session: DBSession,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        q: str | None = Query(default=None),
    ) -> PaginatedHistory:
        return await self._service.get_history(user_id, session, limit=limit, offset=offset, q=q)

    async def top_artists(
        self,
        user_id: RequireOwnDataView,
        session: DBSession,
        days: int = Query(default=90, ge=1),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> list[ArtistCount]:
        return await self._history_service.get_top_artists(user_id, session, days=days, limit=limit)

    async def top_tracks(
        self,
        user_id: RequireOwnDataView,
        session: DBSession,
        days: int = Query(default=90, ge=1),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> list[TrackSummary]:
        rows = await self._history_service.get_top_tracks(user_id, session, days=days, limit=limit)
        return [
            TrackSummary(
                track_id=r.track_id,
                track_name=r.track_name,
                artist_name=r.artist_name,
                play_count=r.play_count,
            )
            for r in rows
        ]

    async def profile(self, user_id: RequireOwnDataView, session: DBSession) -> UserProfile:
        return await self._service.get_profile(user_id, session)

    async def playlists(self, user_id: RequireOwnDataView, session: DBSession) -> list[PlaylistSummary]:
        return await self._service.get_playlists(user_id, session)

    async def playlist_detail(
        self,
        spotify_playlist_id: str,
        user_id: RequireOwnDataView,
        session: DBSession,
    ) -> PlaylistDetail:
        result = await self._service.get_playlist_detail(user_id, spotify_playlist_id, session)
        if result is None:
            raise HTTPException(status_code=404, detail="Playlist not found")
        return result


_instance = ExplorerRouter()
router = _instance.router
