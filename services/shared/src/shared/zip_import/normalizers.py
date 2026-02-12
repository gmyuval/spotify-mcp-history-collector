"""Normalizers that convert raw JSON records from each Spotify export format into NormalizedPlayRecord."""

import logging
from datetime import UTC, datetime

from shared.zip_import.models import NormalizedPlayRecord

logger = logging.getLogger(__name__)


def normalize_extended_record(raw: dict[str, object]) -> NormalizedPlayRecord | None:
    """Normalize a record from Extended Streaming History (endsong_*.json).

    Expected fields:
        ts: str (ISO 8601 datetime, e.g. "2023-01-15T10:30:00Z")
        ms_played: int
        master_metadata_track_name: str | None
        master_metadata_album_artist_name: str | None
        master_metadata_album_album_name: str | None
        spotify_track_uri: str | None

    Returns None if the record is missing required fields (track or artist name).
    """
    track_name = raw.get("master_metadata_track_name")
    artist_name = raw.get("master_metadata_album_artist_name")

    if not track_name or not artist_name:
        return None

    ts_str = raw.get("ts")
    if not isinstance(ts_str, str):
        return None

    try:
        played_at = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        played_at = played_at.astimezone(UTC)
    except ValueError, TypeError:
        logger.warning("Skipping record with unparseable timestamp: %s", ts_str)
        return None

    ms_played = raw.get("ms_played", 0)
    if not isinstance(ms_played, int):
        ms_played = 0

    album_name = raw.get("master_metadata_album_album_name")
    spotify_track_uri = raw.get("spotify_track_uri")

    return NormalizedPlayRecord(
        track_name=str(track_name),
        artist_name=str(artist_name),
        album_name=str(album_name) if album_name else None,
        ms_played=ms_played,
        played_at=played_at,
        spotify_track_uri=str(spotify_track_uri) if spotify_track_uri else None,
    )


def normalize_account_data_record(raw: dict[str, object]) -> NormalizedPlayRecord | None:
    """Normalize a record from Account Data format (StreamingHistory*.json).

    Expected fields:
        endTime: str (e.g. "2023-01-15 10:30")
        msPlayed: int
        trackName: str
        artistName: str

    Returns None if missing required fields.
    """
    track_name = raw.get("trackName")
    artist_name = raw.get("artistName")

    if not track_name or not artist_name:
        return None

    end_time_str = raw.get("endTime")
    if not isinstance(end_time_str, str):
        return None

    try:
        played_at = datetime.strptime(end_time_str, "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
    except ValueError, TypeError:
        logger.warning("Skipping record with unparseable endTime: %s", end_time_str)
        return None

    ms_played = raw.get("msPlayed", 0)
    if not isinstance(ms_played, int):
        ms_played = 0

    return NormalizedPlayRecord(
        track_name=str(track_name),
        artist_name=str(artist_name),
        album_name=None,
        ms_played=ms_played,
        played_at=played_at,
        spotify_track_uri=None,
    )
