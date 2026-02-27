"""Shared route helpers for the explorer frontend."""

from fastapi import Request
from fastapi.responses import RedirectResponse


def get_access_token(request: Request) -> str | None:
    """Extract access_token from cookies."""
    return request.cookies.get("access_token")


def require_login(request: Request) -> str | RedirectResponse:
    """Return access_token or a redirect to /login.

    Callers should check: if isinstance(result, RedirectResponse): return result
    """
    token = get_access_token(request)
    if token is None:
        return RedirectResponse(url="/login", status_code=303)
    return token


def safe_int(value: str | None, default: int) -> int:
    """Parse a string to int, returning default on failure."""
    if value is None:
        return default
    try:
        return int(value)
    except ValueError, TypeError:
        return default
