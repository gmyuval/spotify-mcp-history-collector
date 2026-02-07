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

    def generate(self) -> str:
        """Generate a signed state parameter containing the current timestamp."""
        ts = str(int(time.time()))
        sig = self._sign(ts)
        return f"{ts}.{sig}"

    def verify(self, state: str) -> bool:
        """Verify the HMAC signature and TTL of a state parameter."""
        parts = state.split(".", 1)
        if len(parts) != 2:
            return False
        ts_str, sig = parts
        if not hmac.compare_digest(sig, self._sign(ts_str)):
            return False
        try:
            ts = int(ts_str)
        except ValueError:
            return False
        return (time.time() - ts) <= self._ttl_seconds

    def _sign(self, timestamp: str) -> str:
        """Create an HMAC-SHA256 signature for the given timestamp."""
        return hmac.new(self._key.encode(), timestamp.encode(), hashlib.sha256).hexdigest()
