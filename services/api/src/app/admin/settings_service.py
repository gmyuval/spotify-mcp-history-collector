"""Admin-configurable settings service with in-process TTL cache.

Settings are stored in the ``app_settings`` DB table and cached in memory
for :attr:`SettingsService._CACHE_TTL` seconds to avoid per-request DB
queries. Falls back to :attr:`SettingsService.DEFAULTS` when the DB row
is absent or unreachable.
"""

import logging
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models.settings import AppSetting

logger = logging.getLogger(__name__)

# (default_value, description, category)
_SettingDef = tuple[Any, str, str]


class SettingsService:
    """DB-backed key-value settings store with an in-process TTL cache.

    Usage::

        value = await _settings_service.get("search.default_limit", 25, session)
        await _settings_service.set("search.default_limit", 10, session)

    The in-memory cache is per-process (not shared across workers), but the
    5-minute TTL means drift between workers is bounded and acceptable for
    operational tunables.
    """

    _CACHE_TTL: float = 300.0  # seconds

    #: Minimum allowed values for integer settings (None = no lower bound).
    _INT_BOUNDS: dict[str, int] = {
        "search.max_query_length": 1,
        "search.default_limit": 1,
        "search.max_limit": 1,
        "search.snippet_max_length": 1,
        "explorer.playlist_cache_ttl_minutes": 1,
        "explorer.playlist_fetch_max": 1,
        "explorer.enrichment_cache_ttl_seconds": 1,
        "playlist.snapshot_compaction_threshold": 1,
        "playlist.default_page_size": 1,
        "playlist.max_page_size": 1,
        "playlist.recent_events_limit": 0,
    }

    #: Minimum allowed values for float settings (None = no lower bound).
    _FLOAT_BOUNDS: dict[str, float] = {
        "search.score_playlist_name": 0.0,
        "search.score_playlist_description": 0.0,
        "search.score_playlist_tags": 0.0,
        "search.score_preference_event": 0.0,
        "search.score_profile": 0.0,
    }

    #: Canonical defaults — authoritative source of truth for all settings.
    #: (default_value, human-readable description, category)
    DEFAULTS: dict[str, _SettingDef] = {
        # ── Search ────────────────────────────────────────────────────
        "search.max_query_length": (500, "Maximum allowed length for search queries", "search"),
        "search.default_limit": (25, "Default number of results returned by memory.search", "search"),
        "search.max_limit": (200, "Maximum results allowed per memory.search call", "search"),
        "search.snippet_max_length": (100, "Maximum characters in a result snippet", "search"),
        "search.score_playlist_name": (1.0, "Relevance score weight for playlist name matches", "search"),
        "search.score_playlist_description": (
            0.8,
            "Relevance score weight for playlist description matches",
            "search",
        ),
        "search.score_playlist_tags": (0.7, "Relevance score weight for playlist tag matches", "search"),
        "search.score_preference_event": (
            0.5,
            "Relevance score weight for preference event matches",
            "search",
        ),
        "search.score_profile": (0.3, "Relevance score weight for taste profile matches", "search"),
        # ── Explorer ──────────────────────────────────────────────────
        "explorer.playlist_cache_ttl_minutes": (
            60,
            "Minutes before the playlist list cache is considered stale and auto-refreshed",
            "explorer",
        ),
        "explorer.playlist_fetch_max": (
            500,
            "Safety cap: maximum number of playlists to fetch from Spotify",
            "explorer",
        ),
        "explorer.enrichment_cache_ttl_seconds": (
            86400,
            "Seconds to cache Spotify enrichment data (track/artist/album detail pages)",
            "explorer",
        ),
        # ── Playlist ledger ───────────────────────────────────────────
        "playlist.snapshot_compaction_threshold": (10, "Auto-snapshot created every N mutations", "playlist"),
        "playlist.default_page_size": (50, "Default page size for memory.get_playlists", "playlist"),
        "playlist.max_page_size": (200, "Maximum page size for memory.get_playlists", "playlist"),
        "playlist.recent_events_limit": (
            50,
            "Default number of events included in memory.get_playlist",
            "playlist",
        ),
    }

    def __init__(self) -> None:
        # Cache: key → (value, expiry_monotonic_time)
        self._cache: dict[str, tuple[Any, float]] = {}

    # ── Public API ────────────────────────────────────────────────────

    async def get(self, key: str, default: Any, session: AsyncSession) -> Any:
        """Return the current value for *key*, using cache then DB then default."""
        cached = self._cache.get(key)
        if cached is not None:
            value, expires_at = cached
            if time.monotonic() < expires_at:
                return value
            # Expired — evict
            del self._cache[key]

        try:
            row = await session.get(AppSetting, key)
        except Exception:
            logger.warning("settings: DB lookup failed for %r — using default", key)
            return default

        if row is None:
            return default

        self._cache[key] = (row.value_json, time.monotonic() + self._CACHE_TTL)
        return row.value_json

    def _validate_value_type(self, key: str, value: Any) -> Any:
        """Validate and coerce *value* to match the type of the hardcoded default for *key*."""
        expected_default, _, _ = self.DEFAULTS[key]
        expected = type(expected_default)
        if expected is bool:
            if not isinstance(value, bool):
                raise ValueError(f"Setting {key!r} expects a boolean, got {type(value).__name__!r}")
            return value
        if expected is int:
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"Setting {key!r} expects an integer, got {type(value).__name__!r}")
            min_v = self._INT_BOUNDS.get(key)
            if min_v is not None and value < min_v:
                raise ValueError(f"Setting {key!r} must be >= {min_v}, got {value}")
            return value
        if expected is float:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                fv = float(value)
                min_v_f = self._FLOAT_BOUNDS.get(key)
                if min_v_f is not None and fv < min_v_f:
                    raise ValueError(f"Setting {key!r} must be >= {min_v_f}, got {fv}")
                return fv
            raise ValueError(f"Setting {key!r} expects a number, got {type(value).__name__!r}")
        if not isinstance(value, expected):
            raise ValueError(f"Setting {key!r} expects {expected.__name__!r}, got {type(value).__name__!r}")
        return value

    async def set(self, key: str, value: Any, session: AsyncSession) -> AppSetting:
        """Upsert *key* to *value* in the DB and invalidate the cache entry."""
        if key not in self.DEFAULTS:
            raise KeyError(f"Unknown setting key: {key!r}")

        value = self._validate_value_type(key, value)
        _, description, category = self.DEFAULTS[key]

        # Use PostgreSQL upsert; fall back to merge for SQLite (tests)
        dialect = session.bind.dialect.name if session.bind else "postgresql"
        if dialect == "postgresql":
            stmt = (
                pg_insert(AppSetting)
                .values(key=key, value_json=value, description=description, category=category)
                .on_conflict_do_update(
                    index_elements=["key"],
                    set_={
                        "value_json": value,
                        "description": description,
                        "category": category,
                    },
                )
                .returning(AppSetting)
            )
            result = await session.execute(stmt)
            row: AppSetting = result.scalar_one()
        else:
            # SQLite path (tests): get-or-create then update
            row_or_none = await session.get(AppSetting, key)
            if row_or_none is None:
                row = AppSetting(key=key, value_json=value, description=description, category=category)
                session.add(row)
            else:
                row_or_none.value_json = value
                row = row_or_none
            await session.flush()

        self.invalidate_cache(key)
        return row

    async def get_all(self, session: AsyncSession, category: str | None = None) -> list[AppSetting]:
        """Return all settings rows, optionally filtered by *category*."""
        stmt = select(AppSetting).order_by(AppSetting.category, AppSetting.key)
        if category is not None:
            stmt = stmt.where(AppSetting.category == category)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def reset_to_default(self, key: str | None, session: AsyncSession) -> int:
        """Reset one or all settings to their hardcoded defaults.

        Returns the number of rows affected.
        """
        keys_to_reset = [key] if key is not None else list(self.DEFAULTS.keys())
        count = 0
        for k in keys_to_reset:
            if k not in self.DEFAULTS:
                raise KeyError(f"Unknown setting key: {k!r}")
            default_value, description, category = self.DEFAULTS[k]
            await self.set(k, default_value, session)
            count += 1
        return count

    def invalidate_cache(self, key: str | None = None) -> None:
        """Evict *key* from cache, or clear the entire cache if *key* is None."""
        if key is None:
            self._cache.clear()
        else:
            self._cache.pop(key, None)

    def default_value(self, key: str) -> Any:
        """Return the hardcoded default value for *key*."""
        return self.DEFAULTS[key][0]


# Module-level singleton — imported by tool handlers and admin router.
_settings_service = SettingsService()
