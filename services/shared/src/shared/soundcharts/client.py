"""Async Soundcharts API client for audio features."""

import asyncio
import logging
import random

import httpx

from shared.cache.backend import CacheBackend
from shared.soundcharts.constants import (
    SC_API_BASE,
    SC_API_KEY_HEADER,
    SC_APP_ID_HEADER,
    SC_DEFAULT_CACHE_TTL,
    SC_REQUEST_TIMEOUT,
    SC_SONG_AUDIO_FEATURES_PATH,
    SC_SONG_BY_PLATFORM_PATH,
)
from shared.soundcharts.models import SoundchartsAudioFeatures, SoundchartsSongIdentifier

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0


class SoundchartsClient:
    """Async Soundcharts client for audio features lookup."""

    def __init__(
        self,
        app_id: str,
        api_key: str,
        cache: CacheBackend,
        cache_ttl: int = SC_DEFAULT_CACHE_TTL,
    ) -> None:
        self._cache = cache
        self._cache_ttl = cache_ttl
        self._disabled = False
        self._client = httpx.AsyncClient(
            base_url=SC_API_BASE,
            headers={
                SC_APP_ID_HEADER: app_id,
                SC_API_KEY_HEADER: api_key,
                "Accept": "application/json",
            },
            timeout=SC_REQUEST_TIMEOUT,
        )

    @property
    def disabled(self) -> bool:
        return self._disabled

    async def close(self) -> None:
        await self._client.aclose()

    async def get_audio_features(self, spotify_track_id: str) -> SoundchartsAudioFeatures | None:
        """Get audio features for a Spotify track ID."""
        if self._disabled:
            return None

        cache_key = f"sc:features:{spotify_track_id}"
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return SoundchartsAudioFeatures.model_validate(cached)

        # Step 1: Resolve Spotify ID to Soundcharts UUID
        song = await self._get_song_by_spotify_id(spotify_track_id)
        if not song:
            return None

        # Step 2: Fetch audio features
        features = await self._get_features(song.uuid)
        if features:
            await self._cache.set(cache_key, features.model_dump(), self._cache_ttl)
        return features

    async def _request_with_retry(self, path: str) -> httpx.Response | None:
        """Make a GET request with exponential backoff on 429/5xx."""
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.get(path)

                if response.status_code in (401, 403):
                    logger.error("Soundcharts auth failed (%d), disabling client", response.status_code)
                    self._disabled = True
                    return None

                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < _MAX_RETRIES - 1:
                        retry_after = response.headers.get("Retry-After")
                        if retry_after and retry_after.isdigit():
                            delay = float(retry_after)
                        else:
                            delay = _RETRY_BASE_DELAY * (2**attempt) + random.uniform(0, 0.5)
                        logger.debug(
                            "Soundcharts %d on %s, retrying in %.1fs (attempt %d/%d)",
                            response.status_code,
                            path,
                            delay,
                            attempt + 1,
                            _MAX_RETRIES,
                        )
                        await asyncio.sleep(delay)
                        continue
                    logger.warning("Soundcharts %d on %s, exhausted retries", response.status_code, path)
                    return None

                return response
            except httpx.HTTPError as e:
                if attempt < _MAX_RETRIES - 1:
                    delay = _RETRY_BASE_DELAY * (2**attempt)
                    logger.debug("Soundcharts request error on %s: %s, retrying in %.1fs", path, e, delay)
                    await asyncio.sleep(delay)
                    continue
                logger.debug("Soundcharts request error on %s: %s, exhausted retries", path, e)
                return None
        return None

    async def _get_song_by_spotify_id(self, spotify_track_id: str) -> SoundchartsSongIdentifier | None:
        """Resolve a Spotify track ID to a Soundcharts song."""
        response = await self._request_with_retry(f"{SC_SONG_BY_PLATFORM_PATH}/{spotify_track_id}")
        if response is None:
            return None
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            logger.debug("Soundcharts song lookup returned %d", response.status_code)
            return None

        try:
            data = response.json()
        except ValueError:
            logger.debug("Soundcharts song lookup returned invalid JSON")
            return None
        obj = data.get("object", {})
        if not obj.get("uuid"):
            return None
        return SoundchartsSongIdentifier(uuid=obj["uuid"], name=obj.get("name", ""))

    async def _get_features(self, song_uuid: str) -> SoundchartsAudioFeatures | None:
        """Fetch audio features for a Soundcharts song UUID."""
        path = SC_SONG_AUDIO_FEATURES_PATH.format(song_uuid=song_uuid)
        response = await self._request_with_retry(path)
        if response is None:
            return None
        if response.status_code != 200:
            return None

        try:
            data = response.json()
        except ValueError:
            logger.debug("Soundcharts audio features returned invalid JSON")
            return None
        obj = data.get("object", {})
        if not obj:
            return None
        return SoundchartsAudioFeatures.model_validate(obj)
