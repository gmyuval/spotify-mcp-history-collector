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
    assert "Login with Spotify" in response.text


def test_login_page_redirects_when_authenticated(client: TestClient) -> None:
    client.cookies.set("access_token", "test-jwt")
    response = client.get("/login", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    client.cookies.clear()


def test_login_redirect(client: TestClient) -> None:
    response = client.get("/login/redirect", follow_redirects=False)
    assert response.status_code == 303
    location = response.headers["location"]
    assert "http://test-api:8000/auth/login" in location
    assert "next=" in location


def test_logout(client: TestClient) -> None:
    response = client.get("/logout", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


# --- Dashboard ---


def test_dashboard_requires_login(client: TestClient) -> None:
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_dashboard_page(client: TestClient, mock_api: AsyncMock) -> None:
    client.cookies.set("access_token", "test-jwt")
    response = client.get("/")
    assert response.status_code == 200
    assert "150" in response.text  # total_plays
    assert "Test Artist" in response.text
    assert "Test Track" in response.text
    mock_api.get_dashboard.assert_called_once_with("test-jwt")
    client.cookies.clear()


def test_dashboard_api_error(client: TestClient, mock_api: AsyncMock) -> None:
    mock_api.get_dashboard.side_effect = ApiError(500, "Server error")
    client.cookies.set("access_token", "test-jwt")
    response = client.get("/")
    assert response.status_code == 200
    assert "Server error" in response.text
    client.cookies.clear()


def test_dashboard_401_redirects_to_login(client: TestClient, mock_api: AsyncMock) -> None:
    mock_api.get_dashboard.side_effect = ApiError(401, "Unauthorized")
    client.cookies.set("access_token", "expired-jwt")
    response = client.get("/", follow_redirects=False)
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
