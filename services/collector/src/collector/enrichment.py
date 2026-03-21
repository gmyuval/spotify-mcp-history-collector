"""Audio features enrichment service for the collector."""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from collector.settings import CollectorSettings
from collector.tokens import CollectorTokenManager
from shared.audio.provider import (
    AudioFeaturesProvider,
    ChainedAudioFeaturesProvider,
    SoundchartsAudioFeaturesProvider,
    SpotifyAudioFeaturesProvider,
)
from shared.db.enums import JobStatus, JobType
from shared.db.models.music import AudioFeatures, Track
from shared.db.models.operations import JobRun
from shared.db.models.user import SpotifyToken
from shared.spotify.client import SpotifyClient

logger = logging.getLogger(__name__)


class AudioFeaturesEnrichmentService:
    """Batch-enriches tracks with audio features using chained providers."""

    def __init__(self, settings: CollectorSettings) -> None:
        self._settings = settings
        self._token_manager = CollectorTokenManager(settings)
        self._sc_provider: SoundchartsAudioFeaturesProvider | None = None
        self._sc_initialized = False

    async def enrich(self, session: AsyncSession) -> int:
        """Enrich tracks missing audio features. Returns count of enriched tracks."""
        if not self._settings.ENRICH_AUDIO_FEATURES_ENABLED:
            return 0

        # Find tracks with Spotify IDs but no audio features
        existing_af_ids = select(AudioFeatures.track_id)
        result = await session.execute(
            select(Track.id, Track.spotify_track_id)
            .where(
                Track.spotify_track_id.isnot(None),
                Track.spotify_track_id.notlike("local:%"),
                ~Track.id.in_(existing_af_ids),
            )
            .limit(self._settings.ENRICH_MAX_PER_CYCLE)
        )
        tracks_to_enrich = result.all()

        if not tracks_to_enrich:
            logger.debug("No tracks need audio features enrichment")
            return 0

        logger.info("Found %d tracks to enrich with audio features", len(tracks_to_enrich))

        # Get any active user's token for Spotify API calls
        user_id = await self._get_any_active_user(session)

        # Need at least one user for job tracking (JobRun.user_id is a required FK)
        if user_id is None:
            logger.warning("No active users with Spotify tokens, skipping enrichment")
            return 0

        # Build provider chain
        providers: list[AudioFeaturesProvider] = []
        spotify_provider = SpotifyAudioFeaturesProvider(lambda uid, sess: self._create_spotify_client(uid, sess))
        providers.append(spotify_provider)

        # Soundcharts provider (reuse across cycles)
        sc_provider = self._get_or_create_soundcharts_provider()
        if sc_provider is not None:
            providers.append(sc_provider)

        chain = ChainedAudioFeaturesProvider(providers)

        # Record job start
        job_run = JobRun(
            user_id=user_id,
            job_type=JobType.ENRICH,
            started_at=datetime.now(UTC),
            status=JobStatus.RUNNING,
        )
        session.add(job_run)
        await session.flush()

        # Process in batches
        total_enriched = 0
        batch_size = self._settings.ENRICH_BATCH_SIZE

        try:
            for i in range(0, len(tracks_to_enrich), batch_size):
                batch = tracks_to_enrich[i : i + batch_size]
                track_id_map = {row.spotify_track_id: row.id for row in batch}
                spotify_ids = list(track_id_map.keys())

                kwargs: dict[str, Any] = {"user_id": user_id, "session": session}
                features = await chain.get_features(spotify_ids, **kwargs)

                batch_count = 0
                for spotify_id, data in features.items():
                    db_track_id = track_id_map.get(spotify_id)
                    if db_track_id is None:
                        continue
                    af = AudioFeatures(
                        track_id=db_track_id,
                        danceability=data.danceability,
                        energy=data.energy,
                        key=data.key,
                        loudness=data.loudness,
                        mode=data.mode,
                        speechiness=data.speechiness,
                        acousticness=data.acousticness,
                        instrumentalness=data.instrumentalness,
                        liveness=data.liveness,
                        valence=data.valence,
                        tempo=data.tempo,
                        time_signature=data.time_signature,
                    )
                    session.add(af)
                    batch_count += 1

                try:
                    await session.flush()
                    total_enriched += batch_count
                except IntegrityError:
                    # Another worker may have inserted the same track_id — rollback batch and continue
                    logger.debug("IntegrityError during enrichment batch flush, rolling back batch")
                    await session.rollback()
                    # Re-add the job_run since rollback removed it
                    session.add(job_run)
                    await session.flush()

            # Finalize job — success
            job_run.completed_at = datetime.now(UTC)
            job_run.status = JobStatus.SUCCESS
            job_run.records_inserted = total_enriched
            await session.commit()
        except Exception:
            # Finalize job — error
            logger.exception("Error during audio features enrichment")
            await session.rollback()
            job_run.completed_at = datetime.now(UTC)
            job_run.status = JobStatus.ERROR
            job_run.error_message = "Enrichment failed — see logs"
            session.add(job_run)
            await session.commit()
            raise

        logger.info("Enriched %d tracks with audio features", total_enriched)
        return total_enriched

    def _get_or_create_soundcharts_provider(self) -> SoundchartsAudioFeaturesProvider | None:
        """Lazily create and reuse the Soundcharts provider across cycles."""
        if self._sc_initialized:
            return self._sc_provider

        self._sc_initialized = True

        if not self._settings.SOUNDCHARTZ_X_APP_ID or not self._settings.SOUNDCHARTZ_X_API_KEY:
            return None

        try:
            from shared.cache.backend import CacheBackend
            from shared.cache.valkey_backend import ValkeyCacheBackend
            from shared.soundcharts.client import SoundchartsClient

            sc_cache: CacheBackend
            if self._settings.VALKEY_URL:
                sc_cache = ValkeyCacheBackend.from_url(self._settings.VALKEY_URL)
            else:
                from shared.cache.postgres_backend import PostgresCacheBackend
                from shared.config.database import DatabaseSettings
                from shared.db.session import DatabaseManager

                db_settings = DatabaseSettings(database_url=self._settings.DATABASE_URL)
                db_mgr = DatabaseManager(db_settings)
                sc_cache = PostgresCacheBackend(db_mgr.session)

            sc_client = SoundchartsClient(
                app_id=self._settings.SOUNDCHARTZ_X_APP_ID,
                api_key=self._settings.SOUNDCHARTZ_X_API_KEY,
                cache=sc_cache,
            )
            self._sc_provider = SoundchartsAudioFeaturesProvider(sc_client)
        except Exception as exc:
            logger.warning("Failed to initialize Soundcharts provider: %s", exc)

        return self._sc_provider

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
