"""OAuth state parameter management for CSRF protection."""

import hashlib
import hmac
import time


class OAuthStateManager:
    """Generates and verifies HMAC-signed OAuth state parameters.

    The state is a timestamp-based token signed with HMAC-SHA256.
    This provides stateless CSRF protection without server-side session storage.
    """

    def __init__(self, key: str, ttl_seconds: int) -> None:
        self._key = key
        self._ttl_seconds = ttl_seconds

    def generate(self, payload: str = "") -> str:
        """Generate a signed state parameter, optionally embedding *payload*.

        The state format is ``{timestamp}:{payload}.{signature}`` when a payload
        is provided, or ``{timestamp}.{signature}`` without one.  The HMAC
        covers the data portion (everything before the dot), ensuring the
        payload cannot be tampered with.
        """
        ts = str(int(time.time()))
        data = f"{ts}:{payload}" if payload else ts
        sig = self._sign(data)
        return f"{data}.{sig}"

    def verify(self, state: str) -> bool:
        """Verify the HMAC signature and TTL of a state parameter."""
        parts = state.split(".", 1)
        if len(parts) != 2:
            return False
        data, sig = parts
        if not hmac.compare_digest(sig, self._sign(data)):
            return False
        ts_str = data.split(":", 1)[0]
        try:
            ts = int(ts_str)
        except ValueError:
            return False
        return (time.time() - ts) <= self._ttl_seconds

    def extract_payload(self, state: str) -> str | None:
        """Extract the embedded payload from a verified state token.

        Returns ``None`` if the state has no payload or is invalid.
        Callers should call :meth:`verify` first to ensure the state is valid.
        """
        parts = state.split(".", 1)
        if len(parts) != 2:
            return None
        data = parts[0]
        if ":" in data:
            payload = data.split(":", 1)[1]
            return payload or None
        return None

    def _sign(self, data: str) -> str:
        """Create an HMAC-SHA256 signature for the given data."""
        return hmac.new(self._key.encode(), data.encode(), hashlib.sha256).hexdigest()
