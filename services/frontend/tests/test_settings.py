"""Tests for admin settings frontend routes."""

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from frontend.api_client import ApiError

# ── GET /admin/settings ──────────────────────────────────────────────────────


def test_settings_page_loads(client: TestClient, mock_api: AsyncMock) -> None:
    response = client.get("/admin/settings")
    assert response.status_code == 200
    assert "Settings" in response.text
    mock_api.list_settings.assert_called_once()


def test_settings_page_shows_categories(client: TestClient, mock_api: AsyncMock) -> None:
    response = client.get("/admin/settings")
    assert response.status_code == 200
    assert "search" in response.text.lower()
    assert "playlist" in response.text.lower()


def test_settings_page_shows_keys(client: TestClient, mock_api: AsyncMock) -> None:
    response = client.get("/admin/settings")
    assert response.status_code == 200
    assert "search.default_limit" in response.text
    assert "playlist.snapshot_compaction_threshold" in response.text


def test_settings_page_api_error_shows_message(client: TestClient, mock_api: AsyncMock) -> None:
    mock_api.list_settings.side_effect = ApiError(503, "Service unavailable")
    response = client.get("/admin/settings")
    assert response.status_code == 200
    assert "Service unavailable" in response.text


# ── POST /admin/settings/{key} ───────────────────────────────────────────────


def test_update_setting_success(client: TestClient, mock_api: AsyncMock) -> None:
    response = client.post("/admin/settings/search.default_limit", data={"value": "10"})
    assert response.status_code == 200
    mock_api.update_setting.assert_called_once_with("search.default_limit", 10)
    assert "Saved" in response.text


def test_update_setting_parses_float(client: TestClient, mock_api: AsyncMock) -> None:
    mock_api.update_setting.return_value = {
        "key": "search.score_playlist_name",
        "value_json": 0.5,
        "default_value": 1.0,
        "description": "Score weight",
        "category": "search",
        "updated_at": "2024-01-01T00:00:00",
    }
    response = client.post("/admin/settings/search.score_playlist_name", data={"value": "0.5"})
    assert response.status_code == 200
    mock_api.update_setting.assert_called_once_with("search.score_playlist_name", 0.5)


def test_update_setting_falls_back_to_string(client: TestClient, mock_api: AsyncMock) -> None:
    mock_api.update_setting.return_value = {
        "key": "some.key",
        "value_json": "hello",
        "default_value": "hello",
        "description": "",
        "category": "search",
        "updated_at": "2024-01-01T00:00:00",
    }
    response = client.post("/admin/settings/some.key", data={"value": "hello"})
    assert response.status_code == 200
    mock_api.update_setting.assert_called_once_with("some.key", "hello")


def test_update_setting_api_error_shows_flash(client: TestClient, mock_api: AsyncMock) -> None:
    mock_api.update_setting.side_effect = ApiError(404, "Unknown setting key")
    response = client.post("/admin/settings/no.such.key", data={"value": "1"})
    assert response.status_code == 200
    assert "Unknown setting key" in response.text


# ── POST /admin/settings/{key}/reset ────────────────────────────────────────


def test_reset_setting_success(client: TestClient, mock_api: AsyncMock) -> None:
    response = client.post("/admin/settings/search.default_limit/reset")
    assert response.status_code == 200
    mock_api.reset_settings.assert_called_once_with(key="search.default_limit")
    mock_api.list_settings.assert_called()
    assert "Reset to default" in response.text


def test_reset_setting_api_error(client: TestClient, mock_api: AsyncMock) -> None:
    mock_api.reset_settings.side_effect = ApiError(404, "Unknown setting key")
    response = client.post("/admin/settings/no.such.key/reset")
    assert response.status_code == 200
    assert "Unknown setting key" in response.text
