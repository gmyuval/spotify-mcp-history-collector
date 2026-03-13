"""Tests for /tracks and /artists browser routes + dashboard time-window partial."""

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from explorer.api_client import ApiError


class TestTracksPage:
    def test_tracks_requires_login(self, client: TestClient) -> None:
        resp = client.get("/tracks/", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"

    def test_tracks_page(self, client: TestClient, mock_api: AsyncMock) -> None:
        mock_api.get_tracks.return_value = {
            "items": [
                {
                    "track_id": 1,
                    "name": "Test Track",
                    "artist_name": "Test Artist",
                    "play_count": 10,
                    "last_played": "2026-03-01T10:00:00",
                },
                {
                    "track_id": 2,
                    "name": "Other Track",
                    "artist_name": "Other Artist",
                    "play_count": 5,
                    "last_played": None,
                },
            ],
            "total": 2,
            "limit": 50,
            "offset": 0,
        }
        client.cookies.set("access_token", "test-jwt")
        resp = client.get("/tracks/")
        assert resp.status_code == 200
        assert "Test Track" in resp.text
        assert "Other Track" in resp.text
        mock_api.get_tracks.assert_called_once_with(
            "test-jwt", limit=50, offset=0, sort="play_count", q=None, days=None
        )
        client.cookies.clear()

    def test_tracks_with_search(self, client: TestClient, mock_api: AsyncMock) -> None:
        mock_api.get_tracks.return_value = {"items": [], "total": 0, "limit": 50, "offset": 0}
        client.cookies.set("access_token", "test-jwt")
        resp = client.get("/tracks?q=test&sort=name")
        assert resp.status_code == 200
        mock_api.get_tracks.assert_called_once_with("test-jwt", limit=50, offset=0, sort="name", q="test", days=None)
        client.cookies.clear()

    def test_tracks_table_partial(self, client: TestClient, mock_api: AsyncMock) -> None:
        mock_api.get_tracks.return_value = {
            "items": [
                {"track_id": 1, "name": "Track 1", "artist_name": "Artist 1", "play_count": 5, "last_played": None}
            ],
            "total": 1,
            "limit": 10,
            "offset": 0,
        }
        client.cookies.set("access_token", "test-jwt")
        resp = client.get("/tracks/partials/tracks-table?limit=10&offset=0")
        assert resp.status_code == 200
        assert "Track 1" in resp.text
        mock_api.get_tracks.assert_called_once_with(
            "test-jwt", limit=10, offset=0, sort="play_count", q=None, days=None
        )
        client.cookies.clear()

    def test_tracks_api_error(self, client: TestClient, mock_api: AsyncMock) -> None:
        mock_api.get_tracks.side_effect = ApiError(500, "Server error")
        client.cookies.set("access_token", "test-jwt")
        resp = client.get("/tracks/")
        assert resp.status_code == 200
        assert "Server error" in resp.text
        client.cookies.clear()

    def test_tracks_401_redirects(self, client: TestClient, mock_api: AsyncMock) -> None:
        mock_api.get_tracks.side_effect = ApiError(401, "Unauthorized")
        client.cookies.set("access_token", "test-jwt")
        resp = client.get("/tracks/", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"
        client.cookies.clear()

    def test_tracks_with_days(self, client: TestClient, mock_api: AsyncMock) -> None:
        mock_api.get_tracks.return_value = {"items": [], "total": 0, "limit": 50, "offset": 0}
        client.cookies.set("access_token", "test-jwt")
        resp = client.get("/tracks?days=30")
        assert resp.status_code == 200
        mock_api.get_tracks.assert_called_once_with("test-jwt", limit=50, offset=0, sort="play_count", q=None, days=30)
        client.cookies.clear()


class TestArtistsPage:
    def test_artists_requires_login(self, client: TestClient) -> None:
        resp = client.get("/artists/", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"

    def test_artists_page(self, client: TestClient, mock_api: AsyncMock) -> None:
        mock_api.get_artists.return_value = {
            "items": [
                {"artist_id": 1, "name": "Test Artist", "play_count": 20, "track_count": 5},
                {"artist_id": 2, "name": "Other Artist", "play_count": 10, "track_count": 3},
            ],
            "total": 2,
            "limit": 50,
            "offset": 0,
        }
        client.cookies.set("access_token", "test-jwt")
        resp = client.get("/artists/")
        assert resp.status_code == 200
        assert "Test Artist" in resp.text
        assert "Other Artist" in resp.text
        mock_api.get_artists.assert_called_once_with(
            "test-jwt", limit=50, offset=0, sort="play_count", q=None, days=None
        )
        client.cookies.clear()

    def test_artists_with_search(self, client: TestClient, mock_api: AsyncMock) -> None:
        mock_api.get_artists.return_value = {"items": [], "total": 0, "limit": 50, "offset": 0}
        client.cookies.set("access_token", "test-jwt")
        resp = client.get("/artists?q=test&sort=name")
        assert resp.status_code == 200
        mock_api.get_artists.assert_called_once_with("test-jwt", limit=50, offset=0, sort="name", q="test", days=None)
        client.cookies.clear()

    def test_artists_table_partial(self, client: TestClient, mock_api: AsyncMock) -> None:
        mock_api.get_artists.return_value = {
            "items": [{"artist_id": 1, "name": "Artist 1", "play_count": 10, "track_count": 2}],
            "total": 1,
            "limit": 10,
            "offset": 0,
        }
        client.cookies.set("access_token", "test-jwt")
        resp = client.get("/artists/partials/artists-table?limit=10&offset=0")
        assert resp.status_code == 200
        assert "Artist 1" in resp.text
        mock_api.get_artists.assert_called_once_with(
            "test-jwt", limit=10, offset=0, sort="play_count", q=None, days=None
        )
        client.cookies.clear()

    def test_artists_api_error(self, client: TestClient, mock_api: AsyncMock) -> None:
        mock_api.get_artists.side_effect = ApiError(500, "Server error")
        client.cookies.set("access_token", "test-jwt")
        resp = client.get("/artists/")
        assert resp.status_code == 200
        assert "Server error" in resp.text
        client.cookies.clear()

    def test_artists_401_redirects(self, client: TestClient, mock_api: AsyncMock) -> None:
        mock_api.get_artists.side_effect = ApiError(401, "Unauthorized")
        client.cookies.set("access_token", "test-jwt")
        resp = client.get("/artists/", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"
        client.cookies.clear()


class TestDashboardPartial:
    def test_top_content_partial(self, client: TestClient, mock_api: AsyncMock) -> None:
        client.cookies.set("access_token", "test-jwt")
        resp = client.get("/dashboard/partials/top?days=7")
        assert resp.status_code == 200
        assert "Test Artist" in resp.text
        mock_api.get_dashboard.assert_called_once_with("test-jwt", days=7)
        client.cookies.clear()

    def test_top_content_partial_default_days(self, client: TestClient, mock_api: AsyncMock) -> None:
        client.cookies.set("access_token", "test-jwt")
        resp = client.get("/dashboard/partials/top")
        assert resp.status_code == 200
        mock_api.get_dashboard.assert_called_once_with("test-jwt", days=30)
        client.cookies.clear()

    def test_top_content_partial_requires_login(self, client: TestClient) -> None:
        resp = client.get("/dashboard/partials/top", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"

    def test_top_content_partial_401(self, client: TestClient, mock_api: AsyncMock) -> None:
        mock_api.get_dashboard.side_effect = ApiError(401, "Unauthorized")
        client.cookies.set("access_token", "test-jwt")
        resp = client.get("/dashboard/partials/top", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"
        client.cookies.clear()


class TestDashboardClickableCards:
    def test_dashboard_has_clickable_cards(self, client: TestClient, mock_api: AsyncMock) -> None:
        client.cookies.set("access_token", "test-jwt")
        resp = client.get("/dashboard")
        assert resp.status_code == 200
        assert 'href="/history"' in resp.text
        assert 'href="/tracks"' in resp.text
        assert 'href="/artists"' in resp.text
        client.cookies.clear()

    def test_dashboard_has_time_window_pills(self, client: TestClient, mock_api: AsyncMock) -> None:
        client.cookies.set("access_token", "test-jwt")
        resp = client.get("/dashboard")
        assert resp.status_code == 200
        assert "7d" in resp.text
        assert "30d" in resp.text
        assert "90d" in resp.text
        assert "1y" in resp.text
        assert "All" in resp.text
        client.cookies.clear()


class TestDetailPlaceholders:
    def test_track_detail_shows_coming_soon(self, client: TestClient, mock_api: AsyncMock) -> None:
        client.cookies.set("access_token", "test-jwt")
        resp = client.get("/tracks/123")
        assert resp.status_code == 200
        assert "Under Construction" in resp.text
        assert 'href="/tracks"' in resp.text
        client.cookies.clear()

    def test_artist_detail_shows_coming_soon(self, client: TestClient, mock_api: AsyncMock) -> None:
        client.cookies.set("access_token", "test-jwt")
        resp = client.get("/artists/456")
        assert resp.status_code == 200
        assert "Under Construction" in resp.text
        assert 'href="/artists"' in resp.text
        client.cookies.clear()

    def test_track_detail_requires_login(self, client: TestClient) -> None:
        resp = client.get("/tracks/123", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"

    def test_artist_detail_requires_login(self, client: TestClient) -> None:
        resp = client.get("/artists/456", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"


class TestNavLinks:
    def test_tracks_nav_link(self, client: TestClient, mock_api: AsyncMock) -> None:
        client.cookies.set("access_token", "test-jwt")
        resp = client.get("/dashboard")
        assert resp.status_code == 200
        assert 'href="/tracks"' in resp.text
        assert 'href="/artists"' in resp.text
        client.cookies.clear()
