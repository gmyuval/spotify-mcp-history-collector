"""Tests for SpotifyClient."""

import httpx
import pytest
import respx

from shared.spotify.client import SpotifyClient
from shared.spotify.exceptions import (
    SpotifyAuthError,
    SpotifyRateLimitError,
    SpotifyRequestError,
    SpotifyServerError,
)


def _recently_played_json(count: int = 1) -> dict[str, object]:
    """Helper to build a recently-played JSON response."""
    items = [
        {
            "track": {
                "id": f"track{i}",
                "name": f"Track {i}",
                "artists": [{"id": f"artist{i}", "name": f"Artist {i}"}],
            },
            "played_at": f"2024-01-15T10:{i:02d}:00Z",
        }
        for i in range(count)
    ]
    return {"items": items, "cursors": {"before": "cursor_before"}, "limit": 50}


@respx.mock
async def test_get_recently_played_success() -> None:
    """Successful recently-played call returns parsed response."""
    respx.get("https://api.spotify.com/v1/me/player/recently-played").mock(
        return_value=httpx.Response(200, json=_recently_played_json(2))
    )

    client = SpotifyClient("test-token", max_retries=0)
    result = await client.get_recently_played()
    assert len(result.items) == 2
    assert result.items[0].track.name == "Track 0"


@respx.mock
async def test_get_recently_played_with_before() -> None:
    """Recently-played passes the before parameter."""
    route = respx.get("https://api.spotify.com/v1/me/player/recently-played").mock(
        return_value=httpx.Response(200, json=_recently_played_json(1))
    )

    client = SpotifyClient("test-token", max_retries=0)
    await client.get_recently_played(before=1705312200000)
    assert route.called
    request = route.calls[0].request
    assert "before=1705312200000" in str(request.url)


@respx.mock
async def test_401_without_callback_raises_auth_error() -> None:
    """401 without on_token_expired raises SpotifyAuthError."""
    respx.get("https://api.spotify.com/v1/me/player/recently-played").mock(
        return_value=httpx.Response(401, json={"error": {"message": "The access token expired"}})
    )

    client = SpotifyClient("expired-token", max_retries=0)
    with pytest.raises(SpotifyAuthError, match="401"):
        await client.get_recently_played()


@respx.mock
async def test_401_with_callback_retries_once() -> None:
    """401 with callback refreshes token and retries, succeeding on second attempt."""
    route = respx.get("https://api.spotify.com/v1/me/player/recently-played").mock(
        side_effect=[
            httpx.Response(401, json={"error": {"message": "expired"}}),
            httpx.Response(200, json=_recently_played_json(1)),
        ]
    )

    refresh_called = False

    async def mock_refresh() -> str:
        nonlocal refresh_called
        refresh_called = True
        return "new-token"

    client = SpotifyClient("old-token", on_token_expired=mock_refresh, max_retries=1)
    result = await client.get_recently_played()
    assert refresh_called
    assert len(result.items) == 1
    assert route.call_count == 2


@respx.mock
async def test_401_with_callback_only_retries_once() -> None:
    """If 401 persists after token refresh, raises SpotifyAuthError."""
    respx.get("https://api.spotify.com/v1/me/player/recently-played").mock(
        return_value=httpx.Response(401, json={"error": {"message": "still expired"}})
    )

    async def mock_refresh() -> str:
        return "still-bad-token"

    client = SpotifyClient("old-token", on_token_expired=mock_refresh, max_retries=2)
    with pytest.raises(SpotifyAuthError, match="401"):
        await client.get_recently_played()


@respx.mock
async def test_429_retries_and_succeeds() -> None:
    """429 with Retry-After header retries and eventually succeeds."""
    respx.get("https://api.spotify.com/v1/me/player/recently-played").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json=_recently_played_json(1)),
        ]
    )

    client = SpotifyClient("test-token", max_retries=1, retry_base_delay=0.0)
    result = await client.get_recently_played()
    assert len(result.items) == 1


@respx.mock
async def test_429_exhausted_raises_rate_limit_error() -> None:
    """Persistent 429 raises SpotifyRateLimitError."""
    respx.get("https://api.spotify.com/v1/me/player/recently-played").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "0"})
    )

    client = SpotifyClient("test-token", max_retries=1, retry_base_delay=0.0)
    with pytest.raises(SpotifyRateLimitError):
        await client.get_recently_played()


@respx.mock
async def test_5xx_retries_and_succeeds() -> None:
    """5xx retries with backoff and succeeds on next attempt."""
    respx.get("https://api.spotify.com/v1/me/player/recently-played").mock(
        side_effect=[
            httpx.Response(503, text="Service Unavailable"),
            httpx.Response(200, json=_recently_played_json(1)),
        ]
    )

    client = SpotifyClient("test-token", max_retries=1, retry_base_delay=0.0)
    result = await client.get_recently_played()
    assert len(result.items) == 1


@respx.mock
async def test_5xx_exhausted_raises_server_error() -> None:
    """Persistent 5xx raises SpotifyServerError."""
    respx.get("https://api.spotify.com/v1/me/player/recently-played").mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )

    client = SpotifyClient("test-token", max_retries=1, retry_base_delay=0.0)
    with pytest.raises(SpotifyServerError, match="500"):
        await client.get_recently_played()


@respx.mock
async def test_4xx_raises_request_error_immediately() -> None:
    """Non-retryable 4xx (e.g., 403) raises SpotifyRequestError immediately."""
    respx.get("https://api.spotify.com/v1/me/player/recently-played").mock(
        return_value=httpx.Response(403, text="Forbidden")
    )

    client = SpotifyClient("test-token", max_retries=3)
    with pytest.raises(SpotifyRequestError, match="403"):
        await client.get_recently_played()


@respx.mock
async def test_get_tracks() -> None:
    """get_tracks returns parsed BatchTracksResponse."""
    respx.get("https://api.spotify.com/v1/tracks").mock(
        return_value=httpx.Response(
            200,
            json={"tracks": [{"id": "t1", "name": "Track 1"}]},
        )
    )

    client = SpotifyClient("test-token", max_retries=0)
    result = await client.get_tracks(["t1"])
    assert len(result.tracks) == 1
    assert result.tracks[0] is not None
    assert result.tracks[0].name == "Track 1"


@respx.mock
async def test_get_tracks_empty() -> None:
    """get_tracks with empty list returns empty response without API call."""
    client = SpotifyClient("test-token", max_retries=0)
    result = await client.get_tracks([])
    assert result.tracks == []


@respx.mock
async def test_get_artists() -> None:
    """get_artists returns parsed BatchArtistsResponse."""
    respx.get("https://api.spotify.com/v1/artists").mock(
        return_value=httpx.Response(
            200,
            json={"artists": [{"id": "a1", "name": "Artist 1", "genres": ["rock"]}]},
        )
    )

    client = SpotifyClient("test-token", max_retries=0)
    result = await client.get_artists(["a1"])
    assert len(result.artists) == 1


@respx.mock
async def test_get_audio_features() -> None:
    """get_audio_features returns parsed response."""
    respx.get("https://api.spotify.com/v1/audio-features").mock(
        return_value=httpx.Response(
            200,
            json={"audio_features": [{"id": "t1", "danceability": 0.8}]},
        )
    )

    client = SpotifyClient("test-token", max_retries=0)
    result = await client.get_audio_features(["t1"])
    assert len(result.audio_features) == 1


@respx.mock
async def test_get_top_artists() -> None:
    """get_top_artists returns parsed response."""
    respx.get("https://api.spotify.com/v1/me/top/artists").mock(
        return_value=httpx.Response(
            200,
            json={"items": [{"id": "a1", "name": "Top Artist"}], "total": 1},
        )
    )

    client = SpotifyClient("test-token", max_retries=0)
    result = await client.get_top_artists()
    assert len(result.items) == 1


@respx.mock
async def test_get_top_tracks() -> None:
    """get_top_tracks returns parsed response."""
    respx.get("https://api.spotify.com/v1/me/top/tracks").mock(
        return_value=httpx.Response(
            200,
            json={"items": [{"id": "t1", "name": "Top Track"}], "total": 1},
        )
    )

    client = SpotifyClient("test-token", max_retries=0)
    result = await client.get_top_tracks()
    assert len(result.items) == 1


@respx.mock
async def test_search() -> None:
    """search returns parsed SpotifySearchResponse."""
    respx.get("https://api.spotify.com/v1/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "tracks": {
                    "items": [{"id": "t1", "name": "Found Track"}],
                    "total": 1,
                }
            },
        )
    )

    client = SpotifyClient("test-token", max_retries=0)
    result = await client.search("test query")
    assert result.tracks is not None
    assert len(result.tracks.items) == 1
