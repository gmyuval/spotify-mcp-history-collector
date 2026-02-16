"""Tests for JWTService — token creation and validation."""

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt as pyjwt
import pytest
from cryptography.fernet import Fernet

from app.auth.jwt import JWTExpiredError, JWTInvalidError, JWTService
from app.settings import AppSettings

TEST_KEY = Fernet.generate_key().decode()


def _test_settings(**overrides: Any) -> AppSettings:
    return AppSettings(
        SPOTIFY_CLIENT_ID="test",
        SPOTIFY_CLIENT_SECRET="test",
        TOKEN_ENCRYPTION_KEY=TEST_KEY,
        **overrides,
    )


def _service(**overrides: Any) -> JWTService:
    return JWTService(_test_settings(**overrides))


def test_create_and_decode_access_token() -> None:
    """Access token round-trips through create and decode."""
    svc = _service()
    token = svc.create_access_token(42)
    assert svc.decode_access_token(token) == 42


def test_create_and_decode_refresh_token() -> None:
    """Refresh token round-trips through create and decode."""
    svc = _service()
    token = svc.create_refresh_token(99)
    assert svc.decode_refresh_token(token) == 99


def test_create_token_pair() -> None:
    """create_token_pair returns two distinct tokens."""
    svc = _service()
    access, refresh = svc.create_token_pair(7)
    assert access != refresh
    assert svc.decode_access_token(access) == 7
    assert svc.decode_refresh_token(refresh) == 7


def test_decode_access_rejects_refresh_token() -> None:
    """Passing a refresh token to decode_access_token raises JWTInvalidError."""
    svc = _service()
    refresh = svc.create_refresh_token(1)
    with pytest.raises(JWTInvalidError, match="not an access token"):
        svc.decode_access_token(refresh)


def test_decode_refresh_rejects_access_token() -> None:
    """Passing an access token to decode_refresh_token raises JWTInvalidError."""
    svc = _service()
    access = svc.create_access_token(1)
    with pytest.raises(JWTInvalidError, match="not a refresh token"):
        svc.decode_refresh_token(access)


def test_expired_access_token() -> None:
    """Expired access token raises JWTExpiredError."""
    svc = _service(JWT_ACCESS_TOKEN_EXPIRE_MINUTES=0)
    # Manually create a token with past expiry
    payload = {
        "sub": "1",
        "type": "access",
        "iat": datetime.now(UTC) - timedelta(hours=1),
        "exp": datetime.now(UTC) - timedelta(seconds=1),
    }
    token = pyjwt.encode(payload, TEST_KEY, algorithm="HS256")
    with pytest.raises(JWTExpiredError, match="expired"):
        svc.decode_access_token(token)


def test_expired_refresh_token() -> None:
    """Expired refresh token raises JWTExpiredError."""
    svc = _service()
    payload = {
        "sub": "1",
        "type": "refresh",
        "iat": datetime.now(UTC) - timedelta(days=30),
        "exp": datetime.now(UTC) - timedelta(seconds=1),
    }
    token = pyjwt.encode(payload, TEST_KEY, algorithm="HS256")
    with pytest.raises(JWTExpiredError, match="expired"):
        svc.decode_refresh_token(token)


def test_invalid_signature() -> None:
    """Token signed with a different key raises JWTInvalidError."""
    svc = _service()
    other_key = Fernet.generate_key().decode()
    payload = {"sub": "1", "type": "access", "exp": datetime.now(UTC) + timedelta(hours=1)}
    token = pyjwt.encode(payload, other_key, algorithm="HS256")
    with pytest.raises(JWTInvalidError, match="Invalid token"):
        svc.decode_access_token(token)


def test_malformed_token() -> None:
    """Garbage string raises JWTInvalidError."""
    svc = _service()
    with pytest.raises(JWTInvalidError, match="Invalid token"):
        svc.decode_access_token("not.a.jwt")


def test_missing_sub_claim() -> None:
    """Token without 'sub' claim raises JWTInvalidError."""
    svc = _service()
    payload = {"type": "access", "exp": datetime.now(UTC) + timedelta(hours=1)}
    token = pyjwt.encode(payload, TEST_KEY, algorithm="HS256")
    with pytest.raises(JWTInvalidError, match="missing 'sub' claim"):
        svc.decode_access_token(token)


def test_access_expire_seconds() -> None:
    """access_expire_seconds returns minutes * 60."""
    svc = _service(JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30)
    assert svc.access_expire_seconds == 1800


def test_refresh_expire_seconds() -> None:
    """refresh_expire_seconds returns days * 86400."""
    svc = _service(JWT_REFRESH_TOKEN_EXPIRE_DAYS=14)
    assert svc.refresh_expire_seconds == 14 * 86400


def test_cookie_domain_empty_returns_none() -> None:
    """Empty JWT_COOKIE_DOMAIN returns None."""
    svc = _service(JWT_COOKIE_DOMAIN="")
    assert svc.cookie_domain is None


def test_cookie_domain_set() -> None:
    """Non-empty JWT_COOKIE_DOMAIN is returned."""
    svc = _service(JWT_COOKIE_DOMAIN=".example.com")
    assert svc.cookie_domain == ".example.com"
