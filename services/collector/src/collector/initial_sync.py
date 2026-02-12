"""Initial sync service — backward paging through recently-played history."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from collector.job_tracking import JobTracker
from collector.settings import CollectorSettings
from collector.tokens import CollectorTokenManager
from shared.db.enums import JobType, SyncStatus
from shared.db.models.operations import SyncCheckpoint
from shared.db.operations import MusicRepository
from shared.spotify.client import SpotifyClient
from shared.spotify.exceptions import SpotifyRateLimitError

logger = logging.getLogger(__name__)


def _datetime_to_unix_ms(dt: datetime) -> int:
    """Convert a datetime to Unix epoch milliseconds."""
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int((dt - epoch).total_seconds() * 1000)


class InitialSyncService:
    """Pages backward through Spotify recently-played to backfill history."""

    def __init__(self, settings: CollectorSettings) -> None:
        self._settings = settings
        self._token_manager = CollectorTokenManager(settings)
        self._music_repo = MusicRepository()
        self._job_tracker = JobTracker()

    async def sync_user(
        self,
        user_id: int,
        session: AsyncSession,
    ) -> tuple[int, int]:
        """Run initial sync for a user. Returns (total_inserted, total_skipped).

        Skips silently if sync is already completed.
        """
        checkpoint = await self._get_or_create_checkpoint(user_id, session)

        if checkpoint.initial_sync_completed_at is not None:
            logger.info("Initial sync already completed for user %d, skipping", user_id)
            return 0, 0

        # Start job tracking
        job_run = await self._job_tracker.start_job(user_id, JobType.INITIAL_SYNC, session)

        # Mark checkpoint as syncing
        checkpoint.status = SyncStatus.SYNCING
        checkpoint.initial_sync_started_at = datetime.now(UTC)
        await session.flush()

        # Get a valid access token + create client
        access_token = await self._token_manager.get_valid_token(user_id, session)

        async def _on_token_expired() -> str:
            return await self._token_manager.refresh_access_token(user_id, session)

        client = SpotifyClient(
            access_token=access_token,
            on_token_expired=_on_token_expired,
        )

        total_inserted = 0
        total_skipped = 0
        total_fetched = 0
        request_count = 0
        cursor: int | None = None  # Unix ms 'before' cursor
        previous_oldest: datetime | None = None
        cutoff = datetime.now(UTC) - timedelta(days=self._settings.INITIAL_SYNC_MAX_DAYS)
        stop_reason = "unknown"

        try:
            while True:
                # Stop condition: max requests
                if request_count >= self._settings.INITIAL_SYNC_MAX_REQUESTS:
                    stop_reason = "max_requests"
                    logger.info(
                        "Initial sync for user %d: reached max requests (%d)",
                        user_id,
                        self._settings.INITIAL_SYNC_MAX_REQUESTS,
                    )
                    break

                # Fetch a batch
                try:
                    response = await client.get_recently_played(limit=50, before=cursor)
                except SpotifyRateLimitError:
                    stop_reason = "rate_limited"
                    logger.warning("Initial sync for user %d: excessive rate limiting, stopping", user_id)
                    break

                request_count += 1
                total_fetched += len(response.items)

                # Stop condition: empty batch
                if not response.items:
                    stop_reason = "empty_batch"
                    logger.info("Initial sync for user %d: empty batch, stopping", user_id)
                    break

                # Process the batch
                inserted, skipped = await self._music_repo.batch_process_play_history(response.items, user_id, session)
                total_inserted += inserted
                total_skipped += skipped

                # Find oldest played_at in this batch
                batch_oldest = min(item.played_at for item in response.items)

                # Stop condition: no progress
                if previous_oldest is not None and batch_oldest >= previous_oldest:
                    stop_reason = "no_progress"
                    logger.info("Initial sync for user %d: no progress, stopping", user_id)
                    break

                previous_oldest = batch_oldest

                # Update checkpoint with earliest timestamp seen so far
                # Ensure batch_oldest is tz-aware for comparison with DB
                if batch_oldest.tzinfo is None:
                    batch_oldest = batch_oldest.replace(tzinfo=UTC)
                if (
                    checkpoint.initial_sync_earliest_played_at is None
                    or batch_oldest < checkpoint.initial_sync_earliest_played_at
                ):
                    checkpoint.initial_sync_earliest_played_at = batch_oldest
                    await session.flush()

                # Stop condition: max days
                if batch_oldest.tzinfo is None:
                    batch_oldest_aware = batch_oldest.replace(tzinfo=UTC)
                else:
                    batch_oldest_aware = batch_oldest
                if batch_oldest_aware < cutoff:
                    stop_reason = "max_days"
                    logger.info(
                        "Initial sync for user %d: reached max days (%d)",
                        user_id,
                        self._settings.INITIAL_SYNC_MAX_DAYS,
                    )
                    break

                # Advance cursor: before = oldest_played_at - 1ms
                cursor = _datetime_to_unix_ms(batch_oldest) - 1

            # Mark checkpoint based on stop reason
            if stop_reason == "rate_limited":
                # Rate-limited: leave sync incomplete so it retries on next cycle
                checkpoint.status = SyncStatus.IDLE
                checkpoint.error_message = None
                await session.flush()

                await self._job_tracker.complete_job(
                    job_run,
                    fetched=total_fetched,
                    inserted=total_inserted,
                    skipped=total_skipped,
                    session=session,
                )

                logger.warning(
                    "Initial sync incomplete for user %d (rate limited): %d fetched, %d inserted, requests=%d. "
                    "Will retry on next cycle.",
                    user_id,
                    total_fetched,
                    total_inserted,
                    request_count,
                )
            else:
                # Normal stop: mark sync completed
                checkpoint.initial_sync_completed_at = datetime.now(UTC)
                checkpoint.status = SyncStatus.IDLE
                checkpoint.error_message = None
                await session.flush()

                await self._job_tracker.complete_job(
                    job_run,
                    fetched=total_fetched,
                    inserted=total_inserted,
                    skipped=total_skipped,
                    session=session,
                )

                logger.info(
                    "Initial sync completed for user %d: %d fetched, %d inserted, %d skipped, "
                    "stop_reason=%s, requests=%d",
                    user_id,
                    total_fetched,
                    total_inserted,
                    total_skipped,
                    stop_reason,
                    request_count,
                )

        except Exception as exc:
            checkpoint.status = SyncStatus.ERROR
            checkpoint.error_message = str(exc)[:500]
            await session.flush()

            await self._job_tracker.fail_job(job_run, str(exc)[:500], session)
            raise

        return total_inserted, total_skipped

    async def _get_or_create_checkpoint(
        self,
        user_id: int,
        session: AsyncSession,
    ) -> SyncCheckpoint:
        """Get or create a SyncCheckpoint for the user."""
        result = await session.execute(select(SyncCheckpoint).where(SyncCheckpoint.user_id == user_id))
        checkpoint = result.scalar_one_or_none()
        if checkpoint is None:
            checkpoint = SyncCheckpoint(user_id=user_id)
            session.add(checkpoint)
            await session.flush()
        return checkpoint
