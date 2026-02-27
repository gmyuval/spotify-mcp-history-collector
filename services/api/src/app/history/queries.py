"""SQLAlchemy query builders for history analysis — class-based."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import Integer, case, cast, distinct, extract, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.enums import TrackSource
from shared.db.models.music import Artist, Play, Track, TrackArtist


class HistoryQueries:
    """Stateless query builder for history analysis."""

    @staticmethod
    def _cutoff(days: int) -> datetime:
        """Return a UTC datetime `days` ago."""
        return datetime.now(UTC) - timedelta(days=days)

    @staticmethod
    async def top_artists(
        user_id: int,
        session: AsyncSession,
        days: int = 90,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        """Top artists by play count within the time window."""
        cutoff = HistoryQueries._cutoff(days)
        stmt = (
            select(
                Artist.id.label("artist_id"),
                Artist.name.label("artist_name"),
                func.count(Play.id).label("play_count"),
            )
            .select_from(Play)
            .join(Track, Play.track_id == Track.id)
            .join(TrackArtist, TrackArtist.track_id == Track.id)
            .join(Artist, TrackArtist.artist_id == Artist.id)
            .where(Play.user_id == user_id, Play.played_at >= cutoff)
            .group_by(Artist.id, Artist.name)
            .order_by(func.count(Play.id).desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return [dict(row._mapping) for row in result.all()]

    @staticmethod
    async def top_tracks(
        user_id: int,
        session: AsyncSession,
        days: int = 90,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        """Top tracks by play count, with primary artist name."""
        cutoff = HistoryQueries._cutoff(days)

        # Subquery: primary artist per track (position=0)
        primary_artist = (
            select(TrackArtist.track_id, Artist.name.label("artist_name"))
            .join(Artist, TrackArtist.artist_id == Artist.id)
            .where(TrackArtist.position == 0)
            .subquery()
        )

        stmt = (
            select(
                Track.id.label("track_id"),
                Track.name.label("track_name"),
                func.coalesce(primary_artist.c.artist_name, literal("Unknown")).label("artist_name"),
                func.count(Play.id).label("play_count"),
            )
            .select_from(Play)
            .join(Track, Play.track_id == Track.id)
            .outerjoin(primary_artist, primary_artist.c.track_id == Track.id)
            .where(Play.user_id == user_id, Play.played_at >= cutoff)
            .group_by(Track.id, Track.name, primary_artist.c.artist_name)
            .order_by(func.count(Play.id).desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return [dict(row._mapping) for row in result.all()]

    @staticmethod
    async def play_stats(
        user_id: int,
        session: AsyncSession,
        days: int = 90,
    ) -> dict[str, object]:
        """Aggregate play stats: total plays, unique tracks/artists, total ms played."""
        cutoff = HistoryQueries._cutoff(days)

        stmt = select(
            func.count(Play.id).label("total_plays"),
            func.count(distinct(Play.track_id)).label("unique_tracks"),
            func.coalesce(func.sum(Play.ms_played), 0).label("total_ms_played"),
        ).where(Play.user_id == user_id, Play.played_at >= cutoff)
        result = await session.execute(stmt)
        row = result.one()

        # Unique artists requires a join
        artist_stmt = (
            select(func.count(distinct(Artist.id)))
            .select_from(Play)
            .join(Track, Play.track_id == Track.id)
            .join(TrackArtist, TrackArtist.track_id == Track.id)
            .join(Artist, TrackArtist.artist_id == Artist.id)
            .where(Play.user_id == user_id, Play.played_at >= cutoff)
        )
        unique_artists = (await session.execute(artist_stmt)).scalar() or 0

        return {
            "total_plays": row.total_plays,
            "unique_tracks": row.unique_tracks,
            "unique_artists": unique_artists,
            "total_ms_played": row.total_ms_played,
        }

    @staticmethod
    async def heatmap(
        user_id: int,
        session: AsyncSession,
        days: int = 90,
    ) -> list[dict[str, object]]:
        """Weekday/hour play counts. Weekday: 0=Monday..6=Sunday (ISO)."""
        cutoff = HistoryQueries._cutoff(days)

        dialect = session.bind.dialect.name if session.bind else "postgresql"

        if dialect == "sqlite":
            # strftime('%w') → 0=Sunday; convert to ISO: (w+6)%7 → 0=Monday
            weekday_expr = (cast(func.strftime("%w", Play.played_at), Integer) + 6) % 7
            hour_expr = cast(func.strftime("%H", Play.played_at), Integer)
        else:
            # PostgreSQL: EXTRACT(ISODOW) → 1=Monday..7=Sunday; subtract 1
            weekday_expr = cast(extract("isodow", Play.played_at), Integer) - 1
            hour_expr = cast(extract("hour", Play.played_at), Integer)

        stmt = (
            select(
                weekday_expr.label("weekday"),
                hour_expr.label("hour"),
                func.count(Play.id).label("play_count"),
            )
            .where(Play.user_id == user_id, Play.played_at >= cutoff)
            .group_by(weekday_expr, hour_expr)
            .order_by(weekday_expr, hour_expr)
        )
        result = await session.execute(stmt)
        return [dict(row._mapping) for row in result.all()]

    @staticmethod
    async def coverage(
        user_id: int,
        session: AsyncSession,
        days: int = 90,
    ) -> dict[str, object]:
        """Data completeness: source breakdown, date range, active days."""
        cutoff = HistoryQueries._cutoff(days)

        stmt = select(
            func.count(Play.id).label("total_plays"),
            func.min(Play.played_at).label("earliest_play"),
            func.max(Play.played_at).label("latest_play"),
            func.sum(case((Play.source == TrackSource.SPOTIFY_API, 1), else_=0)).label("api_source_count"),
            func.sum(case((Play.source == TrackSource.IMPORT_ZIP, 1), else_=0)).label("import_source_count"),
            func.count(distinct(func.date(Play.played_at))).label("active_days"),
        ).where(Play.user_id == user_id, Play.played_at >= cutoff)
        result = await session.execute(stmt)
        row = result.one()
        return {
            "total_plays": row.total_plays,
            "earliest_play": row.earliest_play,
            "latest_play": row.latest_play,
            "api_source_count": row.api_source_count or 0,
            "import_source_count": row.import_source_count or 0,
            "active_days": row.active_days,
        }

    @staticmethod
    async def recent_plays(
        user_id: int,
        session: AsyncSession,
        limit: int = 50,
        offset: int = 0,
        q: str | None = None,
    ) -> tuple[list[dict[str, object]], int]:
        """Paginated recent plays with track and artist details.

        Returns (rows, total_count) for pagination.
        """
        # Subquery: primary artist per track (position=0)
        primary_artist = (
            select(TrackArtist.track_id, Artist.name.label("artist_name"))
            .join(Artist, TrackArtist.artist_id == Artist.id)
            .where(TrackArtist.position == 0)
            .subquery()
        )

        base = (
            select(
                Play.played_at,
                Track.id.label("track_id"),
                Track.name.label("track_name"),
                func.coalesce(primary_artist.c.artist_name, literal("Unknown")).label("artist_name"),
                Play.ms_played,
            )
            .select_from(Play)
            .join(Track, Play.track_id == Track.id)
            .outerjoin(primary_artist, primary_artist.c.track_id == Track.id)
            .where(Play.user_id == user_id)
        )

        if q:
            pattern = f"%{q}%"
            base = base.where(
                or_(
                    Track.name.ilike(pattern),
                    primary_artist.c.artist_name.ilike(pattern),
                )
            )

        # Total count
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await session.execute(count_stmt)).scalar() or 0

        # Paginated results
        stmt = base.order_by(Play.played_at.desc()).limit(limit).offset(offset)
        result = await session.execute(stmt)
        rows = [dict(row._mapping) for row in result.all()]

        return rows, total


# Module-level aliases for backward compatibility
query_top_artists = HistoryQueries.top_artists
query_top_tracks = HistoryQueries.top_tracks
query_play_stats = HistoryQueries.play_stats
query_heatmap = HistoryQueries.heatmap
query_coverage = HistoryQueries.coverage
