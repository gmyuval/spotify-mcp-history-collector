"""Collector run loop — orchestrates initial sync and incremental polling."""

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from collector.initial_sync import InitialSyncService
from collector.polling import PollingService
from collector.settings import CollectorSettings
from shared.db.enums import SyncStatus
from shared.db.models.operations import SyncCheckpoint
from shared.db.models.user import User
from shared.db.session import DatabaseManager

logger = logging.getLogger(__name__)


class CollectorRunLoop:
    """Priority-based collector: (ZIP imports) -> initial sync -> incremental polling."""

    def __init__(self, settings: CollectorSettings, db_manager: DatabaseManager) -> None:
        self._settings = settings
        self._db_manager = db_manager
        self._polling_service = PollingService(settings)
        self._initial_sync_service = InitialSyncService(settings)
        self._user_semaphore = asyncio.Semaphore(self._settings.INITIAL_SYNC_CONCURRENCY)

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Main loop: run cycles until shutdown_event is set."""
        logger.info(
            "Collector run loop starting (interval=%ds, initial_sync=%s)",
            self._settings.COLLECTOR_INTERVAL_SECONDS,
            self._settings.INITIAL_SYNC_ENABLED,
        )

        while not shutdown_event.is_set():
            try:
                await self._run_cycle()
            except Exception:
                logger.exception("Unhandled error in collector cycle")

            # Sleep in small increments so we can respond to shutdown quickly
            for _ in range(self._settings.COLLECTOR_INTERVAL_SECONDS):
                if shutdown_event.is_set():
                    break
                await asyncio.sleep(1)

        logger.info("Collector run loop shutting down")

    async def _run_cycle(self) -> None:
        """Execute one full collector cycle."""
        logger.info("Starting collector cycle")

        # Phase 1: ZIP imports (placeholder for Phase 5)
        # TODO: process pending import_jobs here

        # Phase 2 & 3: Process each user (initial sync or polling)
        async with self._db_manager.session() as session:
            users = await self._get_active_users(session)

        if not users:
            logger.info("No active users found, skipping cycle")
            return

        logger.info("Processing %d active user(s)", len(users))

        tasks = [self._process_user(user_id) for user_id in users]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for user_id, result in zip(users, results, strict=True):
            if isinstance(result, Exception):
                logger.error("Error processing user %d: %s", user_id, result)

        logger.info("Collector cycle complete")

    async def _get_active_users(self, session: AsyncSession) -> list[int]:
        """Get IDs of users that should be processed (not paused)."""
        # Get all users that have a token (i.e. have completed OAuth)
        result = await session.execute(select(User).options(selectinload(User.sync_checkpoint)).join(User.token))
        users = result.scalars().all()

        active_user_ids: list[int] = []
        for user in users:
            if user.sync_checkpoint and user.sync_checkpoint.status == SyncStatus.PAUSED:
                logger.debug("Skipping paused user %d", user.id)
                continue
            active_user_ids.append(user.id)

        return active_user_ids

    async def _process_user(self, user_id: int) -> None:
        """Process a single user: initial sync if needed, then poll."""
        async with self._user_semaphore:
            async with self._db_manager.session() as session:
                # Check if initial sync is needed
                if self._settings.INITIAL_SYNC_ENABLED:
                    result = await session.execute(select(SyncCheckpoint).where(SyncCheckpoint.user_id == user_id))
                    checkpoint = result.scalar_one_or_none()

                    if checkpoint is None or checkpoint.initial_sync_completed_at is None:
                        logger.info("Running initial sync for user %d", user_id)
                        await self._initial_sync_service.sync_user(user_id, session)
                        return

                # Run incremental poll
                logger.info("Running incremental poll for user %d", user_id)
                await self._polling_service.poll_user(user_id, session)
