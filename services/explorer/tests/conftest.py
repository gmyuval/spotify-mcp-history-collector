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
