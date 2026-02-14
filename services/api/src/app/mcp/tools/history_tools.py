"""MCP tool handlers for history analysis — class-based."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.history.service import HistoryService
from app.mcp.registry import registry
from app.mcp.schemas import MCPToolParam

_USER_PARAM = MCPToolParam(name="user_id", type="int", description="User ID")
_DAYS_PARAM = MCPToolParam(name="days", type="int", description="Time window in days", required=False, default=90)
_LIMIT_PARAM = MCPToolParam(name="limit", type="int", description="Max results", required=False, default=20)


class HistoryToolHandlers:
    """Registers and handles history-related MCP tools."""

    def __init__(self, service: HistoryService | None = None) -> None:
        self._service = service or HistoryService()
        self._register()

    def _register(self) -> None:
        registry.register(
            name="history.taste_summary",
            description="Comprehensive listening analysis: top artists/tracks, listening hours, repeat rate, peak times, coverage",
            category="history",
            parameters=[_USER_PARAM, _DAYS_PARAM],
        )(self.taste_summary)

        registry.register(
            name="history.top_artists",
            description="Top artists ranked by play count within time window",
            category="history",
            parameters=[_USER_PARAM, _DAYS_PARAM, _LIMIT_PARAM],
        )(self.top_artists)

        registry.register(
            name="history.top_tracks",
            description="Top tracks ranked by play count within time window",
            category="history",
            parameters=[_USER_PARAM, _DAYS_PARAM, _LIMIT_PARAM],
        )(self.top_tracks)

        registry.register(
            name="history.listening_heatmap",
            description="Weekday/hour distribution of listening activity",
            category="history",
            parameters=[_USER_PARAM, _DAYS_PARAM],
        )(self.listening_heatmap)

        registry.register(
            name="history.repeat_rate",
            description="Track repeat/replay statistics and most replayed tracks",
            category="history",
            parameters=[_USER_PARAM, _DAYS_PARAM],
        )(self.repeat_rate)

        registry.register(
            name="history.coverage",
            description="Data completeness: source breakdown (API vs import), date range, active days",
            category="history",
            parameters=[_USER_PARAM, _DAYS_PARAM],
        )(self.coverage)

    async def taste_summary(self, args: dict[str, Any], session: AsyncSession) -> Any:
        result = await self._service.get_taste_summary(args["user_id"], session, days=args.get("days", 90))
        return result.model_dump()

    async def top_artists(self, args: dict[str, Any], session: AsyncSession) -> Any:
        results = await self._service.get_top_artists(
            args["user_id"], session, days=args.get("days", 90), limit=args.get("limit", 20)
        )
        return [r.model_dump() for r in results]

    async def top_tracks(self, args: dict[str, Any], session: AsyncSession) -> Any:
        results = await self._service.get_top_tracks(
            args["user_id"], session, days=args.get("days", 90), limit=args.get("limit", 20)
        )
        return [r.model_dump() for r in results]

    async def listening_heatmap(self, args: dict[str, Any], session: AsyncSession) -> Any:
        result = await self._service.get_listening_heatmap(args["user_id"], session, days=args.get("days", 90))
        return result.model_dump()

    async def repeat_rate(self, args: dict[str, Any], session: AsyncSession) -> Any:
        result = await self._service.get_repeat_rate(args["user_id"], session, days=args.get("days", 90))
        return result.model_dump()

    async def coverage(self, args: dict[str, Any], session: AsyncSession) -> Any:
        result = await self._service.get_coverage(args["user_id"], session, days=args.get("days", 90))
        return result.model_dump()


_instance = HistoryToolHandlers()
