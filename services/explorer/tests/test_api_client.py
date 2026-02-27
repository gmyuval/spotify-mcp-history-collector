"""Tests for the ExplorerApiClient."""

import httpx
import pytest
import respx

from explorer.api_client import ApiError, ExplorerApiClient


@pytest.fixture
def api_client() -> ExplorerApiClient:
    return ExplorerApiClient(base_url="http://test-api:8000")


@respx.mock
async def test_get_dashboard(api_client: ExplorerApiClient) -> None:
    respx.get("http://test-api:8000/api/me/dashboard").mock(return_value=httpx.Response(200, json={"total_plays": 10}))
    result = await api_client.get_dashboard("token123")
    assert result["total_plays"] == 10


@respx.mock
async def test_get_history(api_client: ExplorerApiClient) -> None:
    route = respx.get("http://test-api:8000/api/me/history").mock(
        return_value=httpx.Response(200, json={"items": [], "total": 0})
    )
    result = await api_client.get_history("token123", limit=10, offset=5)
    assert result["total"] == 0
    assert route.calls[0].request.url.params["limit"] == "10"
    assert route.calls[0].request.url.params["offset"] == "5"


@respx.mock
async def test_get_playlists(api_client: ExplorerApiClient) -> None:
    respx.get("http://test-api:8000/api/me/playlists").mock(return_value=httpx.Response(200, json=[{"name": "Test"}]))
    result = await api_client.get_playlists("token123")
    assert len(result) == 1


@respx.mock
async def test_get_playlist(api_client: ExplorerApiClient) -> None:
    respx.get("http://test-api:8000/api/me/playlists/pl_1").mock(
        return_value=httpx.Response(200, json={"name": "Test", "tracks": []})
    )
    result = await api_client.get_playlist("token123", "pl_1")
    assert result["name"] == "Test"


@respx.mock
async def test_auth_header_forwarded(api_client: ExplorerApiClient) -> None:
    route = respx.get("http://test-api:8000/api/me/dashboard").mock(return_value=httpx.Response(200, json={}))
    await api_client.get_dashboard("my-jwt-token")
    assert route.calls[0].request.headers["authorization"] == "Bearer my-jwt-token"


@respx.mock
async def test_error_response(api_client: ExplorerApiClient) -> None:
    respx.get("http://test-api:8000/api/me/dashboard").mock(
        return_value=httpx.Response(403, json={"detail": "Forbidden"})
    )
    with pytest.raises(ApiError) as exc_info:
        await api_client.get_dashboard("token123")
    assert exc_info.value.status_code == 403
    assert "Forbidden" in exc_info.value.detail


@respx.mock
async def test_401_raises_api_error(api_client: ExplorerApiClient) -> None:
    respx.get("http://test-api:8000/api/me/dashboard").mock(
        return_value=httpx.Response(401, json={"detail": "Unauthorized"})
    )
    with pytest.raises(ApiError) as exc_info:
        await api_client.get_dashboard("bad-token")
    assert exc_info.value.status_code == 401


@respx.mock
async def test_transport_error_raises_api_error(api_client: ExplorerApiClient) -> None:
    respx.get("http://test-api:8000/api/me/dashboard").mock(side_effect=httpx.ConnectError("Connection refused"))
    with pytest.raises(ApiError) as exc_info:
        await api_client.get_dashboard("token123")
    assert exc_info.value.status_code == 503
    assert "API unavailable" in exc_info.value.detail
