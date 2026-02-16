"""Spotify Web API async client with retry and rate-limit handling."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from shared.spotify.constants import (
    ALBUMS_URL,
    ARTISTS_URL,
    AUDIO_FEATURES_URL,
    DEFAULT_CONCURRENCY_LIMIT,
    DEFAULT_MAX_RETRIES,
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_RETRY_BASE_DELAY,
    PLAYLIST_URL,
    RECENTLY_PLAYED_URL,
    SEARCH_URL,
    TOP_ARTISTS_URL,
    TOP_TRACKS_URL,
    TRACKS_URL,
    USER_PLAYLISTS_URL,
)
from shared.spotify.exceptions import (
    SpotifyAuthError,
    SpotifyRateLimitError,
    SpotifyRequestError,
    SpotifyServerError,
)
from shared.spotify.models import (
    BatchArtistsResponse,
    BatchAudioFeaturesResponse,
    BatchTracksResponse,
    RecentlyPlayedResponse,
    SpotifyAlbumFull,
    SpotifyArtistFull,
    SpotifyPlaylist,
    SpotifyPlaylistTrackItem,
    SpotifyPlaylistTracks,
    SpotifySearchResponse,
    SpotifySnapshotResponse,
    SpotifyTrack,
    TopArtistsResponse,
    TopTracksResponse,
    UserPlaylistsResponse,
)

logger = logging.getLogger(__name__)


class SpotifyClient:
    """Async Spotify Web API client.

    Takes an access_token per-instance (stateless re: auth). Handles 429 backoff
    and 5xx retries internally. Supports optional on_token_expired async callback
    for 401 retry.
    """

    def __init__(
        self,
        access_token: str,
        *,
        on_token_expired: Callable[[], Awaitable[str]] | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_base_delay: float = DEFAULT_RETRY_BASE_DELAY,
        concurrency_limit: int = DEFAULT_CONCURRENCY_LIMIT,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
    ) -> None:
        self._access_token = access_token
        self._on_token_expired = on_token_expired
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._semaphore = asyncio.Semaphore(concurrency_limit)
        self._request_timeout = request_timeout

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str | int] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Send an HTTP request with retry logic for 429/5xx and 401 callback.

        Retry loop:
        1. Send request with Bearer token
        2. If 2xx: return response
        3. If 401 and callback and not already retried: get new token, retry once
        4. If 429: sleep(Retry-After header or exponential backoff), continue
        5. If 5xx: sleep(exponential backoff), continue
        6. If other 4xx: raise SpotifyRequestError immediately
        """
        already_retried_401 = False
        last_status = 0
        last_retry_after: float | None = None

        for attempt in range(self._max_retries + 1):
            async with self._semaphore:
                async with httpx.AsyncClient(timeout=self._request_timeout) as client:
                    response = await client.request(
                        method,
                        url,
                        params=params,
                        json=json_body,
                        headers={"Authorization": f"Bearer {self._access_token}"},
                    )

            last_status = response.status_code

            if 200 <= response.status_code < 300:
                return response

            # 401 Unauthorized — try token refresh once
            if response.status_code == 401:
                if self._on_token_expired and not already_retried_401:
                    already_retried_401 = True
                    logger.info("Spotify returned 401, attempting token refresh")
                    self._access_token = await self._on_token_expired()
                    continue
                raise SpotifyAuthError("Spotify returned 401 Unauthorized")

            # 429 Rate Limited
            if response.status_code == 429:
                retry_after_header = response.headers.get("Retry-After")
                if retry_after_header:
                    delay = float(retry_after_header)
                else:
                    delay = self._retry_base_delay * (2**attempt)
                last_retry_after = delay
                if attempt < self._max_retries:
                    logger.warning(
                        "Spotify rate limited (429), sleeping %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        self._max_retries,
                    )
                    await asyncio.sleep(delay)
                    continue

            # 5xx Server Error
            elif response.status_code >= 500:
                if attempt < self._max_retries:
                    delay = self._retry_base_delay * (2**attempt)
                    logger.warning(
                        "Spotify server error %d, sleeping %.1fs (attempt %d/%d)",
                        response.status_code,
                        delay,
                        attempt + 1,
                        self._max_retries,
                    )
                    await asyncio.sleep(delay)
                    continue

            # Other 4xx — non-retryable
            else:
                detail = f"HTTP {response.status_code}"
                try:
                    error_body = response.json()
                    detail = error_body.get("error", {}).get("message", detail)
                except Exception:
                    if response.text:
                        detail = response.text[:200]
                raise SpotifyRequestError(status_code=response.status_code, detail=detail)

        # Exhausted retries
        if last_status == 429:
            raise SpotifyRateLimitError(retry_after=last_retry_after)
        raise SpotifyServerError(status_code=last_status, detail="Max retries exhausted")

    # -------------------------------------------------------------------
    # Public API methods
    # -------------------------------------------------------------------

    async def get_recently_played(
        self,
        *,
        limit: int = 50,
        before: int | None = None,
        after: int | None = None,
    ) -> RecentlyPlayedResponse:
        """GET /me/player/recently-played."""
        params: dict[str, str | int] = {"limit": limit}
        if before is not None:
            params["before"] = before
        if after is not None:
            params["after"] = after
        response = await self._request("GET", RECENTLY_PLAYED_URL, params=params)
        return RecentlyPlayedResponse.model_validate(response.json())

    async def get_tracks(self, track_ids: list[str]) -> BatchTracksResponse:
        """GET /tracks?ids=... (max 50 per request)."""
        if not track_ids:
            return BatchTracksResponse()
        response = await self._request("GET", TRACKS_URL, params={"ids": ",".join(track_ids[:50])})
        return BatchTracksResponse.model_validate(response.json())

    async def get_artists(self, artist_ids: list[str]) -> BatchArtistsResponse:
        """GET /artists?ids=... (max 50 per request)."""
        if not artist_ids:
            return BatchArtistsResponse()
        response = await self._request("GET", ARTISTS_URL, params={"ids": ",".join(artist_ids[:50])})
        return BatchArtistsResponse.model_validate(response.json())

    async def get_audio_features(self, track_ids: list[str]) -> BatchAudioFeaturesResponse:
        """GET /audio-features?ids=... (max 100 per request)."""
        if not track_ids:
            return BatchAudioFeaturesResponse()
        response = await self._request("GET", AUDIO_FEATURES_URL, params={"ids": ",".join(track_ids[:100])})
        return BatchAudioFeaturesResponse.model_validate(response.json())

    async def get_top_artists(
        self,
        *,
        time_range: str = "medium_term",
        limit: int = 20,
        offset: int = 0,
    ) -> TopArtistsResponse:
        """GET /me/top/artists."""
        response = await self._request(
            "GET",
            TOP_ARTISTS_URL,
            params={"time_range": time_range, "limit": limit, "offset": offset},
        )
        return TopArtistsResponse.model_validate(response.json())

    async def get_top_tracks(
        self,
        *,
        time_range: str = "medium_term",
        limit: int = 20,
        offset: int = 0,
    ) -> TopTracksResponse:
        """GET /me/top/tracks."""
        response = await self._request(
            "GET",
            TOP_TRACKS_URL,
            params={"time_range": time_range, "limit": limit, "offset": offset},
        )
        return TopTracksResponse.model_validate(response.json())

    async def search(
        self,
        query: str,
        *,
        search_type: str = "track",
        limit: int = 20,
        offset: int = 0,
    ) -> SpotifySearchResponse:
        """GET /search."""
        response = await self._request(
            "GET",
            SEARCH_URL,
            params={"q": query, "type": search_type, "limit": limit, "offset": offset},
        )
        return SpotifySearchResponse.model_validate(response.json())

    # -------------------------------------------------------------------
    # Single-resource info methods
    # -------------------------------------------------------------------

    async def get_track(self, track_id: str) -> SpotifyTrack:
        """GET /tracks/{id}."""
        response = await self._request("GET", f"{TRACKS_URL}/{track_id}")
        return SpotifyTrack.model_validate(response.json())

    async def get_artist(self, artist_id: str) -> SpotifyArtistFull:
        """GET /artists/{id}."""
        response = await self._request("GET", f"{ARTISTS_URL}/{artist_id}")
        return SpotifyArtistFull.model_validate(response.json())

    async def get_album(self, album_id: str) -> SpotifyAlbumFull:
        """GET /albums/{id}."""
        response = await self._request("GET", f"{ALBUMS_URL}/{album_id}")
        return SpotifyAlbumFull.model_validate(response.json())

    # -------------------------------------------------------------------
    # Playlist read methods
    # -------------------------------------------------------------------

    async def get_user_playlists(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> UserPlaylistsResponse:
        """GET /me/playlists."""
        response = await self._request(
            "GET",
            USER_PLAYLISTS_URL,
            params={"limit": limit, "offset": offset},
        )
        return UserPlaylistsResponse.model_validate(response.json())

    async def get_playlist(self, playlist_id: str) -> SpotifyPlaylist:
        """GET /playlists/{id}."""
        response = await self._request("GET", f"{PLAYLIST_URL}/{playlist_id}")
        return SpotifyPlaylist.model_validate(response.json())

    async def get_playlist_all_tracks(
        self,
        playlist_id: str,
        *,
        page_size: int = 100,
        max_tracks: int = 10_000,
    ) -> list[SpotifyPlaylistTrackItem]:
        """Fetch all tracks for a playlist, following pagination.

        Args:
            playlist_id: Spotify playlist ID.
            page_size: Number of tracks per API request (max 100).
            max_tracks: Safety cap to prevent runaway loops (Spotify's
                own limit is 10,000 tracks per playlist).

        Returns:
            Complete list of playlist track items across all pages.
        """
        all_items: list[SpotifyPlaylistTrackItem] = []
        url: str | None = f"{PLAYLIST_URL}/{playlist_id}/tracks"
        params: dict[str, str | int] | None = {"limit": min(page_size, 100), "offset": 0}

        while url and len(all_items) < max_tracks:
            response = await self._request("GET", url, params=params)
            page = SpotifyPlaylistTracks.model_validate(response.json())
            all_items.extend(page.items)

            # Spotify's `next` is a full absolute URL with limit/offset baked in.
            url = page.next
            params = None  # subsequent requests use the full `next` URL as-is

        return all_items[:max_tracks]

    # -------------------------------------------------------------------
    # Playlist write methods
    # -------------------------------------------------------------------

    async def create_playlist(
        self,
        name: str,
        *,
        description: str = "",
        public: bool = True,
    ) -> SpotifyPlaylist:
        """POST /me/playlists."""
        response = await self._request(
            "POST",
            USER_PLAYLISTS_URL,
            json_body={"name": name, "description": description, "public": public},
        )
        return SpotifyPlaylist.model_validate(response.json())

    async def add_tracks_to_playlist(
        self,
        playlist_id: str,
        uris: list[str],
        *,
        position: int | None = None,
    ) -> SpotifySnapshotResponse:
        """POST /playlists/{id}/items."""
        body: dict[str, Any] = {"uris": uris}
        if position is not None:
            body["position"] = position
        response = await self._request(
            "POST",
            f"{PLAYLIST_URL}/{playlist_id}/items",
            json_body=body,
        )
        return SpotifySnapshotResponse.model_validate(response.json())

    async def remove_tracks_from_playlist(
        self,
        playlist_id: str,
        uris: list[str],
    ) -> SpotifySnapshotResponse:
        """DELETE /playlists/{id}/items."""
        body: dict[str, Any] = {"items": [{"uri": uri} for uri in uris]}
        response = await self._request(
            "DELETE",
            f"{PLAYLIST_URL}/{playlist_id}/items",
            json_body=body,
        )
        return SpotifySnapshotResponse.model_validate(response.json())

    async def update_playlist_details(
        self,
        playlist_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        public: bool | None = None,
    ) -> None:
        """PUT /playlists/{id} — returns 200 with empty body on success."""
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        if public is not None:
            body["public"] = public
        await self._request(
            "PUT",
            f"{PLAYLIST_URL}/{playlist_id}",
            json_body=body,
        )
