"""Main entry point for Spotify History Collector."""

from __future__ import annotations

import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    """Main collector entry point."""
    logger.info("Spotify History Collector starting...")
    # Placeholder - will implement runloop in Phase 6
    await asyncio.sleep(1)
    logger.info("Collector initialized. Waiting for runloop implementation...")
    # Keep container running for now
    while True:
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
