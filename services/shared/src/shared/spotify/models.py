"""Pydantic models for Spotify Web API responses.

These are pure data models matching Spotify's JSON structure.
No DB or auth dependencies.
"""

from datetime import datetime

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------


class SpotifyImage(BaseModel):
    """Image object returned by Spotify (album art, artist photos, etc.)."""

    url: str
    height: int | None = None
    width: int | None = None


# ---------------------------------------------------------------------------
# Artists
# ---------------------------------------------------------------------------


class SpotifyArtistSimplified(BaseModel):
    """Simplified artist object (embedded in tracks, albums)."""

    id: str | None = None
    name: str
    uri: str | None = None
    href: str | None = None
    external_urls: dict[str, str] = Field(default_factory=dict)


class SpotifyArtistFull(SpotifyArtistSimplified):
    """Full artist object (from /artists endpoint or top artists)."""

    genres: list[str] = Field(default_factory=list)
    popularity: int | None = None
    images: list[SpotifyImage] = Field(default_factory=list)
    followers: dict[str, object] | None = None


# ---------------------------------------------------------------------------
# Albums
# ---------------------------------------------------------------------------


class SpotifyAlbumSimplified(BaseModel):
    """Simplified album object (embedded in tracks)."""

    id: str | None = None
    name: str
    uri: str | None = None
    album_type: str | None = None
    release_date: str | None = None
    images: list[SpotifyImage] = Field(default_factory=list)
    external_urls: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Tracks
# ---------------------------------------------------------------------------


class SpotifyExternalIds(BaseModel):
    """External IDs (ISRC, EAN, UPC)."""

    isrc: str | None = None
    ean: str | None = None
    upc: str | None = None


class SpotifyTrack(BaseModel):
    """Full track object from Spotify."""

    id: str | None = None
    name: str
    uri: str | None = None
    duration_ms: int | None = None
    explicit: bool | None = None
    popularity: int | None = None
    track_number: int | None = None
    disc_number: int | None = None
    is_local: bool = False
    artists: list[SpotifyArtistSimplified] = Field(default_factory=list)
    album: SpotifyAlbumSimplified | None = None
    external_ids: SpotifyExternalIds | None = None
    external_urls: dict[str, str] = Field(default_factory=dict)
    href: str | None = None


# ---------------------------------------------------------------------------
# Play History
# ---------------------------------------------------------------------------


class SpotifyContext(BaseModel):
    """Playback context (playlist, album, artist, etc.)."""

    type: str | None = None
    uri: str | None = None
    href: str | None = None
    external_urls: dict[str, str] = Field(default_factory=dict)


class SpotifyPlayHistoryItem(BaseModel):
    """Single item from /me/player/recently-played."""

    track: SpotifyTrack
    played_at: datetime
    context: SpotifyContext | None = None


class SpotifyCursors(BaseModel):
    """Cursors for cursor-based paging."""

    after: str | None = None
    before: str | None = None


class RecentlyPlayedResponse(BaseModel):
    """Response from GET /me/player/recently-played."""

    items: list[SpotifyPlayHistoryItem] = Field(default_factory=list)
    next: str | None = None
    cursors: SpotifyCursors | None = None
    limit: int | None = None
    href: str | None = None


# ---------------------------------------------------------------------------
# Batch endpoints
# ---------------------------------------------------------------------------


class BatchTracksResponse(BaseModel):
    """Response from GET /tracks?ids=..."""

    tracks: list[SpotifyTrack | None] = Field(default_factory=list)


class BatchArtistsResponse(BaseModel):
    """Response from GET /artists?ids=..."""

    artists: list[SpotifyArtistFull | None] = Field(default_factory=list)


class SpotifyAudioFeatures(BaseModel):
    """Audio features for a single track."""

    id: str | None = None
    danceability: float | None = None
    energy: float | None = None
    key: int | None = None
    loudness: float | None = None
    mode: int | None = None
    speechiness: float | None = None
    acousticness: float | None = None
    instrumentalness: float | None = None
    liveness: float | None = None
    valence: float | None = None
    tempo: float | None = None
    time_signature: int | None = None
    duration_ms: int | None = None
    uri: str | None = None


class BatchAudioFeaturesResponse(BaseModel):
    """Response from GET /audio-features?ids=..."""

    audio_features: list[SpotifyAudioFeatures | None] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Top items
# ---------------------------------------------------------------------------


class TopArtistsResponse(BaseModel):
    """Response from GET /me/top/artists."""

    items: list[SpotifyArtistFull] = Field(default_factory=list)
    total: int | None = None
    limit: int | None = None
    offset: int | None = None
    next: str | None = None
    previous: str | None = None
    href: str | None = None


class TopTracksResponse(BaseModel):
    """Response from GET /me/top/tracks."""

    items: list[SpotifyTrack] = Field(default_factory=list)
    total: int | None = None
    limit: int | None = None
    offset: int | None = None
    next: str | None = None
    previous: str | None = None
    href: str | None = None


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class SpotifySearchTracks(BaseModel):
    """Tracks section of search results."""

    items: list[SpotifyTrack] = Field(default_factory=list)
    total: int | None = None
    limit: int | None = None
    offset: int | None = None


class SpotifySearchArtists(BaseModel):
    """Artists section of search results."""

    items: list[SpotifyArtistFull] = Field(default_factory=list)
    total: int | None = None
    limit: int | None = None
    offset: int | None = None


class SpotifySearchAlbums(BaseModel):
    """Albums section of search results."""

    items: list[SpotifyAlbumSimplified] = Field(default_factory=list)
    total: int | None = None
    limit: int | None = None
    offset: int | None = None


class SpotifySearchResponse(BaseModel):
    """Response from GET /search."""

    tracks: SpotifySearchTracks | None = None
    artists: SpotifySearchArtists | None = None
    albums: SpotifySearchAlbums | None = None
