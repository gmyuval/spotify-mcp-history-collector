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
    assert "hx-get" in response.text  # HTMX triggers present
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
