"""Tests for explorer frontend route handlers."""

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from explorer.api_client import ApiError

# --- Health check ---


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


# --- Auth ---


def test_login_page(client: TestClient) -> None:
    response = client.get("/login", follow_redirects=False)
    assert response.status_code == 200
    assert "Sign in with Google" in response.text


def test_login_page_redirects_when_authenticated(client: TestClient) -> None:
    client.cookies.set("access_token", "test-jwt")
    response = client.get("/login", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"
    client.cookies.clear()


def test_logout(client: TestClient) -> None:
    response = client.post("/logout", follow_redirects=False)
    assert response.status_code == 303
    assert "/oauth2/sign_out" in response.headers["location"]


# --- Dashboard ---


def test_landing_page_public(client: TestClient) -> None:
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 200
    assert "Spotify MCP" in response.text


def test_dashboard_requires_login(client: TestClient) -> None:
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_dashboard_page(client: TestClient, mock_api: AsyncMock) -> None:
    client.cookies.set("access_token", "test-jwt")
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "150" in response.text  # total_plays
    assert "Test Artist" in response.text
    assert "Test Track" in response.text
    mock_api.get_dashboard.assert_called_once_with("test-jwt")
    client.cookies.clear()


def test_dashboard_api_error(client: TestClient, mock_api: AsyncMock) -> None:
    mock_api.get_dashboard.side_effect = ApiError(500, "Server error")
    client.cookies.set("access_token", "test-jwt")
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "Server error" in response.text
    client.cookies.clear()


def test_dashboard_401_redirects_to_login(client: TestClient, mock_api: AsyncMock) -> None:
    mock_api.get_dashboard.side_effect = ApiError(401, "Unauthorized")
    client.cookies.set("access_token", "expired-jwt")
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    client.cookies.clear()


# --- History ---


def test_history_requires_login(client: TestClient) -> None:
    response = client.get("/history/", follow_redirects=False)
    assert response.status_code == 303


def test_history_page(client: TestClient, mock_api: AsyncMock) -> None:
    client.cookies.set("access_token", "test-jwt")
    response = client.get("/history/")
    assert response.status_code == 200
    assert "History" in response.text
    assert "Test Track" in response.text
    mock_api.get_history.assert_called_once_with("test-jwt", limit=50, offset=0, q=None)
    client.cookies.clear()


def test_history_with_search(client: TestClient, mock_api: AsyncMock) -> None:
    client.cookies.set("access_token", "test-jwt")
    response = client.get("/history/?q=test")
    assert response.status_code == 200
    mock_api.get_history.assert_called_once_with("test-jwt", limit=50, offset=0, q="test")
    client.cookies.clear()


def test_history_table_partial(client: TestClient, mock_api: AsyncMock) -> None:
    client.cookies.set("access_token", "test-jwt")
    response = client.get("/history/partials/history-table?limit=10&offset=20")
    assert response.status_code == 200
    mock_api.get_history.assert_called_once_with("test-jwt", limit=10, offset=20, q=None)
    client.cookies.clear()


# --- Playlists ---


def test_playlists_requires_login(client: TestClient) -> None:
    response = client.get("/playlists/", follow_redirects=False)
    assert response.status_code == 303


def test_playlists_page(client: TestClient, mock_api: AsyncMock) -> None:
    client.cookies.set("access_token", "test-jwt")
    response = client.get("/playlists/")
    assert response.status_code == 200
    assert "My Playlist" in response.text
    assert "5 tracks" in response.text
    mock_api.get_playlists.assert_called_once_with("test-jwt")
    client.cookies.clear()


def test_playlist_detail(client: TestClient, mock_api: AsyncMock) -> None:
    client.cookies.set("access_token", "test-jwt")
    response = client.get("/playlists/pl_123")
    assert response.status_code == 200
    assert "My Playlist" in response.text
    assert "Track 1" in response.text
    mock_api.get_playlist.assert_called_once_with("test-jwt", "pl_123")
    client.cookies.clear()


def test_playlist_detail_api_error(client: TestClient, mock_api: AsyncMock) -> None:
    mock_api.get_playlist.side_effect = ApiError(404, "Not found")
    client.cookies.set("access_token", "test-jwt")
    response = client.get("/playlists/nonexistent")
    assert response.status_code == 200
    assert "Not found" in response.text
    client.cookies.clear()


# --- Taste Profile ---


def test_taste_requires_login(client: TestClient) -> None:
    response = client.get("/taste", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_taste_page(client: TestClient, mock_api: AsyncMock) -> None:
    client.cookies.set("access_token", "test-jwt")
    response = client.get("/taste")
    assert response.status_code == 200
    assert "Taste Profile" in response.text
    assert "symphonic metal" in response.text
    assert "power metal" in response.text
    assert "pop" in response.text  # avoid list
    mock_api.get_taste_profile.assert_called_once_with("test-jwt")
    client.cookies.clear()


def test_taste_page_empty_profile(client: TestClient, mock_api: AsyncMock) -> None:
    mock_api.get_taste_profile.return_value = {
        "profile": {"user_id": 1, "profile": {}, "version": 0, "updated_at": None},
        "recent_events": [],
    }
    client.cookies.set("access_token", "test-jwt")
    response = client.get("/taste")
    assert response.status_code == 200
    assert "No taste profile yet" in response.text
    client.cookies.clear()


def test_taste_page_api_error(client: TestClient, mock_api: AsyncMock) -> None:
    mock_api.get_taste_profile.side_effect = ApiError(500, "Server error")
    client.cookies.set("access_token", "test-jwt")
    response = client.get("/taste")
    assert response.status_code == 200
    assert "Server error" in response.text
    client.cookies.clear()


def test_taste_page_401_redirects(client: TestClient, mock_api: AsyncMock) -> None:
    mock_api.get_taste_profile.side_effect = ApiError(401, "Unauthorized")
    client.cookies.set("access_token", "expired-jwt")
    response = client.get("/taste", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    client.cookies.clear()


def test_taste_update_add_genre(client: TestClient, mock_api: AsyncMock) -> None:
    client.cookies.set("access_token", "test-jwt")
    response = client.post(
        "/taste/update",
        data={"action": "add", "field": "core_genres", "value": "melodic death metal"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/taste"
    # Should have fetched current profile then called update
    mock_api.get_taste_profile.assert_called_once_with("test-jwt")
    mock_api.update_taste_profile.assert_called_once()
    call_args = mock_api.update_taste_profile.call_args
    patch = call_args[0][1]  # second positional arg
    assert "melodic death metal" in patch["core_genres"]
    client.cookies.clear()


def test_taste_update_remove_genre(client: TestClient, mock_api: AsyncMock) -> None:
    client.cookies.set("access_token", "test-jwt")
    response = client.post(
        "/taste/update",
        data={"action": "remove", "field": "core_genres", "value": "power metal"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    mock_api.update_taste_profile.assert_called_once()
    call_args = mock_api.update_taste_profile.call_args
    patch = call_args[0][1]
    assert "power metal" not in patch["core_genres"]
    assert "symphonic metal" in patch["core_genres"]
    client.cookies.clear()


def test_taste_update_set_value(client: TestClient, mock_api: AsyncMock) -> None:
    client.cookies.set("access_token", "test-jwt")
    response = client.post(
        "/taste/update",
        data={"action": "set", "field": "mood", "value": "dark"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    mock_api.update_taste_profile.assert_called_once()
    call_args = mock_api.update_taste_profile.call_args
    patch = call_args[0][1]
    assert patch["mood"] == "dark"
    client.cookies.clear()


def test_taste_update_requires_login(client: TestClient) -> None:
    response = client.post("/taste/update", data={"action": "add", "field": "x", "value": "y"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_taste_clear(client: TestClient, mock_api: AsyncMock) -> None:
    client.cookies.set("access_token", "test-jwt")
    response = client.post("/taste/clear", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/taste"
    mock_api.clear_taste_profile.assert_called_once_with("test-jwt")
    client.cookies.clear()


def test_taste_clear_requires_login(client: TestClient) -> None:
    response = client.post("/taste/clear", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_taste_events_partial(client: TestClient, mock_api: AsyncMock) -> None:
    client.cookies.set("access_token", "test-jwt")
    response = client.get("/taste/partials/events?limit=10&offset=0")
    assert response.status_code == 200
    mock_api.get_preference_events.assert_called_once_with("test-jwt", limit=10, offset=0)
    client.cookies.clear()


def test_taste_events_partial_requires_login(client: TestClient) -> None:
    response = client.get("/taste/partials/events", follow_redirects=False)
    assert response.status_code == 303


# --- Dashboard taste integration ---


def test_dashboard_shows_taste_summary(client: TestClient, mock_api: AsyncMock) -> None:
    client.cookies.set("access_token", "test-jwt")
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "symphonic metal" in response.text
    assert "power metal" in response.text
    mock_api.get_taste_profile.assert_called_once_with("test-jwt")
    client.cookies.clear()


def test_dashboard_taste_api_error_graceful(client: TestClient, mock_api: AsyncMock) -> None:
    """Dashboard still loads even if taste profile API fails."""
    mock_api.get_taste_profile.side_effect = ApiError(500, "Taste error")
    client.cookies.set("access_token", "test-jwt")
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "150" in response.text  # Dashboard data still renders
    client.cookies.clear()
