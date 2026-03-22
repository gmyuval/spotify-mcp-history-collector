"""Tests for analytics page routes."""

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
    # Time-window pills
    assert "7d" in response.text
    assert "90d" in response.text
    client.cookies.clear()
