"""Valkey/Redis cache backend using redis.asyncio."""

import json
import logging
from typing import Any

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class ValkeyCacheBackend:
    """CacheBackend backed by Valkey (or Redis) via redis.asyncio."""

    def __init__(self, client: Redis) -> None:
        self._client = client

    @classmethod
    def from_url(cls, url: str) -> ValkeyCacheBackend:
        """Create from a redis://, rediss://, or valkey:// URL."""
        # The redis library doesn't recognize valkey:// scheme — translate it
        normalized = url
        if normalized.startswith("valkey://"):
            normalized = "redis://" + normalized[len("valkey://") :]
        elif normalized.startswith("valkeys://"):
            normalized = "rediss://" + normalized[len("valkeys://") :]
        client = Redis.from_url(normalized, decode_responses=True)
        return cls(client)

    async def get(self, key: str) -> dict[str, Any] | None:
        raw = await self._client.get(key)
        if raw is None:
            return None
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                logger.warning("Cache entry for key %s is not a dict, deleting", key)
                await self._client.delete(key)
                return None
            return parsed
        except json.JSONDecodeError, TypeError:
            logger.warning("Corrupt cache entry for key %s, deleting", key)
            await self._client.delete(key)
            return None

    async def set(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        await self._client.setex(key, ttl_seconds, json.dumps(value))

    async def delete(self, key: str) -> None:
        await self._client.delete(key)

    async def close(self) -> None:
        await self._client.aclose()
