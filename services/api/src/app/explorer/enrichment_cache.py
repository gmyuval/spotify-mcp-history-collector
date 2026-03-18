"""In-memory TTL cache for Spotify API enrichment responses.

Replaced by Valkey CacheBackend in Phase 4b. The class-based design allows
reuse in tests and easy swapping of the backing store.
"""

import time
from typing import Any


class EnrichmentCache:
    """Simple in-memory TTL cache with capacity-based eviction.

    Parameters are constructor arguments so tests can override them and
    the production instance can use sensible defaults without external config.
    """

    def __init__(self, default_ttl: int = 86400, max_entries: int = 500) -> None:
        self._default_ttl = default_ttl  # 24 hours
        self._max_entries = max_entries
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        """Return cached value if present and not expired, else None."""
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() > expires_at:
            self._store.pop(key, None)
            return None
        return value

    def put(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Store a value with TTL. Evicts oldest entries if over capacity."""
        if len(self._store) >= self._max_entries:
            by_age = sorted(self._store.items(), key=lambda kv: kv[1][0])
            for k, _ in by_age[: len(self._store) - self._max_entries + 1]:
                self._store.pop(k, None)
        self._store[key] = (time.monotonic() + (ttl if ttl is not None else self._default_ttl), value)

    def clear(self) -> None:
        """Clear all cached entries."""
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)


# Module-level singleton used by the service layer.
cache = EnrichmentCache()
