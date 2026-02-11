"""Main entry point for Spotify History Collector."""

import asyncio
import logging
import signal
import sys

from collector.runloop import CollectorRunLoop
from collector.settings import CollectorSettings
from shared.db import DatabaseManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def _register_shutdown_signals(loop: asyncio.AbstractEventLoop, shutdown_event: asyncio.Event) -> None:
    """Register signal handlers for graceful shutdown on both Unix and Windows."""

    def _signal_handler_sync(signum: int, _frame: object) -> None:
        """Stdlib signal handler (runs in main thread). Thread-safe bridge into asyncio."""
        logger.info("Shutdown signal received (signal %d)", signum)
        loop.call_soon_threadsafe(shutdown_event.set)

    if sys.platform != "win32":
        # Unix: asyncio-native signal handlers (preferred)
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, shutdown_event.set)
    else:
        # Windows: loop.add_signal_handler is not supported.
        # Use stdlib signal.signal() which runs the handler in the main thread,
        # then bridge into the event loop via call_soon_threadsafe.
        signal.signal(signal.SIGTERM, _signal_handler_sync)
        signal.signal(signal.SIGINT, _signal_handler_sync)


async def main() -> None:
    """Main collector entry point with graceful shutdown."""
    logger.info("Spotify History Collector starting...")
    settings = CollectorSettings()
    db_manager = DatabaseManager.from_env()
    shutdown_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    _register_shutdown_signals(loop, shutdown_event)

    try:
        run_loop = CollectorRunLoop(settings, db_manager)
        await run_loop.run(shutdown_event)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received, shutting down")
    finally:
        await db_manager.dispose()
        logger.info("Collector shut down complete")


if __name__ == "__main__":
    asyncio.run(main())
