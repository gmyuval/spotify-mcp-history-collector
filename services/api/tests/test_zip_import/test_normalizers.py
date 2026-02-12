"""Tests for ZIP import normalizers."""

from datetime import UTC, datetime

from shared.zip_import.normalizers import (
    normalize_account_data_record,
    normalize_extended_record,
)


def test_normalize_extended_record_valid() -> None:
    """Valid extended record normalizes correctly."""
    raw = {
        "ts": "2023-06-15T10:30:00Z",
        "ms_played": 180000,
        "master_metadata_track_name": "Bohemian Rhapsody",
        "master_metadata_album_artist_name": "Queen",
        "master_metadata_album_album_name": "A Night at the Opera",
        "spotify_track_uri": "spotify:track:4u7EnebtmKWzUH433cf5Qv",
    }
    record = normalize_extended_record(raw)
    assert record is not None
    assert record.track_name == "Bohemian Rhapsody"
    assert record.artist_name == "Queen"
    assert record.album_name == "A Night at the Opera"
    assert record.ms_played == 180000
    assert record.played_at == datetime(2023, 6, 15, 10, 30, 0, tzinfo=UTC)
    assert record.spotify_track_uri == "spotify:track:4u7EnebtmKWzUH433cf5Qv"
    assert record.spotify_track_id == "4u7EnebtmKWzUH433cf5Qv"


def test_normalize_extended_record_missing_track_name() -> None:
    """Record without track name returns None (e.g. podcast)."""
    raw = {
        "ts": "2023-06-15T10:30:00Z",
        "ms_played": 180000,
        "master_metadata_track_name": None,
        "master_metadata_album_artist_name": "Queen",
    }
    assert normalize_extended_record(raw) is None


def test_normalize_extended_record_missing_artist_name() -> None:
    """Record without artist name returns None."""
    raw = {
        "ts": "2023-06-15T10:30:00Z",
        "ms_played": 180000,
        "master_metadata_track_name": "Track",
        "master_metadata_album_artist_name": None,
    }
    assert normalize_extended_record(raw) is None


def test_normalize_extended_record_invalid_timestamp() -> None:
    """Record with invalid timestamp returns None."""
    raw = {
        "ts": "not-a-date",
        "ms_played": 180000,
        "master_metadata_track_name": "Track",
        "master_metadata_album_artist_name": "Artist",
    }
    assert normalize_extended_record(raw) is None


def test_normalize_extended_record_no_uri() -> None:
    """Record without spotify_track_uri normalizes with None URI."""
    raw = {
        "ts": "2023-06-15T10:30:00Z",
        "ms_played": 120000,
        "master_metadata_track_name": "Track",
        "master_metadata_album_artist_name": "Artist",
    }
    record = normalize_extended_record(raw)
    assert record is not None
    assert record.spotify_track_uri is None
    assert record.spotify_track_id is None


def test_normalize_account_data_record_valid() -> None:
    """Valid account data record normalizes correctly."""
    raw = {
        "endTime": "2023-06-15 10:30",
        "msPlayed": 120000,
        "trackName": "Yesterday",
        "artistName": "The Beatles",
    }
    record = normalize_account_data_record(raw)
    assert record is not None
    assert record.track_name == "Yesterday"
    assert record.artist_name == "The Beatles"
    assert record.album_name is None
    assert record.ms_played == 120000
    assert record.played_at == datetime(2023, 6, 15, 10, 30, tzinfo=UTC)
    assert record.spotify_track_uri is None


def test_normalize_account_data_record_missing_track() -> None:
    """Account data record without trackName returns None."""
    raw = {
        "endTime": "2023-06-15 10:30",
        "msPlayed": 120000,
        "artistName": "Artist",
    }
    assert normalize_account_data_record(raw) is None


def test_normalize_account_data_record_invalid_time() -> None:
    """Account data record with invalid endTime returns None."""
    raw = {
        "endTime": "invalid",
        "msPlayed": 120000,
        "trackName": "Track",
        "artistName": "Artist",
    }
    assert normalize_account_data_record(raw) is None
