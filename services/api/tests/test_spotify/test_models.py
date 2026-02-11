"""Tests for Spotify Pydantic models."""

from datetime import UTC, datetime

from shared.spotify.models import (
    BatchArtistsResponse,
    BatchAudioFeaturesResponse,
    BatchTracksResponse,
    RecentlyPlayedResponse,
    SpotifyArtistFull,
    SpotifyArtistSimplified,
    SpotifySearchResponse,
    SpotifyTrack,
    TopArtistsResponse,
    TopTracksResponse,
)


def test_spotify_track_minimal() -> None:
    """Track can be parsed with minimal fields."""
    track = SpotifyTrack.model_validate({"name": "Test Track"})
    assert track.name == "Test Track"
    assert track.id is None
    assert track.artists == []
    assert track.is_local is False


def test_spotify_track_full() -> None:
    """Track can be parsed with all fields populated."""
    data = {
        "id": "abc123",
        "name": "Bohemian Rhapsody",
        "uri": "spotify:track:abc123",
        "duration_ms": 354000,
        "explicit": False,
        "popularity": 85,
        "is_local": False,
        "artists": [
            {"id": "queen1", "name": "Queen", "uri": "spotify:artist:queen1"},
        ],
        "album": {
            "id": "album1",
            "name": "A Night at the Opera",
            "album_type": "album",
            "images": [{"url": "https://example.com/img.jpg", "height": 640, "width": 640}],
        },
        "external_ids": {"isrc": "GBUM71029604"},
        "external_urls": {"spotify": "https://open.spotify.com/track/abc123"},
    }
    track = SpotifyTrack.model_validate(data)
    assert track.id == "abc123"
    assert track.duration_ms == 354000
    assert len(track.artists) == 1
    assert track.artists[0].name == "Queen"
    assert track.album is not None
    assert track.album.name == "A Night at the Opera"
    assert track.external_ids is not None
    assert track.external_ids.isrc == "GBUM71029604"


def test_spotify_artist_simplified() -> None:
    """Simplified artist can be parsed."""
    artist = SpotifyArtistSimplified.model_validate({"id": "a1", "name": "Test Artist", "uri": "spotify:artist:a1"})
    assert artist.id == "a1"
    assert artist.name == "Test Artist"


def test_spotify_artist_full() -> None:
    """Full artist with genres and popularity."""
    data = {
        "id": "a1",
        "name": "Test Artist",
        "genres": ["rock", "pop"],
        "popularity": 75,
        "images": [{"url": "https://example.com/img.jpg"}],
        "followers": {"href": None, "total": 1000},
    }
    artist = SpotifyArtistFull.model_validate(data)
    assert artist.genres == ["rock", "pop"]
    assert artist.popularity == 75
    assert len(artist.images) == 1


def test_recently_played_response() -> None:
    """RecentlyPlayedResponse can be parsed from typical API output."""
    data = {
        "items": [
            {
                "track": {
                    "id": "t1",
                    "name": "Track 1",
                    "artists": [{"id": "a1", "name": "Artist 1"}],
                },
                "played_at": "2024-01-15T10:30:00Z",
                "context": {
                    "type": "playlist",
                    "uri": "spotify:playlist:p1",
                },
            },
            {
                "track": {
                    "id": "t2",
                    "name": "Track 2",
                    "artists": [{"id": "a2", "name": "Artist 2"}],
                },
                "played_at": "2024-01-15T10:25:00Z",
            },
        ],
        "cursors": {"after": "after_cursor", "before": "before_cursor"},
        "next": "https://api.spotify.com/v1/me/player/recently-played?before=...",
        "limit": 50,
    }
    response = RecentlyPlayedResponse.model_validate(data)
    assert len(response.items) == 2
    assert response.items[0].track.name == "Track 1"
    assert response.items[0].played_at == datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
    assert response.items[0].context is not None
    assert response.items[0].context.type == "playlist"
    assert response.cursors is not None
    assert response.cursors.before == "before_cursor"


def test_recently_played_empty() -> None:
    """Empty response is valid."""
    response = RecentlyPlayedResponse.model_validate({"items": []})
    assert response.items == []


def test_batch_tracks_response() -> None:
    """BatchTracksResponse with null entries (deleted tracks)."""
    data = {
        "tracks": [
            {"id": "t1", "name": "Track 1"},
            None,
            {"id": "t3", "name": "Track 3"},
        ]
    }
    response = BatchTracksResponse.model_validate(data)
    assert len(response.tracks) == 3
    assert response.tracks[1] is None
    assert response.tracks[0] is not None
    assert response.tracks[0].name == "Track 1"


def test_batch_artists_response() -> None:
    """BatchArtistsResponse parses full artist objects."""
    data = {
        "artists": [
            {"id": "a1", "name": "Artist 1", "genres": ["rock"]},
        ]
    }
    response = BatchArtistsResponse.model_validate(data)
    assert len(response.artists) == 1
    assert response.artists[0] is not None
    assert response.artists[0].genres == ["rock"]


def test_batch_audio_features_response() -> None:
    """BatchAudioFeaturesResponse parses audio features."""
    data = {
        "audio_features": [
            {
                "id": "t1",
                "danceability": 0.735,
                "energy": 0.578,
                "key": 5,
                "tempo": 120.0,
                "valence": 0.334,
            },
            None,
        ]
    }
    response = BatchAudioFeaturesResponse.model_validate(data)
    assert len(response.audio_features) == 2
    assert response.audio_features[0] is not None
    assert response.audio_features[0].danceability == 0.735
    assert response.audio_features[1] is None


def test_top_artists_response() -> None:
    """TopArtistsResponse parses."""
    data = {
        "items": [{"id": "a1", "name": "Top Artist", "genres": ["pop"]}],
        "total": 50,
        "limit": 20,
        "offset": 0,
    }
    response = TopArtistsResponse.model_validate(data)
    assert len(response.items) == 1
    assert response.total == 50


def test_top_tracks_response() -> None:
    """TopTracksResponse parses."""
    data = {
        "items": [{"id": "t1", "name": "Top Track"}],
        "total": 50,
        "limit": 20,
        "offset": 0,
    }
    response = TopTracksResponse.model_validate(data)
    assert len(response.items) == 1


def test_search_response() -> None:
    """SpotifySearchResponse parses all sections."""
    data = {
        "tracks": {
            "items": [{"id": "t1", "name": "Found Track"}],
            "total": 100,
            "limit": 20,
            "offset": 0,
        },
        "artists": {
            "items": [{"id": "a1", "name": "Found Artist"}],
            "total": 50,
            "limit": 20,
            "offset": 0,
        },
    }
    response = SpotifySearchResponse.model_validate(data)
    assert response.tracks is not None
    assert len(response.tracks.items) == 1
    assert response.artists is not None
    assert len(response.artists.items) == 1
    assert response.albums is None


def test_search_response_partial() -> None:
    """Search response with only tracks."""
    data = {
        "tracks": {
            "items": [{"id": "t1", "name": "Track"}],
            "total": 1,
        }
    }
    response = SpotifySearchResponse.model_validate(data)
    assert response.tracks is not None
    assert response.artists is None
