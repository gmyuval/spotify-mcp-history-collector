"""History analysis service — orchestrates queries into response models."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.history.queries import HistoryQueries
from app.history.schemas import (
    ArtistCount,
    CoverageStats,
    HeatmapCell,
    ListeningHeatmap,
    RepeatStats,
    TasteSummary,
    TrackCount,
)


class HistoryService:
    """Stateless service that builds Pydantic models from raw query results."""

    async def get_top_artists(
        self,
        user_id: int,
        session: AsyncSession,
        days: int = 90,
        limit: int = 20,
    ) -> list[ArtistCount]:
        rows = await HistoryQueries.top_artists(user_id, session, days, limit)
        return [ArtistCount(**row) for row in rows]

    async def get_top_tracks(
        self,
        user_id: int,
        session: AsyncSession,
        days: int = 90,
        limit: int = 20,
    ) -> list[TrackCount]:
        rows = await HistoryQueries.top_tracks(user_id, session, days, limit)
        return [TrackCount(**row) for row in rows]

    async def get_listening_heatmap(
        self,
        user_id: int,
        session: AsyncSession,
        days: int = 90,
    ) -> ListeningHeatmap:
        cells_raw = await HistoryQueries.heatmap(user_id, session, days)
        cells = [HeatmapCell(**c) for c in cells_raw]
        total = sum(c.play_count for c in cells)
        return ListeningHeatmap(days=days, total_plays=total, cells=cells)

    async def get_repeat_rate(
        self,
        user_id: int,
        session: AsyncSession,
        days: int = 90,
        limit: int = 10,
    ) -> RepeatStats:
        stats = await HistoryQueries.play_stats(user_id, session, days)
        total_plays: int = stats["total_plays"]  # type: ignore[assignment]
        unique_tracks: int = stats["unique_tracks"]  # type: ignore[assignment]
        rate = total_plays / unique_tracks if unique_tracks > 0 else 0.0
        most_repeated = await HistoryQueries.top_tracks(user_id, session, days, limit)
        return RepeatStats(
            days=days,
            total_plays=total_plays,
            unique_tracks=unique_tracks,
            repeat_rate=round(rate, 2),
            most_repeated=[TrackCount(**r) for r in most_repeated],
        )

    async def get_coverage(
        self,
        user_id: int,
        session: AsyncSession,
        days: int = 90,
    ) -> CoverageStats:
        raw = await HistoryQueries.coverage(user_id, session, days)
        return CoverageStats(
            days=days,
            requested_days=days,
            **raw,
        )

    async def get_taste_summary(
        self,
        user_id: int,
        session: AsyncSession,
        days: int = 90,
    ) -> TasteSummary:
        stats = await HistoryQueries.play_stats(user_id, session, days)
        top_artists_raw = await HistoryQueries.top_artists(user_id, session, days, 10)
        top_tracks_raw = await HistoryQueries.top_tracks(user_id, session, days, 10)
        heatmap_raw = await HistoryQueries.heatmap(user_id, session, days)
        coverage_raw = await HistoryQueries.coverage(user_id, session, days)

        total_plays: int = stats["total_plays"]  # type: ignore[assignment]
        unique_tracks: int = stats["unique_tracks"]  # type: ignore[assignment]
        unique_artists: int = stats["unique_artists"]  # type: ignore[assignment]
        total_ms: int = stats["total_ms_played"]  # type: ignore[assignment]
        repeat_rate = total_plays / unique_tracks if unique_tracks > 0 else 0.0

        # Find peak weekday/hour from heatmap
        peak_weekday: int | None = None
        peak_hour: int | None = None
        if heatmap_raw:
            weekday_totals: dict[int, int] = {}
            hour_totals: dict[int, int] = {}
            for cell in heatmap_raw:
                wd = int(cell["weekday"])  # type: ignore[call-overload]
                hr = int(cell["hour"])  # type: ignore[call-overload]
                cnt = int(cell["play_count"])  # type: ignore[call-overload]
                weekday_totals[wd] = weekday_totals.get(wd, 0) + cnt
                hour_totals[hr] = hour_totals.get(hr, 0) + cnt
            peak_weekday = max(weekday_totals, key=weekday_totals.get)  # type: ignore[arg-type]
            peak_hour = max(hour_totals, key=hour_totals.get)  # type: ignore[arg-type]

        coverage = CoverageStats(
            days=days,
            requested_days=days,
            **coverage_raw,
        )

        return TasteSummary(
            days=days,
            total_plays=total_plays,
            unique_tracks=unique_tracks,
            unique_artists=unique_artists,
            total_ms_played=total_ms,
            listening_hours=round(total_ms / 3_600_000, 1),
            top_artists=[ArtistCount(**r) for r in top_artists_raw],
            top_tracks=[TrackCount(**r) for r in top_tracks_raw],
            repeat_rate=round(repeat_rate, 2),
            peak_weekday=peak_weekday,
            peak_hour=peak_hour,
            coverage=coverage,
        )
