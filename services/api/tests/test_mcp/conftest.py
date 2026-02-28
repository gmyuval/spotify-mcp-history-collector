"""Shared fixtures for MCP tool tests."""

import pytest

from app.middleware import RateLimitMiddleware


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
