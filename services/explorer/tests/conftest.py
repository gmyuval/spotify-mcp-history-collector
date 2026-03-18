"""Test fixtures for the explorer frontend."""

from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from explorer.api_client import ExplorerApiClient
from explorer.settings import ExplorerSettings


def _default_mock_api() -> AsyncMock:
    """Create a mock ExplorerApiClient with sensible default return values."""
    api = AsyncMock(spec=ExplorerApiClient)

    api.get_dashboard.return_value = {
        "total_plays": 150,
        "unique_tracks": 42,
        "unique_artists": 15,
        "listening_hours": 12.5,
        "top_artists": [
            {"artist_name": "Test Artist", "play_count": 30},
            {"artist_name": "Another Artist", "play_count": 20},
        ],
        "top_tracks": [
            {"track_name": "Test Track", "artist_name": "Test Artist", "play_count": 15},
            {"track_name": "Another Track", "artist_name": "Another Artist", "play_count": 10},
        ],
    }

    api.get_history.return_value = {
        "items": [
            {
                "played_at": "2026-02-27T10:00:00",
                "track_name": "Test Track",
                "artist_name": "Test Artist",
                "ms_played": 180000,
                "track_id": 1,
            },
        ],
        "total": 1,
        "limit": 50,
        "offset": 0,
    }

    api.get_top_artists.return_value = [
        {"artist_name": "Test Artist", "play_count": 30},
    ]

    api.get_top_tracks.return_value = [
        {"track_name": "Test Track", "artist_name": "Test Artist", "play_count": 15},
    ]

    api.get_playlists.return_value = [
        {
            "spotify_playlist_id": "pl_123",
            "name": "My Playlist",
            "description": "Test playlist",
            "total_tracks": 5,
        },
    ]

    api.get_playlist.return_value = {
        "name": "My Playlist",
        "description": "Test playlist",
        "tracks": [
            {
                "track_name": "Track 1",
                "position": 0,
                "artists_json": [{"id": "a1", "name": "Artist 1"}],
            },
        ],
    }

    api.get_taste_profile.return_value = {
        "profile": {
            "user_id": 1,
            "profile": {
                "core_genres": ["symphonic metal", "power metal"],
                "avoid": ["pop"],
                "energy_preferences": {"default": "upbeat"},
                "playlist_rules": {"max_tracks_per_artist": 3},
            },
            "version": 2,
            "updated_at": "2026-02-28T12:00:00",
        },
        "recent_events": [
            {
                "event_id": "abc-123",
                "timestamp": "2026-02-28T12:00:00",
                "source": "user",
                "type": "like",
                "payload": {"raw_text": "I like symphonic metal"},
            },
        ],
    }

    api.update_taste_profile.return_value = {
        "user_id": 1,
        "profile": {"core_genres": ["symphonic metal", "power metal", "melodic death metal"]},
        "version": 3,
        "updated_at": "2026-02-28T13:00:00",
    }

    api.clear_taste_profile.return_value = None

    api.get_memory_playlists.return_value = {
        "items": [
            {
                "playlist_id": "sp_abc123",
                "name": "My AI Playlist",
                "description": "Created by assistant",
                "created_at": "2026-03-01T10:00:00",
                "updated_at": "2026-03-01T12:00:00",
                "intent_tags": ["upbeat", "metal"],
                "track_count": 15,
            },
        ],
        "total": 1,
        "limit": 20,
        "offset": 0,
    }

    api.get_memory_playlist.return_value = {
        "playlist_id": "sp_abc123",
        "name": "My AI Playlist",
        "description": "Created by assistant",
        "created_at": "2026-03-01T10:00:00",
        "updated_at": "2026-03-01T12:00:00",
        "intent_tags": ["upbeat", "metal"],
        "seed_context": {"days": 30},
        "tracks": [
            {"spotify_track_id": "track1", "track_name": "Track One", "artists": []},
            {"spotify_track_id": "track2", "track_name": "Track Two", "artists": []},
            {"spotify_track_id": "track3", "track_name": "Track Three", "artists": []},
        ],
        "recent_events": [
            {
                "event_id": "evt-123",
                "timestamp": "2026-03-01T12:00:00",
                "type": "ADD_TRACKS",
                "payload": {"track_ids": ["track4"]},
            },
        ],
        "total_events": 1,
    }

    api.get_memory_playlist_events.return_value = {
        "items": [
            {
                "event_id": "evt-123",
                "timestamp": "2026-03-01T12:00:00",
                "type": "ADD_TRACKS",
                "payload": {"track_ids": ["track4"]},
            },
        ],
        "total": 1,
        "limit": 20,
        "offset": 0,
    }

    api.get_track_detail.return_value = {
        "track_id": 123,
        "name": "Test Track",
        "spotify_track_id": "sp_track_123",
        "album_name": "Test Album",
        "album_spotify_id": "sp_album_123",
        "duration_ms": 240000,
        "play_count": 42,
        "total_ms_played": 10080000,
        "first_played": "2025-06-01T10:00:00",
        "last_played": "2026-03-01T18:30:00",
        "artists": [
            {"artist_id": 1, "name": "Test Artist"},
        ],
        "spotify": None,
        "audio_features": None,
        "recent_plays": [
            {
                "played_at": "2026-03-01T18:30:00",
                "ms_played": 240000,
                "context_type": "playlist",
            },
        ],
    }

    api.get_artist_detail.return_value = {
        "artist_id": 456,
        "name": "Test Artist",
        "spotify_artist_id": "sp_artist_456",
        "play_count": 150,
        "unique_tracks": 25,
        "total_ms_played": 54000000,
        "first_played": "2025-05-15T08:00:00",
        "genres": ["symphonic metal", "power metal"],
        "spotify": None,
        "top_tracks": [
            {"track_id": 123, "name": "Test Track", "play_count": 42},
            {"track_id": 124, "name": "Another Track", "play_count": 30},
        ],
    }

    api.get_album_detail.return_value = {
        "name": "Test Album",
        "spotify_album_id": "sp_album_123",
        "play_count": 80,
        "unique_tracks": 10,
        "artists": [
            {"artist_id": 1, "name": "Test Artist"},
        ],
        "spotify": None,
        "tracks": [
            {"track_id": 123, "name": "Test Track", "duration_ms": 240000, "play_count": 42},
            {"track_id": 124, "name": "Another Track", "duration_ms": 180000, "play_count": 30},
        ],
    }

    api.get_preference_events.return_value = {
        "items": [
            {
                "event_id": "abc-123",
                "timestamp": "2026-02-28T12:00:00",
                "source": "user",
                "type": "like",
                "payload": {"raw_text": "I like symphonic metal"},
            },
        ],
        "total": 1,
        "limit": 20,
        "offset": 0,
    }

    return api


def _test_settings() -> ExplorerSettings:
    return ExplorerSettings(
        API_BASE_URL="http://test-api:8000",
        API_PUBLIC_URL="http://test-api:8000",
        EXPLORER_BASE_URL="http://localhost:8002",
    )


@pytest.fixture
def mock_api() -> AsyncMock:
    """Mock ExplorerApiClient with default return values."""
    return _default_mock_api()


@pytest.fixture
def client(mock_api: AsyncMock) -> Generator[TestClient]:
    """TestClient with mock API client injected via overridden lifespan."""
    from explorer.main import app

    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def _test_lifespan(a: FastAPI) -> AsyncGenerator[None]:
        a.state.api = mock_api
        a.state.settings = _test_settings()
        yield

    app.router.lifespan_context = _test_lifespan
    try:
        with TestClient(app) as tc:
            yield tc
    finally:
        app.router.lifespan_context = original_lifespan
