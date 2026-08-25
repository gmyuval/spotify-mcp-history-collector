"""Tests for audio features providers."""

from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from shared.audio.provider import (
    AudioFeaturesData,
    ChainedAudioFeaturesProvider,
    SoundchartsAudioFeaturesProvider,
    SpotifyAudioFeaturesProvider,
)
from shared.cache.backend import CacheBackend
from shared.soundcharts.client import SoundchartsClient
from shared.soundcharts.constants import SC_API_BASE
from shared.soundcharts.models import SoundchartsAudioFeatures
from shared.spotify.exceptions import SpotifyRequestError


@pytest.mark.asyncio
async def test_chained_tries_providers_in_order() -> None:
    provider1 = AsyncMock()
    provider1.disabled = False
    provider1.name = "first"
    provider1.get_features.return_value = {"track1": AudioFeaturesData(danceability=0.8)}

    provider2 = AsyncMock()
    provider2.disabled = False
    provider2.name = "second"
    provider2.get_features.return_value = {"track2": AudioFeaturesData(energy=0.9)}

    chain = ChainedAudioFeaturesProvider([provider1, provider2])
    result = await chain.get_features(["track1", "track2"])

    assert "track1" in result
    assert "track2" in result
    assert result["track1"].danceability == 0.8
    assert result["track2"].energy == 0.9


@pytest.mark.asyncio
async def test_chained_skips_disabled_providers() -> None:
    provider1 = AsyncMock()
    provider1.disabled = True
    provider1.name = "disabled"

    provider2 = AsyncMock()
    provider2.disabled = False
    provider2.name = "active"
    provider2.get_features.return_value = {"track1": AudioFeaturesData(energy=0.5)}

    chain = ChainedAudioFeaturesProvider([provider1, provider2])
    result = await chain.get_features(["track1"])

    provider1.get_features.assert_not_awaited()
    assert "track1" in result


@pytest.mark.asyncio
async def test_chained_reports_disabled_when_all_disabled() -> None:
    provider1 = AsyncMock()
    provider1.disabled = True
    provider2 = AsyncMock()
    provider2.disabled = True

    chain = ChainedAudioFeaturesProvider([provider1, provider2])
    assert chain.disabled is True


@pytest.mark.asyncio
async def test_soundcharts_provider_maps_features() -> None:
    mock_client = AsyncMock()
    mock_client.disabled = False
    mock_client.get_audio_features.return_value = SoundchartsAudioFeatures(
        danceability=0.7, energy=0.85, valence=0.6, tempo=128.0
    )

    provider = SoundchartsAudioFeaturesProvider(mock_client)
    result = await provider.get_features(["track1"])

    assert "track1" in result
    assert result["track1"].danceability == 0.7
    assert result["track1"].tempo == 128.0


@pytest.mark.asyncio
async def test_soundcharts_provider_disabled_when_client_disabled() -> None:
    mock_client = AsyncMock()
    mock_client.disabled = True

    provider = SoundchartsAudioFeaturesProvider(mock_client)
    assert provider.disabled is True


@respx.mock
@pytest.mark.asyncio
async def test_spotify_403_falls_through_to_soundcharts_provider() -> None:
    """The concrete provider chain preserves the external fallback after Spotify rejects access."""
    spotify_client = AsyncMock()
    spotify_client.get_audio_features.side_effect = SpotifyRequestError(403, "Forbidden")

    async def spotify_client_factory(_user_id: int, _session: object) -> AsyncMock:
        return spotify_client

    cache = AsyncMock(spec=CacheBackend)
    cache.get.return_value = None
    soundcharts_client = SoundchartsClient(app_id="test-app", api_key="test-key", cache=cache)
    respx.get(f"{SC_API_BASE}/song/by-platform/spotify/track1").mock(
        return_value=httpx.Response(200, json={"object": {"uuid": "sc-uuid-1", "name": "Test Song"}})
    )
    respx.get(f"{SC_API_BASE}/song/sc-uuid-1/spotify/audio-features").mock(
        return_value=httpx.Response(200, json={"object": {"danceability": 0.75, "energy": 0.82}})
    )
    chain = ChainedAudioFeaturesProvider(
        [
            SpotifyAudioFeaturesProvider(spotify_client_factory),
            SoundchartsAudioFeaturesProvider(soundcharts_client),
        ]
    )

    try:
        result = await chain.get_features(["track1"], user_id=1, session=object())
    finally:
        await soundcharts_client.close()

    assert result["track1"].danceability == 0.75
    assert result["track1"].energy == 0.82
