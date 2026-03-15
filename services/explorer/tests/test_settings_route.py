"""Tests for settings/token management routes."""

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from explorer.api_client import ApiError


class TestTokensPage:
    def test_requires_login(self, client: TestClient) -> None:
        response = client.get("/settings/tokens", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_renders_tokens_page(self, client: TestClient, mock_api: AsyncMock) -> None:
        mock_api.get_tokens.return_value = {
            "items": [
                {
                    "token_id": 1,
                    "name": "Claude Desktop",
                    "prefix": "smcp_a1b",
                    "created_at": "2026-03-14T12:00:00",
                    "last_used_at": "2026-03-14T15:30:00",
                },
            ]
        }
        client.cookies.set("access_token", "test-jwt")
        response = client.get("/settings/tokens")
        assert response.status_code == 200
        assert "Claude Desktop" in response.text
        assert "smcp_a1b" in response.text
        mock_api.get_tokens.assert_called_once_with("test-jwt")
        client.cookies.clear()

    def test_empty_state(self, client: TestClient, mock_api: AsyncMock) -> None:
        mock_api.get_tokens.return_value = {"items": []}
        client.cookies.set("access_token", "test-jwt")
        response = client.get("/settings/tokens")
        assert response.status_code == 200
        assert "No API tokens yet" in response.text
        client.cookies.clear()

    def test_401_redirects_to_login(self, client: TestClient, mock_api: AsyncMock) -> None:
        mock_api.get_tokens.side_effect = ApiError(401, "Unauthorized")
        client.cookies.set("access_token", "test-jwt")
        response = client.get("/settings/tokens", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"
        client.cookies.clear()

    def test_shows_new_token(self, client: TestClient, mock_api: AsyncMock) -> None:
        mock_api.get_tokens.return_value = {"items": []}
        client.cookies.set("access_token", "test-jwt")
        response = client.get("/settings/tokens?new_token=smcp_abc123&new_token_name=Test")
        assert response.status_code == 200
        assert "smcp_abc123" in response.text
        assert "won't be shown again" in response.text.lower() or "won" in response.text
        client.cookies.clear()


class TestCreateToken:
    def test_requires_login(self, client: TestClient) -> None:
        response = client.post("/settings/tokens/create", data={"name": "Test"}, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_create_redirects_with_token(self, client: TestClient, mock_api: AsyncMock) -> None:
        mock_api.create_token.return_value = {
            "token_id": 1,
            "name": "My Token",
            "token": "smcp_newtoken123",
            "prefix": "smcp_new",
            "created_at": "2026-03-14T12:00:00",
        }
        client.cookies.set("access_token", "test-jwt")
        response = client.post("/settings/tokens/create", data={"name": "My Token"}, follow_redirects=False)
        assert response.status_code == 303
        assert "new_token=smcp_newtoken123" in response.headers["location"]
        mock_api.create_token.assert_called_once_with("test-jwt", "My Token")
        client.cookies.clear()

    def test_empty_name_redirects(self, client: TestClient, mock_api: AsyncMock) -> None:
        client.cookies.set("access_token", "test-jwt")
        response = client.post("/settings/tokens/create", data={"name": ""}, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/settings/tokens"
        mock_api.create_token.assert_not_called()
        client.cookies.clear()


class TestRevokeToken:
    def test_requires_login(self, client: TestClient) -> None:
        response = client.post("/settings/tokens/revoke", data={"token_id": "1"}, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_revoke_redirects(self, client: TestClient, mock_api: AsyncMock) -> None:
        mock_api.revoke_token.return_value = None
        client.cookies.set("access_token", "test-jwt")
        response = client.post("/settings/tokens/revoke", data={"token_id": "42"}, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/settings/tokens"
        mock_api.revoke_token.assert_called_once_with("test-jwt", 42)
        client.cookies.clear()
