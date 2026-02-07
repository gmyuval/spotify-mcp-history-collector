"""Main entry point for Spotify History Collector."""

import asyncio
import logging

from shared.db import DatabaseManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    """Main collector entry point."""
    logger.info("Spotify History Collector starting...")
    db_manager = DatabaseManager.from_env()
    try:
        await asyncio.sleep(1)
        logger.info("Collector initialized. Waiting for runloop implementation...")
        # Placeholder - will implement runloop in Phase 6
        while True:
            await asyncio.sleep(60)
    finally:
        await db_manager.dispose()


if __name__ == "__main__":
    asyncio.run(main())
