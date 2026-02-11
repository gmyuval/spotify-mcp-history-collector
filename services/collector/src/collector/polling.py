"""Polling service — fetches recently-played and upserts via MusicRepository."""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from collector.settings import CollectorSettings
from collector.tokens import CollectorTokenManager
from shared.db.models.operations import SyncCheckpoint
from shared.db.operations import MusicRepository
from shared.spotify.client import SpotifyClient

logger = logging.getLogger(__name__)


class PollingService:
    """Polls Spotify's recently-played endpoint for a user and stores the results."""

    def __init__(self, settings: CollectorSettings) -> None:
        self._settings = settings
        self._token_manager = CollectorTokenManager(settings)
        self._music_repo = MusicRepository()

    async def poll_user(
        self,
        user_id: int,
        session: AsyncSession,
    ) -> tuple[int, int]:
        """Poll recently-played for a single user.

        Returns (inserted_count, skipped_count).
        """
        # 1. Get valid token
        access_token = await self._token_manager.get_valid_token(user_id, session)

        # 2. Create SpotifyClient with token-expired callback
        async def _on_token_expired() -> str:
            return await self._token_manager.refresh_access_token(user_id, session)

        client = SpotifyClient(
            access_token=access_token,
            on_token_expired=_on_token_expired,
        )

        # 3. Fetch recently played
        response = await client.get_recently_played(limit=50)
        logger.info("Fetched %d recently-played items for user %d", len(response.items), user_id)

        if not response.items:
            return 0, 0

        # 4. Upsert via MusicRepository
        inserted, skipped = await self._music_repo.batch_process_play_history(response.items, user_id, session)

        # 5. Update SyncCheckpoint
        checkpoint = await self._get_or_create_checkpoint(user_id, session)
        checkpoint.last_poll_completed_at = datetime.now(UTC)

        # Set last_poll_latest_played_at to the most recent played_at.
        # Strip tzinfo to match the DB's naive-datetime convention.
        latest_played_at = max(item.played_at for item in response.items).replace(tzinfo=None)
        if checkpoint.last_poll_latest_played_at is None or latest_played_at > checkpoint.last_poll_latest_played_at:
            checkpoint.last_poll_latest_played_at = latest_played_at

        logger.info(
            "Poll complete for user %d: %d inserted, %d skipped",
            user_id,
            inserted,
            skipped,
        )
        return inserted, skipped

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
