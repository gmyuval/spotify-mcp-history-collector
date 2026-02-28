"""Response schemas for user-facing explorer API endpoints."""

from datetime import datetime

from pydantic import BaseModel


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


class PlaylistTrackItem(BaseModel):
    position: int
    spotify_track_id: str | None
    track_name: str
    artists_json: str | None
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
