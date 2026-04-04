"""Local track resolution — resolve local:<sha1> IDs to real Spotify track IDs."""

import logging
import unicodedata
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from collector.settings import CollectorSettings
from collector.tokens import CollectorTokenManager
from shared.db.enums import JobStatus, JobType, TrackSource
from shared.db.models.music import Track
from shared.db.models.operations import JobRun
from shared.db.models.user import SpotifyToken
from shared.spotify.client import SpotifyClient
from shared.spotify.models import SpotifyTrack

logger = logging.getLogger(__name__)


def _normalize(name: str) -> str:
    """Normalize a name for comparison: lowercase, strip, collapse whitespace, NFKD."""
    text = unicodedata.normalize("NFKD", name)
    return " ".join(text.lower().split())


def _is_match(local_track: str, local_artist: str, candidate: SpotifyTrack) -> bool:
    """Strict match: both track name and primary artist must match after normalization."""
    if _normalize(candidate.name) != _normalize(local_track):
        return False
    if not candidate.artists:
        return False
    return _normalize(candidate.artists[0].name) == _normalize(local_artist)


class LocalTrackResolutionService:
    """Resolves local:<sha1> track IDs to real Spotify track IDs via search."""

    def __init__(self, settings: CollectorSettings) -> None:
        self._settings = settings
        self._token_manager = CollectorTokenManager(settings)

    async def resolve(self, session: AsyncSession) -> int:
        """Resolve unresolved local tracks. Returns count of resolved tracks."""
        if not self._settings.RESOLVE_LOCAL_TRACKS_ENABLED:
            return 0

        cooldown_cutoff = datetime.now(UTC) - timedelta(days=self._settings.RESOLVE_COOLDOWN_DAYS)

        # Find tracks that need resolution:
        # - Have a local_track_id (from ZIP import)
        # - Have no spotify_track_id (not yet resolved)
        # - Haven't been attempted recently (cooldown)
        tracks_to_resolve = await self._find_unresolved_tracks(session, cooldown_cutoff)

        if not tracks_to_resolve:
            logger.debug("No local tracks need resolution")
            return 0

        logger.info("Found %d local tracks to resolve", len(tracks_to_resolve))

        # Need a user token for Spotify API calls
        user_id = await self._get_any_active_user(session)
        if user_id is None:
            logger.warning("No active users with Spotify tokens, skipping resolution")
            return 0

        # Record job start
        job_run = JobRun(
            user_id=user_id,
            job_type=JobType.RESOLVE_LOCAL,
            started_at=datetime.now(UTC),
            status=JobStatus.RUNNING,
        )
        session.add(job_run)
        await session.flush()

        total_resolved = 0
        total_attempted = 0

        try:
            client = await self._create_spotify_client(user_id, session)

            for i in range(0, len(tracks_to_resolve), self._settings.RESOLVE_BATCH_SIZE):
                batch = tracks_to_resolve[i : i + self._settings.RESOLVE_BATCH_SIZE]
                resolved, attempted = await self._resolve_batch(batch, client, session)
                total_resolved += resolved
                total_attempted += attempted
                await session.flush()

            job_run.completed_at = datetime.now(UTC)
            job_run.status = JobStatus.SUCCESS
            job_run.records_fetched = total_attempted
            job_run.records_inserted = total_resolved
            await session.commit()
        except Exception:
            logger.exception("Error during local track resolution")
            await session.rollback()
            job_run.completed_at = datetime.now(UTC)
            job_run.status = JobStatus.ERROR
            job_run.error_message = "Resolution failed — see logs"
            session.add(job_run)
            await session.commit()
            raise

        logger.info("Resolved %d/%d local tracks", total_resolved, total_attempted)
        return total_resolved

    async def _find_unresolved_tracks(self, session: AsyncSession, cooldown_cutoff: datetime) -> list[Track]:
        """Find local tracks eligible for resolution."""
        result = await session.execute(
            select(Track)
            .options(selectinload(Track.artists))
            .where(
                Track.local_track_id.isnot(None),
                Track.spotify_track_id.is_(None),
                Track.source == TrackSource.IMPORT_ZIP,
                # Either never attempted or attempted before cooldown
                (Track.resolution_attempted_at.is_(None)) | (Track.resolution_attempted_at < cooldown_cutoff),
            )
            .limit(self._settings.RESOLVE_MAX_PER_CYCLE)
        )
        return list(result.scalars().all())

    async def _resolve_batch(
        self,
        tracks: list[Track],
        client: SpotifyClient,
        session: AsyncSession,
    ) -> tuple[int, int]:
        """Resolve a batch of tracks. Returns (resolved_count, attempted_count)."""
        resolved = 0

        for track in tracks:
            # Get the primary artist name
            artist_name = self._get_primary_artist_name(track)
            if not artist_name:
                track.resolution_attempted_at = datetime.now(UTC)
                continue

            try:
                query = f"track:{track.name} artist:{artist_name}"
                search_result = await client.search(query, search_type="track", limit=5)

                if search_result.tracks and search_result.tracks.items:
                    match = self._find_best_match(track.name, artist_name, search_result.tracks.items)
                    if match:
                        track.spotify_track_id = match.id
                        track.source = TrackSource.RESOLVED
                        if match.duration_ms and not track.duration_ms:
                            track.duration_ms = match.duration_ms
                        if match.album and match.album.name and not track.album_name:
                            track.album_name = match.album.name
                        if match.album and match.album.id and not track.album_spotify_id:
                            track.album_spotify_id = match.album.id
                        resolved += 1
                        logger.debug(
                            "Resolved '%s' by '%s' → %s",
                            track.name,
                            artist_name,
                            match.id,
                        )

                track.resolution_attempted_at = datetime.now(UTC)

            except Exception:
                logger.warning("Search failed for '%s' by '%s'", track.name, artist_name, exc_info=True)
                track.resolution_attempted_at = datetime.now(UTC)

        return resolved, len(tracks)

    @staticmethod
    def _get_primary_artist_name(track: Track) -> str | None:
        """Get the name of the first artist for a track."""
        if not track.artists:
            return None
        # Artists are ordered by TrackArtist.position; relationship loads in PK order
        return track.artists[0].name

    @staticmethod
    def _find_best_match(track_name: str, artist_name: str, candidates: list[SpotifyTrack]) -> SpotifyTrack | None:
        """Find the first candidate that strictly matches track + artist name."""
        for candidate in candidates:
            if candidate.id and _is_match(track_name, artist_name, candidate):
                return candidate
        return None

    async def _create_spotify_client(self, user_id: int, session: AsyncSession) -> SpotifyClient:
        """Create a SpotifyClient for a user."""
        access_token = await self._token_manager.get_valid_token(user_id, session)

        async def _on_expired() -> str:
            return await self._token_manager.refresh_access_token(user_id, session)

        return SpotifyClient(access_token, on_token_expired=_on_expired)

    @staticmethod
    async def _get_any_active_user(session: AsyncSession) -> int | None:
        """Get any user ID that has an active Spotify token."""
        result = await session.execute(select(SpotifyToken.user_id).limit(1))
        return result.scalar_one_or_none()
