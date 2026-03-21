"""PostgreSQL cache backend using the SpotifyEntityCache table."""

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from shared.db.models.cache import SpotifyEntityCache

logger = logging.getLogger(__name__)


class PostgresCacheBackend:
    """CacheBackend backed by the spotify_entity_cache table.

    Used as fallback when VALKEY_URL is not set, and in tests.
    Entity type is derived from the cache key prefix (e.g. "sp:track:..." -> "sp_track").
    The spotify_id column stores the full key for uniqueness.
    """

    def __init__(
        self,
        session_factory: Any,
    ) -> None:
        """Accept a callable that returns an async context manager yielding AsyncSession.

        Typed as Any because DatabaseManager.session is a bound method returning
        an AsyncGenerator, which is hard to express precisely without coupling to
        the DatabaseManager class itself.
        """
        self._session_factory: Any = session_factory

    async def get(self, key: str) -> dict[str, Any] | None:
        entity_type, spotify_id = self._parse_key(key)
        async with self._session_factory() as session:
            result = await session.execute(
                select(SpotifyEntityCache).where(
                    SpotifyEntityCache.entity_type == entity_type,
                    SpotifyEntityCache.spotify_id == spotify_id,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            try:
                parsed = json.loads(row.data_json)
            except json.JSONDecodeError, TypeError:
                return None
            if not isinstance(parsed, dict):
                return None
            data: dict[str, Any] = parsed
            ttl = data.pop("__ttl__", None)
            if ttl is not None:
                expires_at = row.fetched_at + timedelta(seconds=ttl)
                if datetime.now(UTC) > expires_at:
                    await session.execute(delete(SpotifyEntityCache).where(SpotifyEntityCache.id == row.id))
                    await session.commit()
                    return None
            return data

    async def set(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        entity_type, spotify_id = self._parse_key(key)
        data_with_ttl: dict[str, Any] = {**value, "__ttl__": ttl_seconds}
        data_json = json.dumps(data_with_ttl)
        now = datetime.now(UTC)

        async with self._session_factory() as session:
            dialect = session.bind.dialect.name if session.bind else "sqlite"
            if dialect == "postgresql":
                stmt = (
                    pg_insert(SpotifyEntityCache)
                    .values(
                        entity_type=entity_type,
                        spotify_id=spotify_id,
                        data_json=data_json,
                        fetched_at=now,
                    )
                    .on_conflict_do_update(
                        constraint="uq_entity_cache_type_id",
                        set_={"data_json": data_json, "fetched_at": now},
                    )
                )
                await session.execute(stmt)
            else:
                await session.execute(
                    delete(SpotifyEntityCache).where(
                        SpotifyEntityCache.entity_type == entity_type,
                        SpotifyEntityCache.spotify_id == spotify_id,
                    )
                )
                session.add(
                    SpotifyEntityCache(
                        entity_type=entity_type,
                        spotify_id=spotify_id,
                        data_json=data_json,
                        fetched_at=now,
                    )
                )
            await session.commit()

    async def delete(self, key: str) -> None:
        entity_type, spotify_id = self._parse_key(key)
        async with self._session_factory() as session:
            await session.execute(
                delete(SpotifyEntityCache).where(
                    SpotifyEntityCache.entity_type == entity_type,
                    SpotifyEntityCache.spotify_id == spotify_id,
                )
            )
            await session.commit()

    async def close(self) -> None:
        pass  # Session factory manages its own lifecycle

    @staticmethod
    def _parse_key(key: str) -> tuple[str, str]:
        """Split 'sp:track:abc123' into ('sp_track', 'abc123')."""
        parts = key.split(":", 2)
        if len(parts) == 3:
            return f"{parts[0]}_{parts[1]}", parts[2]
        return "generic", key
