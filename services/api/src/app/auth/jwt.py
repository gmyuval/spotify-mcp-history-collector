"""JWT token creation and validation."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from app.settings import AppSettings

logger = logging.getLogger(__name__)


class JWTError(Exception):
    """Base exception for JWT operations."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class JWTExpiredError(JWTError):
    """Token has expired."""


class JWTInvalidError(JWTError):
    """Token is invalid (bad signature, malformed, wrong type, etc.)."""


class JWTService:
    """Creates and validates JWT access and refresh tokens.

    Tokens are signed with HMAC-SHA256 using the application's
    TOKEN_ENCRYPTION_KEY.
    """

    ALGORITHM = "HS256"

    def __init__(self, settings: AppSettings) -> None:
        secret = settings.TOKEN_ENCRYPTION_KEY
        if not secret or not secret.strip():
            raise ValueError("TOKEN_ENCRYPTION_KEY must be set to a non-empty value for JWT signing")
        self._secret = secret
        self._access_expire_minutes = settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
        self._refresh_expire_days = settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS
        self._cookie_secure = settings.JWT_COOKIE_SECURE
        self._cookie_domain = settings.JWT_COOKIE_DOMAIN

    def create_access_token(self, user_id: int) -> str:
        """Create a short-lived access token for the given user."""
        now = datetime.now(UTC)
        payload: dict[str, Any] = {
            "sub": str(user_id),
            "type": "access",
            "iat": now,
            "exp": now + timedelta(minutes=self._access_expire_minutes),
        }
        return jwt.encode(payload, self._secret, algorithm=self.ALGORITHM)

    def create_refresh_token(self, user_id: int) -> str:
        """Create a long-lived refresh token for the given user."""
        now = datetime.now(UTC)
        payload: dict[str, Any] = {
            "sub": str(user_id),
            "type": "refresh",
            "iat": now,
            "exp": now + timedelta(days=self._refresh_expire_days),
        }
        return jwt.encode(payload, self._secret, algorithm=self.ALGORITHM)

    def create_token_pair(self, user_id: int) -> tuple[str, str]:
        """Create both access and refresh tokens. Returns (access, refresh)."""
        return self.create_access_token(user_id), self.create_refresh_token(user_id)

    def decode_access_token(self, token: str) -> int:
        """Decode and validate an access token. Returns user_id.

        Raises:
            JWTExpiredError: If the token has expired.
            JWTInvalidError: If the token is malformed, wrong type, or bad signature.
        """
        payload = self._decode(token)
        if payload.get("type") != "access":
            raise JWTInvalidError("Token is not an access token")
        return self._parse_sub(payload["sub"])

    def decode_refresh_token(self, token: str) -> int:
        """Decode and validate a refresh token. Returns user_id.

        Raises:
            JWTExpiredError: If the token has expired.
            JWTInvalidError: If the token is malformed, wrong type, or bad signature.
        """
        payload = self._decode(token)
        if payload.get("type") != "refresh":
            raise JWTInvalidError("Token is not a refresh token")
        return self._parse_sub(payload["sub"])

    @staticmethod
    def _parse_sub(sub: str) -> int:
        """Convert the ``sub`` claim to an integer user ID."""
        try:
            return int(sub)
        except (ValueError, TypeError) as exc:
            raise JWTInvalidError(f"Invalid 'sub' claim: {sub!r}") from exc

    @property
    def access_expire_seconds(self) -> int:
        """Access token lifetime in seconds (for cookie max-age)."""
        return self._access_expire_minutes * 60

    @property
    def refresh_expire_seconds(self) -> int:
        """Refresh token lifetime in seconds (for cookie max-age)."""
        return self._refresh_expire_days * 86400

    @property
    def cookie_secure(self) -> bool:
        """Whether cookies should have the Secure flag."""
        return self._cookie_secure

    @property
    def cookie_domain(self) -> str | None:
        """Cookie domain restriction, or None for no restriction."""
        return self._cookie_domain or None

    def _decode(self, token: str) -> dict[str, Any]:
        """Decode a JWT, raising typed exceptions on failure."""
        try:
            payload: dict[str, Any] = jwt.decode(token, self._secret, algorithms=[self.ALGORITHM])
        except jwt.ExpiredSignatureError as exc:
            raise JWTExpiredError("Token has expired") from exc
        except jwt.InvalidTokenError as exc:
            raise JWTInvalidError(f"Invalid token: {exc}") from exc

        if "sub" not in payload:
            raise JWTInvalidError("Token missing 'sub' claim")

        return payload
