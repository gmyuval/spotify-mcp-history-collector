"""MCP tool handlers for history analysis."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.history.service import HistoryService
from app.mcp.registry import registry
from app.mcp.schemas import MCPToolParam

_svc = HistoryService()

_USER_PARAM = MCPToolParam(name="user_id", type="int", description="User ID")
_DAYS_PARAM = MCPToolParam(name="days", type="int", description="Time window in days", required=False, default=90)
_LIMIT_PARAM = MCPToolParam(name="limit", type="int", description="Max results", required=False, default=20)


@registry.register(
    name="history.taste_summary",
    description="Comprehensive listening analysis: top artists/tracks, listening hours, repeat rate, peak times, coverage",
    category="history",
    parameters=[_USER_PARAM, _DAYS_PARAM],
)
async def taste_summary(args: dict[str, Any], session: AsyncSession) -> Any:
    result = await _svc.get_taste_summary(args["user_id"], session, days=args.get("days", 90))
    return result.model_dump()


@registry.register(
    name="history.top_artists",
    description="Top artists ranked by play count within time window",
    category="history",
    parameters=[_USER_PARAM, _DAYS_PARAM, _LIMIT_PARAM],
)
async def top_artists(args: dict[str, Any], session: AsyncSession) -> Any:
    results = await _svc.get_top_artists(
        args["user_id"], session, days=args.get("days", 90), limit=args.get("limit", 20)
    )
    return [r.model_dump() for r in results]


@registry.register(
    name="history.top_tracks",
    description="Top tracks ranked by play count within time window",
    category="history",
    parameters=[_USER_PARAM, _DAYS_PARAM, _LIMIT_PARAM],
)
async def top_tracks(args: dict[str, Any], session: AsyncSession) -> Any:
    results = await _svc.get_top_tracks(
        args["user_id"], session, days=args.get("days", 90), limit=args.get("limit", 20)
    )
    return [r.model_dump() for r in results]


@registry.register(
    name="history.listening_heatmap",
    description="Weekday/hour distribution of listening activity",
    category="history",
    parameters=[_USER_PARAM, _DAYS_PARAM],
)
async def listening_heatmap(args: dict[str, Any], session: AsyncSession) -> Any:
    result = await _svc.get_listening_heatmap(args["user_id"], session, days=args.get("days", 90))
    return result.model_dump()


@registry.register(
    name="history.repeat_rate",
    description="Track repeat/replay statistics and most replayed tracks",
    category="history",
    parameters=[_USER_PARAM, _DAYS_PARAM],
)
async def repeat_rate(args: dict[str, Any], session: AsyncSession) -> Any:
    result = await _svc.get_repeat_rate(args["user_id"], session, days=args.get("days", 90))
    return result.model_dump()


@registry.register(
    name="history.coverage",
    description="Data completeness: source breakdown (API vs import), date range, active days",
    category="history",
    parameters=[_USER_PARAM, _DAYS_PARAM],
)
async def coverage(args: dict[str, Any], session: AsyncSession) -> Any:
    result = await _svc.get_coverage(args["user_id"], session, days=args.get("days", 90))
    return result.model_dump()
