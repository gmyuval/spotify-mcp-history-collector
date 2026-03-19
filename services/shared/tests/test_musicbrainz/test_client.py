"""Tests for MusicBrainzClient with mocked HTTP and cache."""

from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from shared.cache.backend import CacheBackend
from shared.musicbrainz.client import MusicBrainzClient
from shared.musicbrainz.constants import MB_API_BASE


@pytest.fixture
def mock_cache() -> AsyncMock:
    cache = AsyncMock(spec=CacheBackend)
    cache.get.return_value = None
    return cache


@pytest.fixture
def client(mock_cache: AsyncMock) -> MusicBrainzClient:
    return MusicBrainzClient(cache=mock_cache, contact_email="test@example.com")


@respx.mock
@pytest.mark.asyncio
async def test_lookup_recording_by_isrc_caches_result(client: MusicBrainzClient, mock_cache: AsyncMock) -> None:
    respx.get(f"{MB_API_BASE}/recording").mock(
        return_value=httpx.Response(
            200,
            json={
                "recordings": [
                    {
                        "id": "rec-123",
                        "title": "Test Song",
                        "artist-credit": [{"name": "Test Artist", "id": "art-456"}],
                        "releases": [{"id": "rel-789", "title": "Test Album", "date": "2020-01-01", "country": "US"}],
                        "genres": [{"name": "rock", "count": 5}],
                    }
                ],
                "count": 1,
            },
        )
    )
    # Mock the release lookup for label enrichment
    respx.get(f"{MB_API_BASE}/release/rel-789").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "rel-789",
                "title": "Test Album",
                "date": "2020-01-01",
                "country": "US",
                "label-info": [{"label": {"name": "Test Label"}, "catalog-number": "TL-001"}],
            },
        )
    )

    result = await client.lookup_recording_by_isrc("USRC12345678")
    assert result is not None
    assert result.mbid == "rec-123"
    assert result.title == "Test Song"
    assert len(result.genres) == 1
    assert result.genres[0].name == "rock"
    # Should cache the result
    mock_cache.set.assert_awaited()


@respx.mock
@pytest.mark.asyncio
async def test_lookup_returns_cached_result(client: MusicBrainzClient, mock_cache: AsyncMock) -> None:
    mock_cache.get.return_value = {
        "id": "rec-cached",
        "title": "Cached Song",
        "artist-credit": [],
        "releases": [],
        "genres": [],
    }
    result = await client.lookup_recording_by_isrc("USRC99999999")
    assert result is not None
    assert result.mbid == "rec-cached"
    assert result.title == "Cached Song"


@respx.mock
@pytest.mark.asyncio
async def test_lookup_returns_none_on_empty_results(client: MusicBrainzClient, mock_cache: AsyncMock) -> None:
    respx.get(f"{MB_API_BASE}/recording").mock(return_value=httpx.Response(200, json={"recordings": [], "count": 0}))
    result = await client.lookup_recording_by_isrc("USRC00000000")
    assert result is None


@respx.mock
@pytest.mark.asyncio
async def test_lookup_returns_none_on_error(client: MusicBrainzClient, mock_cache: AsyncMock) -> None:
    respx.get(f"{MB_API_BASE}/recording").mock(return_value=httpx.Response(503))
    result = await client.lookup_recording_by_isrc("USRC00000000")
    assert result is None


@respx.mock
@pytest.mark.asyncio
async def test_get_artist_by_mbid(client: MusicBrainzClient, mock_cache: AsyncMock) -> None:
    respx.get(f"{MB_API_BASE}/artist/art-456").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "art-456",
                "name": "Test Artist",
                "sort-name": "Artist, Test",
                "disambiguation": "the rock band",
                "area": {"name": "London"},
                "life-span": {"begin": "1990"},
                "genres": [{"name": "rock", "count": 10}],
            },
        )
    )
    result = await client.get_artist("art-456")
    assert result is not None
    assert result.name == "Test Artist"
    assert result.area == "London"
    assert result.begin_date == "1990"
    assert len(result.genres) == 1
