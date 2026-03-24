"""API client for the explorer frontend — forwards user JWT to the API."""

from typing import Any, TypedDict

import httpx

# -- TypedDicts for structured API response shapes --


class MemoryPlaylistItem(TypedDict):
    """A single memory playlist summary as returned by the list endpoint."""

    playlist_id: str
    name: str
    description: str | None
    created_at: str
    updated_at: str
    intent_tags: list[str]
    track_count: int


class PaginatedMemoryPlaylists(TypedDict):
    """Paginated list of memory playlist summaries."""

    items: list[MemoryPlaylistItem]
    total: int
    limit: int
    offset: int


class MemoryPlaylistEvent(TypedDict):
    """A single playlist mutation event."""

    event_id: str
    timestamp: str
    type: str
    payload: dict[str, Any]


class MemoryPlaylistTrack(TypedDict):
    """A resolved track in a memory playlist."""

    spotify_track_id: str
    track_name: str | None
    artists: list[dict[str, Any]]


class MemoryPlaylistDetail(TypedDict):
    """Full memory playlist detail with tracks and recent events."""

    playlist_id: str
    name: str
    description: str | None
    created_at: str
    updated_at: str
    intent_tags: list[str]
    seed_context: dict[str, Any]
    tracks: list[MemoryPlaylistTrack]
    recent_events: list[MemoryPlaylistEvent]
    total_events: int


class PaginatedMemoryPlaylistEvents(TypedDict):
    """Paginated list of playlist mutation events."""

    items: list[MemoryPlaylistEvent]
    total: int
    limit: int
    offset: int


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
        if resp.status_code == 204:
            return None
        return resp.json()

    async def get_dashboard(self, access_token: str, days: int | None = None) -> dict[str, Any]:
        """GET /api/me/dashboard"""
        params: dict[str, Any] = {}
        if days is not None:
            params["days"] = days
        result: dict[str, Any] = await self._request("GET", "/api/me/dashboard", access_token, params=params or None)
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

    async def get_tracks(
        self,
        access_token: str,
        limit: int = 50,
        offset: int = 0,
        sort: str = "play_count",
        q: str | None = None,
        days: int | None = None,
    ) -> dict[str, Any]:
        """GET /api/me/tracks"""
        params: dict[str, Any] = {"limit": limit, "offset": offset, "sort": sort}
        if q:
            params["q"] = q
        if days is not None:
            params["days"] = days
        result: dict[str, Any] = await self._request("GET", "/api/me/tracks", access_token, params=params)
        return result

    async def get_artists(
        self,
        access_token: str,
        limit: int = 50,
        offset: int = 0,
        sort: str = "play_count",
        q: str | None = None,
        days: int | None = None,
    ) -> dict[str, Any]:
        """GET /api/me/artists"""
        params: dict[str, Any] = {"limit": limit, "offset": offset, "sort": sort}
        if q:
            params["q"] = q
        if days is not None:
            params["days"] = days
        result: dict[str, Any] = await self._request("GET", "/api/me/artists", access_token, params=params)
        return result

    async def get_playlists(self, access_token: str) -> list[dict[str, Any]]:
        """GET /api/me/playlists"""
        result: list[dict[str, Any]] = await self._request("GET", "/api/me/playlists", access_token)
        return result

    async def refresh_playlists(self, access_token: str) -> list[dict[str, Any]]:
        """POST /api/me/playlists/refresh — force-refresh from Spotify"""
        result: list[dict[str, Any]] = await self._request("POST", "/api/me/playlists/refresh", access_token)
        return result

    async def get_profile(self, access_token: str) -> dict[str, Any]:
        """GET /api/me/profile"""
        result: dict[str, Any] = await self._request("GET", "/api/me/profile", access_token)
        return result

    async def get_playlist(self, access_token: str, spotify_playlist_id: str) -> dict[str, Any]:
        """GET /api/me/playlists/{spotify_playlist_id}"""
        result: dict[str, Any] = await self._request("GET", f"/api/me/playlists/{spotify_playlist_id}", access_token)
        return result

    async def fetch_playlist_tracks(self, access_token: str, spotify_playlist_id: str) -> dict[str, Any]:
        """POST /api/me/playlists/{spotify_playlist_id}/fetch-tracks"""
        result: dict[str, Any] = await self._request(
            "POST", f"/api/me/playlists/{spotify_playlist_id}/fetch-tracks", access_token
        )
        return result

    async def get_taste_profile(self, access_token: str) -> dict[str, Any]:
        """GET /api/me/taste-profile"""
        result: dict[str, Any] = await self._request("GET", "/api/me/taste-profile", access_token)
        return result

    async def update_taste_profile(
        self, access_token: str, patch: dict[str, Any], reason: str | None = None
    ) -> dict[str, Any]:
        """PATCH /api/me/taste-profile"""
        body: dict[str, Any] = {"patch": patch}
        if reason:
            body["reason"] = reason
        result: dict[str, Any] = await self._request("PATCH", "/api/me/taste-profile", access_token, json=body)
        return result

    async def clear_taste_profile(self, access_token: str) -> None:
        """DELETE /api/me/taste-profile"""
        await self._request("DELETE", "/api/me/taste-profile", access_token)

    async def get_preference_events(self, access_token: str, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        """GET /api/me/preference-events"""
        result: dict[str, Any] = await self._request(
            "GET", "/api/me/preference-events", access_token, params={"limit": limit, "offset": offset}
        )
        return result

    async def get_memory_playlists(
        self, access_token: str, limit: int = 20, offset: int = 0
    ) -> PaginatedMemoryPlaylists:
        """Fetch paginated list of assistant-tracked playlists."""
        result: PaginatedMemoryPlaylists = await self._request(
            "GET", "/api/me/memory-playlists", access_token, params={"limit": limit, "offset": offset}
        )
        return result

    async def get_memory_playlist(self, access_token: str, playlist_id: str) -> MemoryPlaylistDetail:
        """Fetch a single memory playlist with track IDs and recent events."""
        result: MemoryPlaylistDetail = await self._request(
            "GET", f"/api/me/memory-playlists/{playlist_id}", access_token
        )
        return result

    async def get_memory_playlist_events(
        self, access_token: str, playlist_id: str, limit: int = 20, offset: int = 0
    ) -> PaginatedMemoryPlaylistEvents:
        """Fetch paginated mutation events for a memory playlist."""
        result: PaginatedMemoryPlaylistEvents = await self._request(
            "GET",
            f"/api/me/memory-playlists/{playlist_id}/events",
            access_token,
            params={"limit": limit, "offset": offset},
        )
        return result

    async def get_tokens(self, access_token: str) -> dict[str, Any]:
        """GET /api/me/tokens — list active API tokens."""
        result: dict[str, Any] = await self._request("GET", "/api/me/tokens", access_token)
        return result

    async def create_token(self, access_token: str, name: str) -> dict[str, Any]:
        """POST /api/me/tokens — create a new API token."""
        result: dict[str, Any] = await self._request("POST", "/api/me/tokens", access_token, json={"name": name})
        return result

    async def revoke_token(self, access_token: str, token_id: int) -> None:
        """DELETE /api/me/tokens/{token_id} — revoke an API token."""
        await self._request("DELETE", f"/api/me/tokens/{token_id}", access_token)

    async def get_heatmap(self, access_token: str, days: int = 90) -> dict[str, Any]:
        """GET /api/me/analytics/heatmap — weekday x hour heatmap."""
        result: dict[str, Any] = await self._request(
            "GET", "/api/me/analytics/heatmap", access_token, params={"days": days}
        )
        return result

    async def get_timeline(self, access_token: str, days: int = 90, bucket: str = "week") -> dict[str, Any]:
        """GET /api/me/analytics/timeline — plays over time."""
        result: dict[str, Any] = await self._request(
            "GET", "/api/me/analytics/timeline", access_token, params={"days": days, "bucket": bucket}
        )
        return result

    async def get_genres(self, access_token: str, days: int = 90) -> dict[str, Any]:
        """GET /api/me/analytics/genres — genre distribution."""
        result: dict[str, Any] = await self._request(
            "GET", "/api/me/analytics/genres", access_token, params={"days": days}
        )
        return result

    async def get_track_detail(self, access_token: str, track_id: int) -> dict[str, Any]:
        """GET /api/me/tracks/{track_id} — track detail with stats and enrichment."""
        result: dict[str, Any] = await self._request("GET", f"/api/me/tracks/{track_id}", access_token)
        return result

    async def get_artist_detail(self, access_token: str, artist_id: int) -> dict[str, Any]:
        """GET /api/me/artists/{artist_id} — artist detail with stats and enrichment."""
        result: dict[str, Any] = await self._request("GET", f"/api/me/artists/{artist_id}", access_token)
        return result

    async def get_album_detail(self, access_token: str, album_spotify_id: str) -> dict[str, Any]:
        """GET /api/me/albums/{album_spotify_id} — album detail with stats and enrichment."""
        result: dict[str, Any] = await self._request("GET", f"/api/me/albums/{album_spotify_id}", access_token)
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
