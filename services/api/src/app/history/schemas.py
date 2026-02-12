"""Pydantic response models for history analysis endpoints."""

from datetime import datetime

from pydantic import BaseModel


class ArtistCount(BaseModel):
    """Artist with play count."""

    artist_id: int
    artist_name: str
    play_count: int


class TrackCount(BaseModel):
    """Track with play count and primary artist."""

    track_id: int
    track_name: str
    artist_name: str
    play_count: int


class HeatmapCell(BaseModel):
    """Single cell in a weekday/hour listening heatmap."""

    weekday: int  # 0=Monday .. 6=Sunday (ISO)
    hour: int  # 0-23
    play_count: int


class ListeningHeatmap(BaseModel):
    """Weekday/hour distribution of listening activity."""

    days: int
    total_plays: int
    cells: list[HeatmapCell]


class RepeatStats(BaseModel):
    """Track repeat / replay statistics."""

    days: int
    total_plays: int
    unique_tracks: int
    repeat_rate: float
    most_repeated: list[TrackCount]


class CoverageStats(BaseModel):
    """Data completeness and source breakdown."""

    days: int
    total_plays: int
    earliest_play: datetime | None
    latest_play: datetime | None
    api_source_count: int
    import_source_count: int
    active_days: int
    requested_days: int


class TasteSummary(BaseModel):
    """Comprehensive listening analysis combining multiple metrics."""

    days: int
    total_plays: int
    unique_tracks: int
    unique_artists: int
    total_ms_played: int
    listening_hours: float
    top_artists: list[ArtistCount]
    top_tracks: list[TrackCount]
    repeat_rate: float
    peak_weekday: int | None
    peak_hour: int | None
    coverage: CoverageStats
