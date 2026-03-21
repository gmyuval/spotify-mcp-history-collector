"""Async MusicBrainz API client with rate limiting and caching."""

import asyncio
import logging
from typing import Any

import httpx

from shared.cache.backend import CacheBackend
from shared.musicbrainz.constants import (
    MB_API_BASE,
    MB_ARTIST_PATH,
    MB_ARTIST_SEARCH_PATH,
    MB_DEFAULT_CACHE_TTL,
    MB_RATE_LIMIT_BACKOFF,
    MB_RATE_LIMIT_INTERVAL,
    MB_RECORDING_PATH,
    MB_RELEASE_PATH,
    MB_REQUEST_TIMEOUT,
)
from shared.musicbrainz.models import MBArtist, MBRecording, MBRecordingSearchResult, MBRelease

logger = logging.getLogger(__name__)


class MusicBrainzClient:
    """Async MusicBrainz client with 1 req/sec rate limit."""

    def __init__(
        self,
        cache: CacheBackend,
        contact_email: str = "",
        app_version: str = "0.6.0",
        cache_ttl: int = MB_DEFAULT_CACHE_TTL,
    ) -> None:
        self._cache = cache
        self._cache_ttl = cache_ttl
        self._semaphore = asyncio.Semaphore(1)
        self._last_request_time: float = 0
        user_agent = f"SpotifyMCPHistoryCollector/{app_version}"
        if contact_email:
            user_agent += f" (contact: {contact_email})"
        self._client = httpx.AsyncClient(
            base_url=MB_API_BASE,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            timeout=MB_REQUEST_TIMEOUT,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _rate_limited_get(
        self, path: str, params: dict[str, str] | None = None, *, max_retries: int = 3
    ) -> dict[str, Any] | None:
        """Make a rate-limited GET request with retry on 429/503/5xx."""
        for attempt in range(max_retries):
            async with self._semaphore:
                now = asyncio.get_running_loop().time()
                wait = max(0, MB_RATE_LIMIT_INTERVAL - (now - self._last_request_time))
                if wait > 0:
                    await asyncio.sleep(wait)

                try:
                    response = await self._client.get(path, params=params)
                    self._last_request_time = asyncio.get_running_loop().time()

                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt < max_retries - 1:
                            retry_after = response.headers.get("Retry-After")
                            if retry_after and retry_after.isdigit():
                                delay = float(retry_after)
                            else:
                                delay = MB_RATE_LIMIT_BACKOFF * (2**attempt)
                            logger.debug(
                                "MusicBrainz %d on %s, retrying in %.1fs (%d/%d)",
                                response.status_code,
                                path,
                                delay,
                                attempt + 1,
                                max_retries,
                            )
                            await asyncio.sleep(delay)
                            continue
                        logger.warning("MusicBrainz %d on %s, exhausted retries", response.status_code, path)
                        return None
                    if response.status_code != 200:
                        logger.debug("MusicBrainz %s returned %d", path, response.status_code)
                        return None

                    try:
                        parsed = response.json()
                    except ValueError:
                        logger.warning("MusicBrainz %s returned invalid JSON", path)
                        return None
                    if not isinstance(parsed, dict):
                        logger.warning("MusicBrainz %s returned non-object JSON", path)
                        return None
                    return parsed
                except httpx.HTTPError as e:
                    if attempt < max_retries - 1:
                        logger.debug("MusicBrainz request error: %s, retrying", e)
                        await asyncio.sleep(MB_RATE_LIMIT_BACKOFF)
                        continue
                    logger.debug("MusicBrainz request error: %s, exhausted retries", e)
                    return None
        return None

    @staticmethod
    def _escape_lucene(value: str) -> str:
        """Escape special Lucene query characters."""
        special = r'+-&|!(){}[]^"~*?:\/'
        return "".join(f"\\{c}" if c in special else c for c in value)

    async def lookup_recording_by_isrc(self, isrc: str) -> MBRecording | None:
        """Look up a recording by ISRC. Returns the best match or None."""
        cache_key = f"mb:recording:{isrc}"
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return MBRecording.model_validate(cached)

        data = await self._rate_limited_get(
            MB_RECORDING_PATH,
            params={
                "query": f"isrc:{isrc}",
                "fmt": "json",
                "limit": "1",
                "inc": "releases+genres+artist-credits",
            },
        )
        if not data:
            return None

        result = MBRecordingSearchResult.model_validate(data)
        if not result.recordings:
            return None

        recording = result.recordings[0]
        # Enrich releases with label info
        await self._enrich_release_labels(recording)
        await self._cache.set(cache_key, recording.model_dump(by_alias=True), self._cache_ttl)
        return recording

    async def search_recording(self, artist: str, title: str) -> MBRecording | None:
        """Search for a recording by artist + title. Returns best match or None."""
        cache_key = f"mb:search:{artist}|{title}"
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return MBRecording.model_validate(cached)

        query = f'artist:"{self._escape_lucene(artist)}" AND recording:"{self._escape_lucene(title)}"'
        data = await self._rate_limited_get(
            MB_RECORDING_PATH,
            params={
                "query": query,
                "fmt": "json",
                "limit": "3",
                "inc": "releases+genres+artist-credits",
            },
        )
        if not data:
            return None

        result = MBRecordingSearchResult.model_validate(data)
        if not result.recordings:
            return None

        # Return the first (highest-scoring) match
        recording = result.recordings[0]
        await self._enrich_release_labels(recording)
        await self._cache.set(cache_key, recording.model_dump(by_alias=True), self._cache_ttl)
        return recording

    async def get_artist(self, mbid: str) -> MBArtist | None:
        """Look up an artist by MBID."""
        cache_key = f"mb:artist:{mbid}"
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return MBArtist.model_validate(cached)

        data = await self._rate_limited_get(
            f"{MB_ARTIST_PATH}/{mbid}",
            params={"fmt": "json", "inc": "genres"},
        )
        if not data:
            return None

        # Extract area name
        area_name = ""
        if "area" in data and data["area"]:
            area_name = data["area"].get("name", "")

        begin_date = ""
        life_span = data.get("life-span", {})
        if life_span:
            begin_date = life_span.get("begin", "")

        artist = MBArtist(
            id=data.get("id", ""),
            name=data.get("name", ""),
            sort_name=data.get("sort-name", ""),
            disambiguation=data.get("disambiguation", ""),
            area=area_name,
            begin_date=begin_date,
            genres=list(data.get("genres", [])),
        )
        await self._cache.set(cache_key, artist.model_dump(by_alias=True), self._cache_ttl)
        return artist

    async def search_artist(self, name: str) -> MBArtist | None:
        """Search for an artist by name and return full details."""
        cache_key = f"mb:artist_search:{name}"
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return MBArtist.model_validate(cached)

        data = await self._rate_limited_get(
            MB_ARTIST_SEARCH_PATH,
            params={"query": f'artist:"{self._escape_lucene(name)}"', "fmt": "json", "limit": "1"},
        )
        if not data:
            return None

        artists = data.get("artists", [])
        if not artists:
            return None

        mbid = artists[0].get("id", "")
        if not mbid:
            return None

        # Fetch full artist details (with genres) using the MBID
        artist = await self.get_artist(mbid)
        if artist is not None:
            await self._cache.set(cache_key, artist.model_dump(by_alias=True), self._cache_ttl)
        return artist

    async def get_release(self, mbid: str) -> MBRelease | None:
        """Look up a release by MBID."""
        cache_key = f"mb:release:{mbid}"
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return MBRelease.model_validate(cached)

        data = await self._rate_limited_get(
            f"{MB_RELEASE_PATH}/{mbid}",
            params={"fmt": "json", "inc": "labels+genres"},
        )
        if not data:
            return None

        label = ""
        catalog_number = ""
        label_info = data.get("label-info", [])
        if label_info:
            first = label_info[0]
            label_obj = first.get("label", {})
            if label_obj:
                label = label_obj.get("name", "")
            catalog_number = first.get("catalog-number", "")

        release = MBRelease(
            id=data.get("id", ""),
            title=data.get("title", ""),
            date=data.get("date", ""),
            country=data.get("country", ""),
            status=data.get("status", ""),
            barcode=data.get("barcode", "") or "",
            label=label,
            catalog_number=catalog_number,
        )
        await self._cache.set(cache_key, release.model_dump(by_alias=True), self._cache_ttl)
        return release

    async def _enrich_release_labels(self, recording: MBRecording) -> None:
        """Fetch label info for the first release of a recording."""
        release = recording.first_release
        if not release or not release.mbid:
            return
        detailed = await self.get_release(release.mbid)
        if detailed:
            release.label = detailed.label
            release.catalog_number = detailed.catalog_number
