"""Audio features provider protocol and implementations.

Spotify's audio-features endpoint is deprecated and may return 403.
Soundcharts is a paid alternative with the same 0.0-1.0 scale.
ChainedAudioFeaturesProvider tries providers in order.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import httpx

from shared.soundcharts.client import SoundchartsClient
from shared.spotify.exceptions import SpotifyClientError

logger = logging.getLogger(__name__)


@dataclass
class AudioFeaturesData:
    """Normalized audio features (same fields as the audio_features DB table)."""

    danceability: float | None = None
    energy: float | None = None
    key: int | None = None
    loudness: float | None = None
    mode: int | None = None
    speechiness: float | None = None
    acousticness: float | None = None
    instrumentalness: float | None = None
    liveness: float | None = None
    valence: float | None = None
    tempo: float | None = None
    time_signature: int | None = None


@runtime_checkable
class AudioFeaturesProvider(Protocol):
    """Interface for audio features providers."""

    async def get_features(self, spotify_track_ids: list[str], **kwargs: Any) -> dict[str, AudioFeaturesData]:
        """Fetch audio features for a batch of Spotify track IDs.

        Returns a dict mapping spotify_track_id -> AudioFeaturesData.
        Missing tracks are omitted from the result.
        """
        ...

    @property
    def name(self) -> str:
        """Provider name for logging."""
        ...

    @property
    def disabled(self) -> bool:
        """Whether this provider is temporarily disabled (e.g. 403)."""
        ...


class SpotifyAudioFeaturesProvider:
    """Audio features from Spotify's (deprecated) /audio-features endpoint."""

    def __init__(self, spotify_client_factory: Callable[..., Awaitable[Any]]) -> None:
        """Accept a callable(user_id, session) -> SpotifyClient."""
        self._client_factory = spotify_client_factory
        self._disabled = False

    @property
    def name(self) -> str:
        return "spotify"

    @property
    def disabled(self) -> bool:
        return self._disabled

    async def get_features(
        self,
        spotify_track_ids: list[str],
        *,
        user_id: int | None = None,
        session: Any | None = None,
        **_kwargs: Any,
    ) -> dict[str, AudioFeaturesData]:
        """Fetch from Spotify. Requires user_id and session for token access."""
        if self._disabled or not user_id or not session:
            return {}

        try:
            client = await self._client_factory(user_id, session)
            response = await client.get_audio_features(spotify_track_ids)

            result: dict[str, AudioFeaturesData] = {}
            for item in response.audio_features or []:
                if item is None or not item.id:
                    continue
                result[item.id] = AudioFeaturesData(
                    danceability=item.danceability,
                    energy=item.energy,
                    key=item.key,
                    loudness=item.loudness,
                    mode=item.mode,
                    speechiness=item.speechiness,
                    acousticness=item.acousticness,
                    instrumentalness=item.instrumentalness,
                    liveness=item.liveness,
                    valence=item.valence,
                    tempo=item.tempo,
                    time_signature=item.time_signature,
                )
            return result
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                logger.warning("Spotify audio features returned 403 (deprecated), disabling provider")
                self._disabled = True
            else:
                logger.debug("Spotify audio features HTTP error: %s", e)
            return {}
        except SpotifyClientError as e:
            if "403" in str(e):
                logger.warning("Spotify audio features returned 403 (deprecated), disabling provider")
                self._disabled = True
            else:
                logger.debug("Spotify audio features error: %s", e)
            return {}
        except Exception as e:
            logger.debug("Spotify audio features error: %s", e)
            return {}


class SoundchartsAudioFeaturesProvider:
    """Audio features from Soundcharts API."""

    def __init__(self, soundcharts_client: SoundchartsClient) -> None:
        self._client = soundcharts_client

    @property
    def name(self) -> str:
        return "soundcharts"

    @property
    def disabled(self) -> bool:
        return self._client.disabled

    async def get_features(self, spotify_track_ids: list[str], **_kwargs: Any) -> dict[str, AudioFeaturesData]:
        result: dict[str, AudioFeaturesData] = {}
        for track_id in spotify_track_ids:
            if self._client.disabled:
                break
            features = await self._client.get_audio_features(track_id)
            if features:
                result[track_id] = AudioFeaturesData(
                    danceability=features.danceability,
                    energy=features.energy,
                    key=features.key,
                    loudness=features.loudness,
                    mode=features.mode,
                    speechiness=features.speechiness,
                    acousticness=features.acousticness,
                    instrumentalness=features.instrumentalness,
                    liveness=features.liveness,
                    valence=features.valence,
                    tempo=features.tempo,
                    time_signature=features.time_signature,
                )
        return result


class ChainedAudioFeaturesProvider:
    """Tries multiple providers in order, merging results."""

    def __init__(self, providers: list[AudioFeaturesProvider]) -> None:
        self._providers = providers

    @property
    def name(self) -> str:
        return "chained"

    @property
    def disabled(self) -> bool:
        return all(p.disabled for p in self._providers)

    async def get_features(self, spotify_track_ids: list[str], **kwargs: Any) -> dict[str, AudioFeaturesData]:
        result: dict[str, AudioFeaturesData] = {}
        remaining = list(spotify_track_ids)

        for provider in self._providers:
            if provider.disabled or not remaining:
                continue
            logger.debug("Trying %s provider for %d tracks", provider.name, len(remaining))
            batch_result = await provider.get_features(remaining, **kwargs)
            result.update(batch_result)
            remaining = [tid for tid in remaining if tid not in result]

        return result
