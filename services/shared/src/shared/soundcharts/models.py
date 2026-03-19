"""Pydantic models for Soundcharts API responses."""

from pydantic import BaseModel


class SoundchartsAudioFeatures(BaseModel):
    """Audio features from Soundcharts (same 0.0-1.0 scale as Spotify)."""

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


class SoundchartsSongIdentifier(BaseModel):
    """Song identifier from Soundcharts platform lookup."""

    uuid: str
    name: str = ""
