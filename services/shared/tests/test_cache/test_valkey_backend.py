"""Tests for ValkeyCacheBackend with mocked redis client."""

from unittest.mock import AsyncMock, patch

import pytest

from shared.cache.valkey_backend import ValkeyCacheBackend


@pytest.fixture
def mock_redis() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def backend(mock_redis: AsyncMock) -> ValkeyCacheBackend:
    return ValkeyCacheBackend(mock_redis)


@pytest.mark.asyncio
async def test_get_returns_none_on_miss(backend: ValkeyCacheBackend, mock_redis: AsyncMock) -> None:
    mock_redis.get.return_value = None
    result = await backend.get("sp:track:abc123")
    assert result is None
    mock_redis.get.assert_awaited_once_with("sp:track:abc123")


@pytest.mark.asyncio
async def test_get_returns_parsed_json(backend: ValkeyCacheBackend, mock_redis: AsyncMock) -> None:
    mock_redis.get.return_value = '{"popularity": 78, "isrc": "USBL10500280"}'
    result = await backend.get("sp:track:abc123")
    assert result == {"popularity": 78, "isrc": "USBL10500280"}


@pytest.mark.asyncio
async def test_get_deletes_corrupt_entry(backend: ValkeyCacheBackend, mock_redis: AsyncMock) -> None:
    mock_redis.get.return_value = "not valid json{{"
    result = await backend.get("sp:track:abc123")
    assert result is None
    mock_redis.delete.assert_awaited_once_with("sp:track:abc123")


@pytest.mark.asyncio
async def test_set_stores_json_with_ttl(backend: ValkeyCacheBackend, mock_redis: AsyncMock) -> None:
    await backend.set("sp:track:abc123", {"popularity": 78}, 86400)
    mock_redis.setex.assert_awaited_once_with("sp:track:abc123", 86400, '{"popularity": 78}')


@pytest.mark.asyncio
async def test_delete_removes_key(backend: ValkeyCacheBackend, mock_redis: AsyncMock) -> None:
    await backend.delete("sp:track:abc123")
    mock_redis.delete.assert_awaited_once_with("sp:track:abc123")


@pytest.mark.asyncio
async def test_close_calls_aclose(backend: ValkeyCacheBackend, mock_redis: AsyncMock) -> None:
    await backend.close()
    mock_redis.aclose.assert_awaited_once()


def test_from_url_translates_valkey_scheme() -> None:
    with patch("shared.cache.valkey_backend.Redis") as mock_redis_cls:
        mock_redis_cls.from_url.return_value = AsyncMock()
        backend = ValkeyCacheBackend.from_url("valkey://host:6379/0")
        mock_redis_cls.from_url.assert_called_once_with("redis://host:6379/0", decode_responses=True)
        assert isinstance(backend, ValkeyCacheBackend)


def test_from_url_translates_valkeys_scheme() -> None:
    with patch("shared.cache.valkey_backend.Redis") as mock_redis_cls:
        mock_redis_cls.from_url.return_value = AsyncMock()
        backend = ValkeyCacheBackend.from_url("valkeys://user:pass@host:25061")
        mock_redis_cls.from_url.assert_called_once_with("rediss://user:pass@host:25061", decode_responses=True)
        assert isinstance(backend, ValkeyCacheBackend)


def test_from_url_keeps_redis_scheme() -> None:
    with patch("shared.cache.valkey_backend.Redis") as mock_redis_cls:
        mock_redis_cls.from_url.return_value = AsyncMock()
        ValkeyCacheBackend.from_url("redis://localhost:6379")
        mock_redis_cls.from_url.assert_called_once_with("redis://localhost:6379", decode_responses=True)
