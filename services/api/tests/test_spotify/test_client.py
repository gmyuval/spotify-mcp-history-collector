"""Tests for SpotifyClient."""

import json
from typing import Any

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


# ---------------------------------------------------------------------------
# Single-resource info methods
# ---------------------------------------------------------------------------


@respx.mock
async def test_get_track() -> None:
    """get_track returns parsed SpotifyTrack."""
    respx.get("https://api.spotify.com/v1/tracks/abc123").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "abc123",
                "name": "Test Track",
                "duration_ms": 210000,
                "popularity": 75,
                "artists": [{"id": "a1", "name": "Artist 1"}],
                "album": {"id": "alb1", "name": "Test Album"},
            },
        )
    )

    client = SpotifyClient("test-token", max_retries=0)
    result = await client.get_track("abc123")
    assert result.id == "abc123"
    assert result.name == "Test Track"
    assert result.duration_ms == 210000
    assert len(result.artists) == 1


@respx.mock
async def test_get_artist() -> None:
    """get_artist returns parsed SpotifyArtistFull."""
    respx.get("https://api.spotify.com/v1/artists/art1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "art1",
                "name": "Test Artist",
                "genres": ["rock", "indie"],
                "popularity": 80,
                "followers": {"total": 50000},
                "images": [{"url": "https://img.example.com/1.jpg", "height": 300, "width": 300}],
            },
        )
    )

    client = SpotifyClient("test-token", max_retries=0)
    result = await client.get_artist("art1")
    assert result.id == "art1"
    assert result.name == "Test Artist"
    assert result.genres == ["rock", "indie"]
    assert result.popularity == 80


@respx.mock
async def test_get_album() -> None:
    """get_album returns parsed SpotifyAlbumFull with tracks."""
    respx.get("https://api.spotify.com/v1/albums/alb1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "alb1",
                "name": "Test Album",
                "album_type": "album",
                "release_date": "2024-06-15",
                "total_tracks": 12,
                "label": "Test Label",
                "genres": ["rock"],
                "popularity": 70,
                "artists": [{"id": "a1", "name": "Artist 1"}],
                "tracks": {
                    "items": [
                        {
                            "id": "t1",
                            "name": "Track 1",
                            "track_number": 1,
                            "duration_ms": 180000,
                            "artists": [{"id": "a1", "name": "Artist 1"}],
                        },
                        {
                            "id": "t2",
                            "name": "Track 2",
                            "track_number": 2,
                            "duration_ms": 200000,
                            "artists": [{"id": "a1", "name": "Artist 1"}],
                        },
                    ],
                    "total": 12,
                },
                "images": [{"url": "https://img.example.com/album.jpg"}],
            },
        )
    )

    client = SpotifyClient("test-token", max_retries=0)
    result = await client.get_album("alb1")
    assert result.id == "alb1"
    assert result.name == "Test Album"
    assert result.total_tracks == 12
    assert result.label == "Test Label"
    assert result.tracks is not None
    assert len(result.tracks.items) == 2
    assert result.tracks.items[0].name == "Track 1"


# ---------------------------------------------------------------------------
# Playlist read methods
# ---------------------------------------------------------------------------


def _playlist_json(playlist_id: str = "pl1", name: str = "My Playlist") -> dict[str, Any]:
    """Helper to build a playlist JSON response."""
    return {
        "id": playlist_id,
        "name": name,
        "description": "A test playlist",
        "public": True,
        "collaborative": False,
        "owner": {"id": "user1", "display_name": "Test User"},
        "snapshot_id": "snap1",
        "tracks": {
            "items": [
                {
                    "track": {"id": "t1", "name": "Track 1", "artists": [{"id": "a1", "name": "Artist 1"}]},
                    "added_at": "2024-01-15T10:00:00Z",
                }
            ],
            "total": 1,
        },
        "images": [],
        "external_urls": {"spotify": "https://open.spotify.com/playlist/pl1"},
    }


@respx.mock
async def test_get_user_playlists() -> None:
    """get_user_playlists returns parsed UserPlaylistsResponse with href+total tracks."""
    respx.get("https://api.spotify.com/v1/me/playlists").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "pl1",
                        "name": "Playlist 1",
                        "public": True,
                        "owner": {"id": "user1", "display_name": "Test User"},
                        "tracks": {"href": "https://api.spotify.com/v1/playlists/pl1/tracks", "total": 25},
                    },
                    {
                        "id": "pl2",
                        "name": "Playlist 2",
                        "public": False,
                        "owner": {"id": "user1", "display_name": "Test User"},
                        "tracks": {"href": "https://api.spotify.com/v1/playlists/pl2/tracks", "total": 10},
                    },
                ],
                "total": 2,
                "limit": 50,
                "offset": 0,
            },
        )
    )

    client = SpotifyClient("test-token", max_retries=0)
    result = await client.get_user_playlists()
    assert len(result.items) == 2
    assert result.items[0].name == "Playlist 1"
    assert result.items[0].tracks == {"href": "https://api.spotify.com/v1/playlists/pl1/tracks", "total": 25}
    assert result.items[0].tracks.get("total") == 25
    assert result.total == 2


@respx.mock
async def test_get_playlist() -> None:
    """get_playlist returns parsed SpotifyPlaylist with tracks."""
    respx.get("https://api.spotify.com/v1/playlists/pl1").mock(return_value=httpx.Response(200, json=_playlist_json()))

    client = SpotifyClient("test-token", max_retries=0)
    result = await client.get_playlist("pl1")
    assert result.id == "pl1"
    assert result.name == "My Playlist"
    assert result.tracks is not None
    assert result.tracks.total == 1
    assert result.tracks.items[0].track is not None
    assert result.tracks.items[0].track.name == "Track 1"


@respx.mock
async def test_get_playlist_new_api_format() -> None:
    """get_playlist handles Spotify's new format (items/item instead of tracks/track)."""
    new_format_json = {
        "id": "pl2",
        "name": "New Format Playlist",
        "description": "",
        "public": True,
        "collaborative": False,
        "owner": {"id": "user1", "display_name": "Test User"},
        "snapshot_id": "snap2",
        "items": {
            "items": [
                {
                    "item": {"id": "t2", "name": "New Track", "artists": [{"id": "a1", "name": "Artist 1"}]},
                    "added_at": "2025-01-15T10:00:00Z",
                }
            ],
            "total": 1,
            "limit": 100,
            "offset": 0,
        },
        "images": [],
        "external_urls": {"spotify": "https://open.spotify.com/playlist/pl2"},
    }
    respx.get("https://api.spotify.com/v1/playlists/pl2").mock(return_value=httpx.Response(200, json=new_format_json))

    client = SpotifyClient("test-token", max_retries=0)
    result = await client.get_playlist("pl2")
    assert result.id == "pl2"
    assert result.name == "New Format Playlist"
    assert result.tracks is not None
    assert result.tracks.total == 1
    assert result.tracks.items[0].track is not None
    assert result.tracks.items[0].track.name == "New Track"


# ---------------------------------------------------------------------------
# Playlist write methods
# ---------------------------------------------------------------------------


@respx.mock
async def test_create_playlist() -> None:
    """create_playlist sends POST with JSON body and returns parsed playlist."""
    route = respx.post("https://api.spotify.com/v1/me/playlists").mock(
        return_value=httpx.Response(
            201,
            json=_playlist_json("new_pl", "New Playlist"),
        )
    )

    client = SpotifyClient("test-token", max_retries=0)
    result = await client.create_playlist("New Playlist", description="Desc", public=False)
    assert result.name == "New Playlist"
    assert route.called
    request = route.calls[0].request
    body = json.loads(request.content)
    assert body["name"] == "New Playlist"
    assert body["public"] is False


@respx.mock
async def test_add_tracks_to_playlist() -> None:
    """add_tracks_to_playlist sends POST with URIs in JSON body."""
    route = respx.post("https://api.spotify.com/v1/playlists/pl1/tracks").mock(
        return_value=httpx.Response(200, json={"snapshot_id": "snap2"})
    )

    client = SpotifyClient("test-token", max_retries=0)
    result = await client.add_tracks_to_playlist("pl1", ["spotify:track:t1", "spotify:track:t2"])
    assert result.snapshot_id == "snap2"
    assert route.called
    request = route.calls[0].request
    body = request.content.decode()
    assert "spotify:track:t1" in body
    assert "spotify:track:t2" in body


@respx.mock
async def test_add_tracks_with_position() -> None:
    """add_tracks_to_playlist with position includes it in the body."""
    route = respx.post("https://api.spotify.com/v1/playlists/pl1/tracks").mock(
        return_value=httpx.Response(200, json={"snapshot_id": "snap3"})
    )

    client = SpotifyClient("test-token", max_retries=0)
    await client.add_tracks_to_playlist("pl1", ["spotify:track:t1"], position=5)
    request = route.calls[0].request
    body = json.loads(request.content)
    assert body["position"] == 5


@respx.mock
async def test_remove_tracks_from_playlist() -> None:
    """remove_tracks_from_playlist sends DELETE with track URIs."""
    route = respx.delete("https://api.spotify.com/v1/playlists/pl1/tracks").mock(
        return_value=httpx.Response(200, json={"snapshot_id": "snap4"})
    )

    client = SpotifyClient("test-token", max_retries=0)
    result = await client.remove_tracks_from_playlist("pl1", ["spotify:track:t1"])
    assert result.snapshot_id == "snap4"
    assert route.called
    request = route.calls[0].request
    body = request.content.decode()
    assert "spotify:track:t1" in body


@respx.mock
async def test_update_playlist_details() -> None:
    """update_playlist_details sends PUT with JSON body."""
    route = respx.put("https://api.spotify.com/v1/playlists/pl1").mock(return_value=httpx.Response(200))

    client = SpotifyClient("test-token", max_retries=0)
    await client.update_playlist_details("pl1", name="New Name", description="New Desc", public=False)
    assert route.called
    request = route.calls[0].request
    body = json.loads(request.content)
    assert body["name"] == "New Name"
    assert body["public"] is False


@respx.mock
async def test_update_playlist_partial() -> None:
    """update_playlist_details only sends provided fields."""
    route = respx.put("https://api.spotify.com/v1/playlists/pl1").mock(return_value=httpx.Response(200))

    client = SpotifyClient("test-token", max_retries=0)
    await client.update_playlist_details("pl1", name="Just Name")
    request = route.calls[0].request
    body = json.loads(request.content)
    assert body["name"] == "Just Name"
    assert "description" not in body
    assert "public" not in body


@respx.mock
async def test_post_with_401_refreshes_token() -> None:
    """POST requests also trigger token refresh on 401."""
    respx.post("https://api.spotify.com/v1/me/playlists").mock(
        side_effect=[
            httpx.Response(401, json={"error": {"message": "expired"}}),
            httpx.Response(201, json=_playlist_json("pl_new", "Refreshed Playlist")),
        ]
    )

    async def mock_refresh() -> str:
        return "new-token"

    client = SpotifyClient("old-token", on_token_expired=mock_refresh, max_retries=1)
    result = await client.create_playlist("Refreshed Playlist")
    assert result.name == "Refreshed Playlist"
