"""Shared helpers for route modules."""


def safe_int(value: str | None, default: int) -> int:
    """Parse *value* as an integer, returning *default* on failure."""
    if value is None:
        return default
    try:
        return int(value)
    except ValueError, TypeError:
        return default
