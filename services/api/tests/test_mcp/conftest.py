"""Shared fixtures for MCP tool tests."""

from unittest.mock import AsyncMock, patch

import pytest

from app.middleware import RateLimitMiddleware


@pytest.fixture(autouse=True)
def _mock_force_refresh_token() -> None:
    """Prevent _force_refresh_token from calling TokenManager with lru-cached prod settings.

    Tests mock _get_client at the method level so real token I/O never happens.
    _force_refresh_token must also be a no-op so it doesn't fail with the
    invalid Fernet key that lru_cache returns in the test environment.
    """
    with patch(
        "app.mcp.tools.playlist_tools.PlaylistToolHandlers._force_refresh_token",
        new_callable=AsyncMock,
        return_value="mocked_fresh_token",
    ):
        yield


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> None:
    """Clear rate limiter state between tests to prevent cross-test 429s.

    The RateLimitMiddleware stores hits in an in-memory dict that persists
    across tests since the ``app`` object is a module-level singleton.
    """
    # Walk the ASGI middleware stack to find the RateLimitMiddleware instance
    from app.main import app

    current = getattr(app, "middleware_stack", None)
    while current is not None:
        if isinstance(current, RateLimitMiddleware):
            current._hits.clear()
            return
        current = getattr(current, "app", None)
