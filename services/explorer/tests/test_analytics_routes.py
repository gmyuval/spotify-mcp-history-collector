"""Tests for analytics page routes."""

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

# --- Analytics page ---


def test_analytics_requires_login(client: TestClient) -> None:
    response = client.get("/analytics", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_analytics_page(client: TestClient) -> None:
    client.cookies.set("access_token", "test-jwt")
    response = client.get("/analytics")
    assert response.status_code == 200
    assert "Analytics" in response.text
    assert "Listening Heatmap" in response.text
    assert "Listening Timeline" in response.text
    assert "Genre Distribution" in response.text
    assert "Discovery Rate" in response.text
    assert "hx-get" in response.text  # HTMX triggers present
    assert "partials/genres" in response.text
    assert "partials/discovery" in response.text
    assert "7d" in response.text
    assert "90d" in response.text
    client.cookies.clear()


# --- Heatmap partial ---


def test_heatmap_partial_requires_login(client: TestClient) -> None:
    response = client.get("/analytics/partials/heatmap", follow_redirects=False)
    assert response.status_code == 303


def test_heatmap_partial(client: TestClient, mock_api: AsyncMock) -> None:
    mock_api.get_heatmap.return_value = {
        "cells": [
            {"weekday": 0, "hour": 10, "play_count": 5},
            {"weekday": 1, "hour": 14, "play_count": 3},
        ]
    }
    client.cookies.set("access_token", "test-jwt")
    response = client.get("/analytics/partials/heatmap?days=90")
    assert response.status_code == 200
    assert "heatmapChart" in response.text
    mock_api.get_heatmap.assert_called_once_with("test-jwt", days=90)
    client.cookies.clear()


def test_heatmap_partial_empty(client: TestClient, mock_api: AsyncMock) -> None:
    mock_api.get_heatmap.return_value = {"cells": []}
    client.cookies.set("access_token", "test-jwt")
    response = client.get("/analytics/partials/heatmap?days=7")
    assert response.status_code == 200
    assert "No listening data" in response.text
    client.cookies.clear()


# --- Timeline partial ---


def test_timeline_partial_requires_login(client: TestClient) -> None:
    response = client.get("/analytics/partials/timeline", follow_redirects=False)
    assert response.status_code == 303


def test_timeline_partial(client: TestClient, mock_api: AsyncMock) -> None:
    mock_api.get_timeline.return_value = {
        "buckets": [
            {"period": "2026-03-15", "play_count": 20, "ms_played": 4000000},
            {"period": "2026-03-22", "play_count": 15, "ms_played": 3000000},
        ],
        "bucket_size": "week",
    }
    client.cookies.set("access_token", "test-jwt")
    response = client.get("/analytics/partials/timeline?days=90&bucket=week")
    assert response.status_code == 200
    assert "timelineChart" in response.text
    mock_api.get_timeline.assert_called_once_with("test-jwt", days=90, bucket="week")
    client.cookies.clear()


def test_timeline_partial_empty(client: TestClient, mock_api: AsyncMock) -> None:
    mock_api.get_timeline.return_value = {"buckets": [], "bucket_size": "week"}
    client.cookies.set("access_token", "test-jwt")
    response = client.get("/analytics/partials/timeline?days=7")
    assert response.status_code == 200
    assert "No listening data" in response.text
    client.cookies.clear()


# --- Genres partial ---


def test_genres_partial_requires_login(client: TestClient) -> None:
    response = client.get("/analytics/partials/genres", follow_redirects=False)
    assert response.status_code == 303


def test_genres_partial(client: TestClient, mock_api: AsyncMock) -> None:
    mock_api.get_genres.return_value = {
        "genres": [
            {"genre": "rock", "play_count": 50, "artist_count": 3},
            {"genre": "indie", "play_count": 30, "artist_count": 2},
        ]
    }
    client.cookies.set("access_token", "test-jwt")
    response = client.get("/analytics/partials/genres?days=90")
    assert response.status_code == 200
    assert "genresChart" in response.text
    mock_api.get_genres.assert_called_once_with("test-jwt", days=90)
    client.cookies.clear()


def test_genres_partial_empty(client: TestClient, mock_api: AsyncMock) -> None:
    mock_api.get_genres.return_value = {"genres": []}
    client.cookies.set("access_token", "test-jwt")
    response = client.get("/analytics/partials/genres?days=7")
    assert response.status_code == 200
    assert "No genre data" in response.text
    client.cookies.clear()


# --- Discovery partial ---


def test_discovery_partial_requires_login(client: TestClient) -> None:
    response = client.get("/analytics/partials/discovery", follow_redirects=False)
    assert response.status_code == 303


def test_discovery_partial(client: TestClient, mock_api: AsyncMock) -> None:
    mock_api.get_discovery.return_value = {
        "days": [
            {"date": "2026-03-20", "new_tracks": 5, "repeat_tracks": 10},
            {"date": "2026-03-21", "new_tracks": 3, "repeat_tracks": 12},
        ]
    }
    client.cookies.set("access_token", "test-jwt")
    response = client.get("/analytics/partials/discovery?days=90")
    assert response.status_code == 200
    assert "discoveryChart" in response.text
    mock_api.get_discovery.assert_called_once_with("test-jwt", days=90)
    client.cookies.clear()


def test_discovery_partial_empty(client: TestClient, mock_api: AsyncMock) -> None:
    mock_api.get_discovery.return_value = {"days": []}
    client.cookies.set("access_token", "test-jwt")
    response = client.get("/analytics/partials/discovery?days=7")
    assert response.status_code == 200
    assert "No listening data" in response.text
    client.cookies.clear()
