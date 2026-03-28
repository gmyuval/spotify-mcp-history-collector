"""Quick database connectivity check for deploy scripts.

Usage: python -m app.db_check
Exits 0 if the database is reachable, 1 otherwise.
"""

import asyncio
import os
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


async def check() -> None:
    url = os.environ["DATABASE_URL"]
    engine = create_async_engine(url, poolclass=NullPool, connect_args={"timeout": 10})
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(check())
    except Exception as exc:
        print(f"DB not ready: {exc}", file=sys.stderr)  # noqa: T201
        sys.exit(1)
