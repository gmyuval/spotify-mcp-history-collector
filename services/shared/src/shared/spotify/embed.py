"""Fetch playlist tracks from Spotify's embed endpoint (no auth required).

Spotify's embed page (``/embed/playlist/{id}``) includes a ``__NEXT_DATA__``
JSON blob with complete track listings. This is used as a fallback when the
Spotify Web API returns 403 (Development Mode restriction).
"""

import asyncio
import json
import logging
import random
import re
import time
from functools import reduce
from typing import Any

import httpx

from shared.spotify.constants import (
    DEFAULT_EMBED_MAX_RETRIES,
    DEFAULT_EMBED_MIN_REQUEST_INTERVAL,
    DEFAULT_EMBED_REQUEST_TIMEOUT,
    DEFAULT_EMBED_RETRY_BASE_DELAY,
    DEFAULT_EMBED_USER_AGENT,
    EMBED_BASE_URL,
)
from shared.spotify.exceptions import SpotifyEmbedError
from shared.spotify.models import EmbedTrackItem

logger = logging.getLogger(__name__)

# Regex to locate the __NEXT_DATA__ JSON blob in Spotify's embed HTML.
_NEXT_DATA_RE = re.compile(
    r'<script\s+id="__NEXT_DATA__"\s+type="application/json">\s*({.*?})\s*</script>',
    re.DOTALL,
)

# Known JSON paths to the ``trackList`` array inside ``__NEXT_DATA__``.
# Spotify occasionally restructures the embed JSON; add new paths here.
_TRACK_LIST_PATHS: list[list[str]] = [
    ["props", "pageProps", "state", "data", "entity", "trackList"],
]

# Spotify track URI prefix used in embed track items.
_SPOTIFY_TRACK_PREFIX = "spotify:track:"

# Fields in embed track items that may contain the Spotify track URI.
_TRACK_URI_FIELDS = ("uid", "uri")


class SpotifyEmbedClient:
    """Async client for fetching playlist tracks from Spotify's embed page.

    Uses the ``__NEXT_DATA__`` JSON blob that Spotify embeds in the page HTML.
    No authentication is required. Rate-limited to avoid abuse.

    Args:
        request_timeout: HTTP request timeout in seconds.
        min_request_interval: Minimum seconds between consecutive requests.
        user_agent: User-Agent header for HTTP requests.
    """

    def __init__(
        self,
        *,
        request_timeout: float = DEFAULT_EMBED_REQUEST_TIMEOUT,
        min_request_interval: float = DEFAULT_EMBED_MIN_REQUEST_INTERVAL,
        user_agent: str = DEFAULT_EMBED_USER_AGENT,
        max_retries: int = DEFAULT_EMBED_MAX_RETRIES,
        retry_base_delay: float = DEFAULT_EMBED_RETRY_BASE_DELAY,
    ) -> None:
        self._request_timeout = request_timeout
        self._min_request_interval = min_request_interval
        self._user_agent = user_agent
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._last_request_time: float = 0.0
        self._lock = asyncio.Lock()

    # ── Public API ────────────────────────────────────────────────────

    async def fetch_playlist_tracks(self, playlist_id: str) -> list[EmbedTrackItem]:
        """Fetch playlist tracks from Spotify's embed endpoint.

        Args:
            playlist_id: Spotify playlist ID.

        Returns:
            List of tracks with IDs, names, artists, and durations.

        Raises:
            SpotifyEmbedError: If the embed page can't be fetched or parsed.
        """
        async with self._lock:
            return await self._fetch_with_retries(playlist_id)

    async def _fetch_with_retries(self, playlist_id: str) -> list[EmbedTrackItem]:
        """Fetch with rate limiting and retry logic. Must be called under ``_lock``."""
        await self._enforce_rate_limit()

        url = f"{EMBED_BASE_URL}/{playlist_id}"
        last_exc: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self._request_timeout) as client:
                    response = await client.get(url, headers={"User-Agent": self._user_agent})
                self._last_request_time = time.monotonic()
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    delay = self._retry_base_delay * (2**attempt) + random.uniform(0, 0.5)
                    logger.warning(
                        "Embed request failed (attempt %d/%d): %s — retrying in %.1fs",
                        attempt + 1,
                        self._max_retries + 1,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise SpotifyEmbedError(f"Failed to fetch embed page for playlist {playlist_id}: {exc}") from exc

            if response.status_code == 429 or response.status_code >= 500:
                last_exc = SpotifyEmbedError(
                    f"Embed page returned HTTP {response.status_code} for playlist {playlist_id}"
                )
                if attempt < self._max_retries:
                    delay = self._compute_retry_delay(response, attempt)
                    logger.warning(
                        "Embed returned %d (attempt %d/%d) — retrying in %.1fs",
                        response.status_code,
                        attempt + 1,
                        self._max_retries + 1,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise last_exc

            if response.status_code != 200:
                raise SpotifyEmbedError(f"Embed page returned HTTP {response.status_code} for playlist {playlist_id}")

            return self._parse_embed_html(response.text, playlist_id)

        # Should not reach here, but satisfy type checker
        raise last_exc or SpotifyEmbedError(f"Failed to fetch embed page for playlist {playlist_id}")

    def _compute_retry_delay(self, response: httpx.Response, attempt: int) -> float:
        """Compute retry delay, honouring Retry-After header on 429."""
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    return max(float(retry_after), 0.0)
                except ValueError:
                    pass
        jitter: float = random.uniform(0, 0.5)
        delay: float = self._retry_base_delay * (2**attempt) + jitter
        return delay

    # ── Private helpers ───────────────────────────────────────────────

    async def _enforce_rate_limit(self) -> None:
        """Sleep if needed to respect the minimum request interval."""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self._min_request_interval:
            await asyncio.sleep(self._min_request_interval - elapsed)

    @staticmethod
    def _parse_embed_html(html: str, playlist_id: str) -> list[EmbedTrackItem]:
        """Parse ``__NEXT_DATA__`` JSON from embed HTML to extract tracks."""
        match = _NEXT_DATA_RE.search(html)
        if not match:
            raise SpotifyEmbedError(f"No __NEXT_DATA__ found in embed page for playlist {playlist_id}")

        try:
            data: dict[str, Any] = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise SpotifyEmbedError(f"Failed to parse __NEXT_DATA__ JSON for playlist {playlist_id}: {exc}") from exc

        track_list = SpotifyEmbedClient._extract_track_list(data)
        if track_list is None:
            raise SpotifyEmbedError(f"No trackList found in embed data for playlist {playlist_id}")

        tracks: list[EmbedTrackItem] = []
        for item in track_list:
            track_id = SpotifyEmbedClient._extract_track_id(item)

            subtitle: str = item.get("subtitle", "")
            artists = [a.strip() for a in subtitle.split(",") if a.strip()] if subtitle else []

            tracks.append(
                EmbedTrackItem(
                    track_id=track_id,
                    name=item.get("title", ""),
                    artists=artists,
                    duration_ms=item.get("duration", 0),
                    unavailable=track_id is None,
                )
            )

        logger.info("Extracted %d tracks from embed page for playlist %s", len(tracks), playlist_id)
        return tracks

    @staticmethod
    def _extract_track_list(data: dict[str, Any]) -> list[Any] | None:
        """Navigate ``__NEXT_DATA__`` JSON to find the ``trackList`` array.

        Tries each known path in ``_TRACK_LIST_PATHS`` via chained ``dict.get``,
        then falls back to a recursive deep search.
        """
        for path in _TRACK_LIST_PATHS:
            try:
                result: Any = reduce(lambda d, key: d[key], path, data)
                if isinstance(result, list):
                    return result
            except KeyError, TypeError, IndexError:
                continue

        return SpotifyEmbedClient._deep_find_list(data, "trackList")

    @staticmethod
    def _deep_find_list(obj: object, key: str) -> list[Any] | None:
        """Recursively search for a key whose value is a list.

        Walks dicts and lists depth-first, returning the first match.
        This is a fallback for when known JSON paths change — it ensures
        we can still find ``trackList`` regardless of nesting depth.
        """
        if isinstance(obj, dict):
            if key in obj and isinstance(obj[key], list):
                return list(obj[key])
            for v in obj.values():
                result = SpotifyEmbedClient._deep_find_list(v, key)
                if result is not None:
                    return result
        elif isinstance(obj, list):
            for item in obj:
                result = SpotifyEmbedClient._deep_find_list(item, key)
                if result is not None:
                    return result
        return None

    @staticmethod
    def _extract_track_id(item: dict[str, Any]) -> str | None:
        """Extract Spotify track ID from an embed track item.

        Checks each field in ``_TRACK_URI_FIELDS`` for a ``spotify:track:``
        prefixed value and returns the bare track ID.
        """
        for field_name in _TRACK_URI_FIELDS:
            value: str = item.get(field_name, "")
            if value.startswith(_SPOTIFY_TRACK_PREFIX):
                return value.removeprefix(_SPOTIFY_TRACK_PREFIX)
        return None
