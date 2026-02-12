"""History analysis REST endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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

router = APIRouter()
_service = HistoryService()


async def _validate_user(user_id: int, session: AsyncSession) -> None:
    result = await session.execute(select(User).where(User.id == user_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")


@router.get("/users/{user_id}/top-artists", response_model=list[ArtistCount])
async def top_artists(
    user_id: int,
    session: Annotated[AsyncSession, Depends(db_manager.dependency)],
    days: int = Query(default=90, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[ArtistCount]:
    """Top artists by play count within the given time window."""
    await _validate_user(user_id, session)
    return await _service.get_top_artists(user_id, session, days, limit)


@router.get("/users/{user_id}/top-tracks", response_model=list[TrackCount])
async def top_tracks(
    user_id: int,
    session: Annotated[AsyncSession, Depends(db_manager.dependency)],
    days: int = Query(default=90, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[TrackCount]:
    """Top tracks by play count within the given time window."""
    await _validate_user(user_id, session)
    return await _service.get_top_tracks(user_id, session, days, limit)


@router.get("/users/{user_id}/heatmap", response_model=ListeningHeatmap)
async def heatmap(
    user_id: int,
    session: Annotated[AsyncSession, Depends(db_manager.dependency)],
    days: int = Query(default=90, ge=1),
) -> ListeningHeatmap:
    """Weekday/hour listening distribution."""
    await _validate_user(user_id, session)
    return await _service.get_listening_heatmap(user_id, session, days)


@router.get("/users/{user_id}/repeat-rate", response_model=RepeatStats)
async def repeat_rate(
    user_id: int,
    session: Annotated[AsyncSession, Depends(db_manager.dependency)],
    days: int = Query(default=90, ge=1),
) -> RepeatStats:
    """Track repeat / replay statistics."""
    await _validate_user(user_id, session)
    return await _service.get_repeat_rate(user_id, session, days)


@router.get("/users/{user_id}/coverage", response_model=CoverageStats)
async def coverage(
    user_id: int,
    session: Annotated[AsyncSession, Depends(db_manager.dependency)],
    days: int = Query(default=90, ge=1),
) -> CoverageStats:
    """Data completeness and source breakdown."""
    await _validate_user(user_id, session)
    return await _service.get_coverage(user_id, session, days)


@router.get("/users/{user_id}/taste-summary", response_model=TasteSummary)
async def taste_summary(
    user_id: int,
    session: Annotated[AsyncSession, Depends(db_manager.dependency)],
    days: int = Query(default=90, ge=1),
) -> TasteSummary:
    """Comprehensive listening analysis."""
    await _validate_user(user_id, session)
    return await _service.get_taste_summary(user_id, session, days)
