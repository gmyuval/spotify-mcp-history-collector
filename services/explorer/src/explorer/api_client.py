"""API client for the explorer frontend — forwards user JWT to the API."""

from typing import Any

import httpx


class ApiError(Exception):
    """Raised when the API returns an error response."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"API error {status_code}: {detail}")


class ExplorerApiClient:
    """HTTP client that talks to /api/me/* endpoints using the user's JWT."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=15.0)

    async def close(self) -> None:
        """Close underlying HTTP client."""
        await self._client.aclose()

    async def _request(self, method: str, path: str, access_token: str, **kwargs: Any) -> Any:
        """Make an authenticated API request."""
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            resp = await self._client.request(method, path, headers=headers, **kwargs)
        except httpx.TransportError as exc:
            raise ApiError(503, f"API unavailable: {exc}") from exc
        if resp.status_code == 401:
            raise ApiError(401, "Authentication required")
        if resp.status_code >= 400:
            try:
                body = resp.json()
                detail = body.get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise ApiError(resp.status_code, str(detail))
        return resp.json()

    async def get_dashboard(self, access_token: str) -> dict[str, Any]:
        """GET /api/me/dashboard"""
        result: dict[str, Any] = await self._request("GET", "/api/me/dashboard", access_token)
        return result

    async def get_history(
        self,
        access_token: str,
        limit: int = 50,
        offset: int = 0,
        q: str | None = None,
    ) -> dict[str, Any]:
        """GET /api/me/history"""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if q:
            params["q"] = q
        result: dict[str, Any] = await self._request("GET", "/api/me/history", access_token, params=params)
        return result

    async def get_top_artists(self, access_token: str, days: int = 90, limit: int = 20) -> list[dict[str, Any]]:
        """GET /api/me/top-artists"""
        result: list[dict[str, Any]] = await self._request(
            "GET", "/api/me/top-artists", access_token, params={"days": days, "limit": limit}
        )
        return result

    async def get_top_tracks(self, access_token: str, days: int = 90, limit: int = 20) -> list[dict[str, Any]]:
        """GET /api/me/top-tracks"""
        result: list[dict[str, Any]] = await self._request(
            "GET", "/api/me/top-tracks", access_token, params={"days": days, "limit": limit}
        )
        return result

    async def get_playlists(self, access_token: str) -> list[dict[str, Any]]:
        """GET /api/me/playlists"""
        result: list[dict[str, Any]] = await self._request("GET", "/api/me/playlists", access_token)
        return result

    async def get_profile(self, access_token: str) -> dict[str, Any]:
        """GET /api/me/profile"""
        result: dict[str, Any] = await self._request("GET", "/api/me/profile", access_token)
        return result

    async def get_playlist(self, access_token: str, spotify_playlist_id: str) -> dict[str, Any]:
        """GET /api/me/playlists/{spotify_playlist_id}"""
        result: dict[str, Any] = await self._request("GET", f"/api/me/playlists/{spotify_playlist_id}", access_token)
        return result

    async def exchange_google_email(self, email: str, internal_api_key: str) -> dict[str, Any] | None:
        """POST /auth/exchange-google — exchange Google email for JWT tokens.

        Returns dict with access_token, refresh_token, etc., or None on failure.
        """
        headers = {"X-Internal-API-Key": internal_api_key}
        try:
            resp = await self._client.post(
                "/auth/exchange-google",
                json={"email": email},
                headers=headers,
            )
        except httpx.TransportError:
            return None
        if resp.status_code != 200:
            return None
        result: dict[str, Any] = resp.json()
        return result
