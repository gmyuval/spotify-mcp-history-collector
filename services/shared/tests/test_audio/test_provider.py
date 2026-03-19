"""Tests for audio features providers."""

from unittest.mock import AsyncMock

import pytest

from shared.audio.provider import (
    AudioFeaturesData,
    ChainedAudioFeaturesProvider,
    SoundchartsAudioFeaturesProvider,
)
from shared.soundcharts.models import SoundchartsAudioFeatures


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
