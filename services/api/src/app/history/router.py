"""History analysis REST endpoints — class-based router."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.auth import require_admin
from app.dependencies import db_manager
from app.history.schemas import (
    ArtistCount,
    CoverageStats,
    ListeningHeatmap,
    RepeatStats,
    TasteSummary,
    TrackCount,
)
from app.history.service import HistoryService
from shared.db.models.user import User


class HistoryRouter:
    """Class-based router for history analysis endpoints."""

    def __init__(self) -> None:
        self._service = HistoryService()
        self.router = APIRouter(dependencies=[Depends(require_admin)])
        self._register_routes()

    def _register_routes(self) -> None:
        r = self.router
        r.add_api_route(
            "/users/{user_id}/top-artists",
            self.top_artists,
            methods=["GET"],
            response_model=list[ArtistCount],
        )
        r.add_api_route(
            "/users/{user_id}/top-tracks",
            self.top_tracks,
            methods=["GET"],
            response_model=list[TrackCount],
        )
        r.add_api_route(
            "/users/{user_id}/heatmap",
            self.heatmap,
            methods=["GET"],
            response_model=ListeningHeatmap,
        )
        r.add_api_route(
            "/users/{user_id}/repeat-rate",
            self.repeat_rate,
            methods=["GET"],
            response_model=RepeatStats,
        )
        r.add_api_route(
            "/users/{user_id}/coverage",
            self.coverage,
            methods=["GET"],
            response_model=CoverageStats,
        )
        r.add_api_route(
            "/users/{user_id}/taste-summary",
            self.taste_summary,
            methods=["GET"],
            response_model=TasteSummary,
        )

    @staticmethod
    async def _validate_user(user_id: int, session: AsyncSession) -> None:
        result = await session.execute(select(User).where(User.id == user_id))
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail=f"User {user_id} not found")

    async def top_artists(
        self,
        user_id: int,
        session: Annotated[AsyncSession, Depends(db_manager.dependency)],
        days: int = Query(default=90, ge=1),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> list[ArtistCount]:
        """Top artists by play count within the given time window."""
        await self._validate_user(user_id, session)
        return await self._service.get_top_artists(user_id, session, days, limit)

    async def top_tracks(
        self,
        user_id: int,
        session: Annotated[AsyncSession, Depends(db_manager.dependency)],
        days: int = Query(default=90, ge=1),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> list[TrackCount]:
        """Top tracks by play count within the given time window."""
        await self._validate_user(user_id, session)
        return await self._service.get_top_tracks(user_id, session, days, limit)

    async def heatmap(
        self,
        user_id: int,
        session: Annotated[AsyncSession, Depends(db_manager.dependency)],
        days: int = Query(default=90, ge=1),
    ) -> ListeningHeatmap:
        """Weekday/hour listening distribution."""
        await self._validate_user(user_id, session)
        return await self._service.get_listening_heatmap(user_id, session, days)

    async def repeat_rate(
        self,
        user_id: int,
        session: Annotated[AsyncSession, Depends(db_manager.dependency)],
        days: int = Query(default=90, ge=1),
    ) -> RepeatStats:
        """Track repeat / replay statistics."""
        await self._validate_user(user_id, session)
        return await self._service.get_repeat_rate(user_id, session, days)

    async def coverage(
        self,
        user_id: int,
        session: Annotated[AsyncSession, Depends(db_manager.dependency)],
        days: int = Query(default=90, ge=1),
    ) -> CoverageStats:
        """Data completeness and source breakdown."""
        await self._validate_user(user_id, session)
        return await self._service.get_coverage(user_id, session, days)

    async def taste_summary(
        self,
        user_id: int,
        session: Annotated[AsyncSession, Depends(db_manager.dependency)],
        days: int = Query(default=90, ge=1),
    ) -> TasteSummary:
        """Comprehensive listening analysis."""
        await self._validate_user(user_id, session)
        return await self._service.get_taste_summary(user_id, session, days)


_instance = HistoryRouter()
router = _instance.router
