"""Tests for JWTAuthMiddleware."""

from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.auth.jwt import JWTService
from app.auth.middleware import JWTAuthMiddleware
from app.settings import AppSettings, get_settings

TEST_KEY = Fernet.generate_key().decode()


def _test_settings() -> AppSettings:
    return AppSettings(
        SPOTIFY_CLIENT_ID="test",
        SPOTIFY_CLIENT_SECRET="test",
        TOKEN_ENCRYPTION_KEY=TEST_KEY,
        JWT_COOKIE_SECURE=False,
    )


def _create_test_app() -> FastAPI:
    """Create a minimal FastAPI app with JWTAuthMiddleware and a test endpoint."""
    test_app = FastAPI()
    test_app.add_middleware(JWTAuthMiddleware)
    test_app.dependency_overrides[get_settings] = _test_settings

    @test_app.get("/test-auth")
    async def test_auth(request: Request) -> dict[str, Any]:
        return {"user_id": getattr(request.state, "user_id", None)}

    @test_app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return test_app


@pytest.fixture
def jwt_service() -> JWTService:
    return JWTService(_test_settings())


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # The middleware calls get_settings() directly (not via DI), so we
    # must monkeypatch it at the module level for the test key to match.
    monkeypatch.setattr("app.auth.middleware.get_settings", _test_settings)
    return TestClient(_create_test_app())


def test_no_token_sets_user_id_none(client: TestClient) -> None:
    """Request without any token sets user_id to None."""
    resp = client.get("/test-auth")
    assert resp.status_code == 200
    assert resp.json()["user_id"] is None


def test_valid_bearer_jwt_sets_user_id(client: TestClient, jwt_service: JWTService) -> None:
    """Valid Bearer JWT sets user_id on request.state."""
    token = jwt_service.create_access_token(42)
    resp = client.get("/test-auth", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["user_id"] == 42


def test_valid_cookie_sets_user_id(client: TestClient, jwt_service: JWTService) -> None:
    """Valid access_token cookie sets user_id."""
    token = jwt_service.create_access_token(99)
    resp = client.get("/test-auth", cookies={"access_token": token})
    assert resp.status_code == 200
    assert resp.json()["user_id"] == 99


def test_bearer_takes_precedence_over_cookie(client: TestClient, jwt_service: JWTService) -> None:
    """Bearer header takes precedence when both are present."""
    bearer_token = jwt_service.create_access_token(10)
    cookie_token = jwt_service.create_access_token(20)
    resp = client.get(
        "/test-auth",
        headers={"Authorization": f"Bearer {bearer_token}"},
        cookies={"access_token": cookie_token},
    )
    assert resp.status_code == 200
    assert resp.json()["user_id"] == 10


def test_expired_jwt_sets_user_id_none(client: TestClient) -> None:
    """Expired JWT doesn't reject — sets user_id to None."""
    from datetime import UTC, datetime, timedelta

    import jwt as pyjwt

    payload = {
        "sub": "1",
        "type": "access",
        "iat": datetime.now(UTC) - timedelta(hours=2),
        "exp": datetime.now(UTC) - timedelta(hours=1),
    }
    token = pyjwt.encode(payload, TEST_KEY, algorithm="HS256")
    resp = client.get("/test-auth", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["user_id"] is None


def test_invalid_jwt_sets_user_id_none(client: TestClient) -> None:
    """Invalid JWT (bad signature) doesn't reject — sets user_id to None."""
    other_key = Fernet.generate_key().decode()
    other_svc = JWTService(
        AppSettings(
            SPOTIFY_CLIENT_ID="test",
            SPOTIFY_CLIENT_SECRET="test",
            TOKEN_ENCRYPTION_KEY=other_key,
        )
    )
    token = other_svc.create_access_token(1)
    resp = client.get("/test-auth", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["user_id"] is None


def test_admin_token_not_parsed_as_jwt(client: TestClient) -> None:
    """Static admin token (no dots) is not treated as JWT."""
    resp = client.get("/test-auth", headers={"Authorization": "Bearer admin-static-token-no-dots"})
    assert resp.status_code == 200
    assert resp.json()["user_id"] is None


def test_skip_paths_not_processed(client: TestClient) -> None:
    """Skipped paths (/healthz) bypass JWT processing."""
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
