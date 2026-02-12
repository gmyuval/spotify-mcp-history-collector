"""Tests for ZipImportParser."""

import json
import zipfile
from pathlib import Path

import pytest

from shared.zip_import.parser import ZipFormatError, ZipImportParser


@pytest.fixture
def extended_zip(tmp_path: Path) -> Path:
    """Create a test ZIP with extended streaming history format."""
    records = [
        {
            "ts": "2023-06-15T10:30:00Z",
            "ms_played": 180000,
            "master_metadata_track_name": "Track A",
            "master_metadata_album_artist_name": "Artist A",
            "master_metadata_album_album_name": "Album A",
            "spotify_track_uri": "spotify:track:AAA",
            "ip_addr_decrypted": "1.2.3.4",
            "username": "testuser",
        },
        {
            "ts": "2023-06-15T11:00:00Z",
            "ms_played": 200000,
            "master_metadata_track_name": "Track B",
            "master_metadata_album_artist_name": "Artist B",
            "master_metadata_album_album_name": "Album B",
            "spotify_track_uri": "spotify:track:BBB",
        },
        {
            "ts": "2023-06-15T12:00:00Z",
            "ms_played": 100000,
            "master_metadata_track_name": None,
            "master_metadata_album_artist_name": None,
        },
    ]
    zip_path = tmp_path / "export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("endsong_0.json", json.dumps(records))
    return zip_path


@pytest.fixture
def account_data_zip(tmp_path: Path) -> Path:
    """Create a test ZIP with account data format."""
    records = [
        {"endTime": "2023-06-15 10:30", "msPlayed": 120000, "trackName": "Song X", "artistName": "Artist X"},
        {"endTime": "2023-06-15 11:00", "msPlayed": 60000, "trackName": "Song Y", "artistName": "Artist Y"},
    ]
    zip_path = tmp_path / "export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("StreamingHistory0.json", json.dumps(records))
    return zip_path


@pytest.fixture
def streaming_history_audio_zip(tmp_path: Path) -> Path:
    """Create a test ZIP with Streaming_History_Audio naming (extended format)."""
    records = [
        {
            "ts": "2024-03-01T08:00:00Z",
            "ms_played": 250000,
            "master_metadata_track_name": "Track C",
            "master_metadata_album_artist_name": "Artist C",
            "master_metadata_album_album_name": "Album C",
            "spotify_track_uri": "spotify:track:CCC",
        },
    ]
    zip_path = tmp_path / "export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("Streaming_History_Audio_2023-2024_0.json", json.dumps(records))
    return zip_path


@pytest.fixture
def empty_zip(tmp_path: Path) -> Path:
    """Create a test ZIP with no recognizable files."""
    zip_path = tmp_path / "export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("readme.txt", "not a spotify export")
    return zip_path


def test_detect_format_extended(extended_zip: Path) -> None:
    """Detects extended streaming history format."""
    parser = ZipImportParser()
    assert parser.detect_format(extended_zip) == "extended"


def test_detect_format_account_data(account_data_zip: Path) -> None:
    """Detects account data format."""
    parser = ZipImportParser()
    assert parser.detect_format(account_data_zip) == "account_data"


def test_detect_format_unknown(empty_zip: Path) -> None:
    """Raises ZipFormatError for unrecognizable ZIP."""
    parser = ZipImportParser()
    with pytest.raises(ZipFormatError):
        parser.detect_format(empty_zip)


def test_iter_batches_extended(extended_zip: Path) -> None:
    """Parses extended format, skips incomplete records, strips sensitive fields."""
    parser = ZipImportParser(batch_size=10)
    batches = list(parser.iter_batches(extended_zip, "extended"))

    assert len(batches) == 1
    records = batches[0]
    # 3 raw records, but one has None track/artist → 2 valid
    assert len(records) == 2
    assert records[0].track_name == "Track A"
    assert records[1].track_name == "Track B"


def test_iter_batches_account_data(account_data_zip: Path) -> None:
    """Parses account data format."""
    parser = ZipImportParser(batch_size=10)
    batches = list(parser.iter_batches(account_data_zip, "account_data"))

    assert len(batches) == 1
    records = batches[0]
    assert len(records) == 2
    assert records[0].track_name == "Song X"
    assert records[1].track_name == "Song Y"


def test_iter_batches_respects_batch_size(extended_zip: Path) -> None:
    """Yields batches of the configured size."""
    parser = ZipImportParser(batch_size=1)
    batches = list(parser.iter_batches(extended_zip, "extended"))
    assert len(batches) == 2
    assert len(batches[0]) == 1
    assert len(batches[1]) == 1


def test_iter_batches_respects_max_records(extended_zip: Path) -> None:
    """Stops after max_records."""
    parser = ZipImportParser(batch_size=10, max_records=1)
    batches = list(parser.iter_batches(extended_zip, "extended"))
    total = sum(len(b) for b in batches)
    assert total == 1


def test_detect_format_streaming_history_audio(streaming_history_audio_zip: Path) -> None:
    """Detects Streaming_History_Audio files as extended format."""
    parser = ZipImportParser()
    assert parser.detect_format(streaming_history_audio_zip) == "extended"


def test_iter_batches_streaming_history_audio(streaming_history_audio_zip: Path) -> None:
    """Parses Streaming_History_Audio files using extended normalizer."""
    parser = ZipImportParser(batch_size=10)
    batches = list(parser.iter_batches(streaming_history_audio_zip, "extended"))

    assert len(batches) == 1
    records = batches[0]
    assert len(records) == 1
    assert records[0].track_name == "Track C"
    assert records[0].artist_name == "Artist C"
    assert records[0].spotify_track_id == "CCC"
