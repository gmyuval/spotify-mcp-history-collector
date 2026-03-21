"""Application-wide dependencies."""

import logging
import os
from urllib.parse import urlsplit

from shared.cache.backend import CacheBackend
from shared.cache.valkey_backend import ValkeyCacheBackend
from shared.db import DatabaseManager

logger = logging.getLogger(__name__)

db_manager = DatabaseManager.from_env()


def create_cache_backend() -> CacheBackend:
    """Create the cache backend based on VALKEY_URL env var.

    Returns ValkeyCacheBackend if VALKEY_URL is set, else PostgresCacheBackend.
    """
    valkey_url = os.environ.get("VALKEY_URL", "")
    if valkey_url:
        parsed = urlsplit(valkey_url)
        logger.info("Using Valkey cache backend at %s:%s", parsed.hostname, parsed.port)
        return ValkeyCacheBackend.from_url(valkey_url)

    # Lazy import to avoid circular dependency at module level
    from shared.cache.postgres_backend import PostgresCacheBackend

    logger.info("VALKEY_URL not set, using PostgreSQL cache backend")
    return PostgresCacheBackend(db_manager.session)


cache_backend: CacheBackend = create_cache_backend()
