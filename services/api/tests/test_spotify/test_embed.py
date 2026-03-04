"""Tests for Spotify embed-based playlist track fetcher."""

import json

import httpx
import pytest
import respx

from shared.spotify.embed import SpotifyEmbedClient
from shared.spotify.exceptions import SpotifyEmbedError
from shared.spotify.models import EmbedTrackItem


def _build_embed_html(track_list: list[dict[str, object]]) -> str:
    """Build a fake embed HTML page with __NEXT_DATA__ containing the given trackList."""
    next_data = {
        "props": {
            "pageProps": {
                "state": {
                    "data": {
                        "entity": {
                            "type": "playlist",
                            "name": "Test Playlist",
                            "trackList": track_list,
                        }
                    }
                }
            }
        }
    }
    return (
        f'<html><body><script id="__NEXT_DATA__" type="application/json">{json.dumps(next_data)}</script></body></html>'
    )


class TestParseEmbedHtml:
    """Tests for SpotifyEmbedClient._parse_embed_html (pure parsing, no HTTP)."""

    def test_parse_valid_tracks(self) -> None:
        tracks_data = [
            {"uid": "spotify:track:abc123", "title": "Song A", "subtitle": "Artist X", "duration": 200000},
            {"uid": "spotify:track:def456", "title": "Song B", "subtitle": "Artist Y, Artist Z", "duration": 300000},
        ]
        html = _build_embed_html(tracks_data)
        result = SpotifyEmbedClient._parse_embed_html(html, "test_pl")

        assert len(result) == 2
        assert result[0] == EmbedTrackItem(track_id="abc123", name="Song A", artists=["Artist X"], duration_ms=200000)
        assert result[1] == EmbedTrackItem(
            track_id="def456", name="Song B", artists=["Artist Y", "Artist Z"], duration_ms=300000
        )

    def test_parse_uri_fallback(self) -> None:
        """Tracks with 'uri' field instead of 'uid' should still be parsed."""
        tracks_data = [{"uri": "spotify:track:uri123", "title": "URI Track", "subtitle": "Artist", "duration": 100000}]
        html = _build_embed_html(tracks_data)
        result = SpotifyEmbedClient._parse_embed_html(html, "test_pl")

        assert len(result) == 1
        assert result[0].track_id == "uri123"

    def test_parse_skips_non_tracks(self) -> None:
        """Items without spotify:track: prefix should be skipped."""
        tracks_data = [
            {"uid": "spotify:track:valid1", "title": "Valid", "subtitle": "A", "duration": 100000},
            {"uid": "spotify:episode:ep1", "title": "Episode", "subtitle": "Podcast", "duration": 500000},
            {"title": "No UID", "subtitle": "Unknown", "duration": 0},
        ]
        html = _build_embed_html(tracks_data)
        result = SpotifyEmbedClient._parse_embed_html(html, "test_pl")

        assert len(result) == 1
        assert result[0].track_id == "valid1"

    def test_parse_empty_track_list(self) -> None:
        html = _build_embed_html([])
        result = SpotifyEmbedClient._parse_embed_html(html, "test_pl")
        assert result == []

    def test_parse_no_next_data(self) -> None:
        html = "<html><body>No data here</body></html>"
        with pytest.raises(SpotifyEmbedError, match="No __NEXT_DATA__"):
            SpotifyEmbedClient._parse_embed_html(html, "test_pl")

    def test_parse_invalid_json(self) -> None:
        html = '<html><body><script id="__NEXT_DATA__" type="application/json">{"bad": json}</script></body></html>'
        with pytest.raises(SpotifyEmbedError, match="Failed to parse"):
            SpotifyEmbedClient._parse_embed_html(html, "test_pl")

    def test_parse_no_track_list(self) -> None:
        next_data = {"props": {"pageProps": {"state": {"data": {"entity": {"type": "playlist"}}}}}}
        html = f'<html><body><script id="__NEXT_DATA__" type="application/json">{json.dumps(next_data)}</script></body></html>'
        with pytest.raises(SpotifyEmbedError, match="No trackList"):
            SpotifyEmbedClient._parse_embed_html(html, "test_pl")


class TestFetchPlaylistTracks:
    """Tests for SpotifyEmbedClient.fetch_playlist_tracks (mocked HTTP)."""

    @respx.mock
    async def test_fetch_success(self) -> None:
        tracks_data = [
            {"uid": "spotify:track:t1", "title": "Track One", "subtitle": "Art1", "duration": 180000},
        ]
        html = _build_embed_html(tracks_data)
        respx.get("https://open.spotify.com/embed/playlist/pl123").mock(return_value=httpx.Response(200, text=html))

        client = SpotifyEmbedClient(min_request_interval=0)
        result = await client.fetch_playlist_tracks("pl123")
        assert len(result) == 1
        assert result[0].track_id == "t1"

    @respx.mock
    async def test_fetch_http_error(self) -> None:
        respx.get("https://open.spotify.com/embed/playlist/pl_err").mock(
            return_value=httpx.Response(404, text="Not Found")
        )
        client = SpotifyEmbedClient(min_request_interval=0)
        with pytest.raises(SpotifyEmbedError, match="HTTP 404"):
            await client.fetch_playlist_tracks("pl_err")

    @respx.mock
    async def test_fetch_connection_error(self) -> None:
        respx.get("https://open.spotify.com/embed/playlist/pl_conn").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        client = SpotifyEmbedClient(min_request_interval=0)
        with pytest.raises(SpotifyEmbedError, match="Failed to fetch"):
            await client.fetch_playlist_tracks("pl_conn")
