"""Response schemas for user-facing explorer API endpoints."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ArtistSummary(BaseModel):
    artist_id: int
    artist_name: str
    play_count: int


class TrackSummary(BaseModel):
    track_id: int
    track_name: str
    artist_name: str
    play_count: int


class DashboardData(BaseModel):
    total_plays: int
    listening_hours: float
    unique_tracks: int
    unique_artists: int
    top_artists: list[ArtistSummary]
    top_tracks: list[TrackSummary]


class PlayHistoryItem(BaseModel):
    played_at: datetime
    track_id: int
    track_name: str
    artist_name: str
    ms_played: int | None


class PaginatedHistory(BaseModel):
    items: list[PlayHistoryItem]
    total: int
    limit: int
    offset: int


class PlaylistSummary(BaseModel):
    id: int
    spotify_playlist_id: str
    name: str
    description: str | None
    total_tracks: int
    owner_display_name: str | None
    external_url: str | None


class PlaylistTrackArtist(BaseModel):
    id: str | None = None
    name: str


class PlaylistTrackItem(BaseModel):
    position: int
    spotify_track_id: str | None
    track_name: str
    artists_json: list[PlaylistTrackArtist]
    added_at: str | None


class PlaylistDetail(BaseModel):
    id: int
    spotify_playlist_id: str
    name: str
    description: str | None
    total_tracks: int
    owner_display_name: str | None
    external_url: str | None
    tracks: list[PlaylistTrackItem]


class UserProfile(BaseModel):
    user_id: int
    spotify_user_id: str
    display_name: str | None
    email: str | None
    country: str | None
    product: str | None
    created_at: datetime
    has_spotify_token: bool
    total_plays: int
    unique_tracks: int
    unique_artists: int
    listening_hours: float


# ── Taste profile schemas ──────────────────────────────────────────


class TasteProfileResponse(BaseModel):
    user_id: int
    profile: dict[str, Any]
    version: int
    updated_at: str | None


class PreferenceEventItem(BaseModel):
    event_id: str
    timestamp: str
    source: str
    type: str
    payload: dict[str, Any]


class TasteProfileWithEvents(BaseModel):
    profile: TasteProfileResponse
    recent_events: list[PreferenceEventItem]


class PaginatedPreferenceEvents(BaseModel):
    items: list[PreferenceEventItem]
    total: int
    limit: int
    offset: int


class TasteProfilePatch(BaseModel):
    patch: dict[str, Any]
    reason: str | None = None


# ── Memory playlist schemas ──────────────────────────────────────


class MemoryPlaylistSummary(BaseModel):
    playlist_id: str
    name: str
    description: str | None
    created_at: str
    updated_at: str
    intent_tags: list[str]
    track_count: int


class PaginatedMemoryPlaylists(BaseModel):
    items: list[MemoryPlaylistSummary]
    total: int
    limit: int
    offset: int


class MemoryPlaylistEventItem(BaseModel):
    event_id: str
    timestamp: str
    type: str
    payload: dict[str, Any]


class MemoryPlaylistTrack(BaseModel):
    spotify_track_id: str
    track_name: str | None = None
    artists: list[PlaylistTrackArtist] = []


class MemoryPlaylistDetail(BaseModel):
    playlist_id: str
    name: str
    description: str | None
    created_at: str
    updated_at: str
    intent_tags: list[str]
    seed_context: dict[str, Any]
    tracks: list[MemoryPlaylistTrack]
    recent_events: list[MemoryPlaylistEventItem]
    total_events: int


class PaginatedMemoryPlaylistEvents(BaseModel):
    items: list[MemoryPlaylistEventItem]
    total: int
    limit: int
    offset: int


# ── Track/artist browser schemas ──────────────────────────────────


class TrackBrowserItem(BaseModel):
    track_id: int
    name: str
    artist_name: str
    play_count: int
    last_played: datetime | None


class PaginatedTracks(BaseModel):
    items: list[TrackBrowserItem]
    total: int
    limit: int
    offset: int


class ArtistBrowserItem(BaseModel):
    artist_id: int
    name: str
    play_count: int
    track_count: int


class PaginatedArtists(BaseModel):
    items: list[ArtistBrowserItem]
    total: int
    limit: int
    offset: int


# ── Entity detail schemas ──────────────────────────────────────


class TrackArtistRef(BaseModel):
    artist_id: int
    name: str


class AudioFeaturesData(BaseModel):
    danceability: float | None = None
    energy: float | None = None
    valence: float | None = None
    acousticness: float | None = None
    instrumentalness: float | None = None
    speechiness: float | None = None
    tempo: float | None = None
    loudness: float | None = None
    key: int | None = None
    mode: int | None = None
    time_signature: int | None = None
    liveness: float | None = None


class SpotifyImage(BaseModel):
    url: str
    height: int | None = None
    width: int | None = None


class SpotifyTrackEnrichment(BaseModel):
    images: list[SpotifyImage] = []
    popularity: int | None = None
    isrc: str | None = None
    preview_url: str | None = None
    external_url: str | None = None


class SpotifyArtistEnrichment(BaseModel):
    images: list[SpotifyImage] = []
    genres: list[str] = []
    popularity: int | None = None
    followers: int | None = None
    external_url: str | None = None


class SpotifyAlbumEnrichment(BaseModel):
    images: list[SpotifyImage] = []
    release_date: str | None = None
    label: str | None = None
    total_tracks: int | None = None
    external_url: str | None = None


class MusicBrainzExternalUrls(BaseModel):
    musicbrainz: str | None = None


class MusicBrainzTrackEnrichment(BaseModel):
    mbid: str | None = None
    label: str | None = None
    release_date: str | None = None
    country: str | None = None
    genres: list[str] = []
    external_urls: MusicBrainzExternalUrls | None = None


class MusicBrainzArtistEnrichment(BaseModel):
    mbid: str | None = None
    area: str | None = None
    disambiguation: str | None = None
    begin_date: str | None = None
    genres: list[str] = []
    external_urls: MusicBrainzExternalUrls | None = None


class MusicBrainzAlbumEnrichment(BaseModel):
    mbid: str | None = None
    label: str | None = None
    catalog_number: str | None = None
    country: str | None = None
    barcode: str | None = None
    external_urls: MusicBrainzExternalUrls | None = None


class RecentPlayItem(BaseModel):
    played_at: datetime
    ms_played: int | None = None
    context_type: str | None = None


class TrackDetailArtist(BaseModel):
    track_id: int
    name: str
    play_count: int


class TrackDetail(BaseModel):
    track_id: int
    name: str
    spotify_track_id: str | None = None
    duration_ms: int | None = None
    album_name: str | None = None
    album_spotify_id: str | None = None
    artists: list[TrackArtistRef] = []
    play_count: int = 0
    first_played: datetime | None = None
    last_played: datetime | None = None
    total_ms_played: int = 0
    audio_features: AudioFeaturesData | None = None
    recent_plays: list[RecentPlayItem] = []
    spotify: SpotifyTrackEnrichment | None = None
    musicbrainz: MusicBrainzTrackEnrichment | None = None


class ArtistDetail(BaseModel):
    artist_id: int
    name: str
    spotify_artist_id: str | None = None
    play_count: int = 0
    unique_tracks: int = 0
    total_ms_played: int = 0
    first_played: datetime | None = None
    last_played: datetime | None = None
    top_tracks: list[TrackDetailArtist] = []
    spotify: SpotifyArtistEnrichment | None = None
    musicbrainz: MusicBrainzArtistEnrichment | None = None


class AlbumTrackItem(BaseModel):
    track_id: int
    name: str
    play_count: int
    duration_ms: int | None = None


class AlbumDetail(BaseModel):
    album_spotify_id: str
    name: str
    artist_names: list[str] = []
    play_count: int = 0
    unique_tracks: int = 0
    tracks: list[AlbumTrackItem] = []
    spotify: SpotifyAlbumEnrichment | None = None
    musicbrainz: MusicBrainzAlbumEnrichment | None = None


# ── API token schemas ──────────────────────────────────────────


class CreateTokenRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255, pattern=r".*\S.*")


class CreatedTokenResponse(BaseModel):
    token_id: int
    name: str
    token: str
    prefix: str
    created_at: datetime


class TokenListItem(BaseModel):
    token_id: int
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None


class TokenListResponse(BaseModel):
    items: list[TokenListItem]
