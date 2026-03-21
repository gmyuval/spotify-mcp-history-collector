"""CacheBackend protocol — the interface all cache implementations must follow."""

from typing import Any, Protocol


class CacheBackend(Protocol):
    """Async key-value cache with TTL support.

    Values are stored as dicts (JSON-serializable). Implementations handle
    serialization internally.
    """

    async def get(self, key: str) -> dict[str, Any] | None:
        """Return cached value or None if missing/expired."""
        ...

    async def set(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        """Store a value with the given TTL."""
        ...

    async def delete(self, key: str) -> None:
        """Remove a key from the cache."""
        ...

    async def close(self) -> None:
        """Release underlying connections."""
        ...
