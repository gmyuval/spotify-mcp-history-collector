"""Tests for SoundchartsClient with mocked HTTP and cache."""

from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from shared.cache.backend import CacheBackend
from shared.soundcharts.client import SoundchartsClient
from shared.soundcharts.constants import SC_API_BASE


@pytest.fixture
def mock_cache() -> AsyncMock:
    cache = AsyncMock(spec=CacheBackend)
    cache.get.return_value = None
    return cache


@pytest.fixture
def client(mock_cache: AsyncMock) -> SoundchartsClient:
    return SoundchartsClient(app_id="test-app", api_key="test-key", cache=mock_cache)


@respx.mock
@pytest.mark.asyncio
async def test_get_audio_features_success(client: SoundchartsClient, mock_cache: AsyncMock) -> None:
    respx.get(f"{SC_API_BASE}/song/by-platform/spotify/abc123").mock(
        return_value=httpx.Response(200, json={"object": {"uuid": "sc-uuid-1", "name": "Test Song"}})
    )
    respx.get(f"{SC_API_BASE}/song/sc-uuid-1/spotify/audio-features").mock(
        return_value=httpx.Response(
            200,
            json={"object": {"danceability": 0.75, "energy": 0.82, "valence": 0.45, "tempo": 120.0}},
        )
    )

    result = await client.get_audio_features("abc123")
    assert result is not None
    assert result.danceability == 0.75
    assert result.energy == 0.82
    mock_cache.set.assert_awaited_once()


@respx.mock
@pytest.mark.asyncio
async def test_get_audio_features_caches_result(client: SoundchartsClient, mock_cache: AsyncMock) -> None:
    mock_cache.get.return_value = {"danceability": 0.5, "energy": 0.6}
    result = await client.get_audio_features("abc123")
    assert result is not None
    assert result.danceability == 0.5


@respx.mock
@pytest.mark.asyncio
async def test_get_audio_features_song_not_found(client: SoundchartsClient, mock_cache: AsyncMock) -> None:
    respx.get(f"{SC_API_BASE}/song/by-platform/spotify/unknown").mock(return_value=httpx.Response(404))
    result = await client.get_audio_features("unknown")
    assert result is None


@respx.mock
@pytest.mark.asyncio
async def test_get_audio_features_auth_error_disables_client(client: SoundchartsClient, mock_cache: AsyncMock) -> None:
    respx.get(f"{SC_API_BASE}/song/by-platform/spotify/abc123").mock(return_value=httpx.Response(403))
    result = await client.get_audio_features("abc123")
    assert result is None
    assert client.disabled is True

    # Subsequent calls should return None immediately
    result2 = await client.get_audio_features("abc123")
    assert result2 is None


@respx.mock
@pytest.mark.asyncio
async def test_get_audio_features_401_disables_client(client: SoundchartsClient, mock_cache: AsyncMock) -> None:
    respx.get(f"{SC_API_BASE}/song/by-platform/spotify/abc123").mock(return_value=httpx.Response(401))
    result = await client.get_audio_features("abc123")
    assert result is None
    assert client.disabled is True

    # Subsequent calls should return None immediately
    result2 = await client.get_audio_features("abc123")
    assert result2 is None
