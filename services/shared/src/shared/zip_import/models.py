"""Normalized data models for ZIP import records."""

import hashlib
from datetime import datetime

from pydantic import BaseModel


class NormalizedPlayRecord(BaseModel):
    """A single play record normalized from any Spotify export format.

    This is the format-agnostic intermediate representation that
    both Extended Streaming History and Account Data formats map to.
    """

    track_name: str
    artist_name: str
    album_name: str | None = None
    ms_played: int
    played_at: datetime  # Naive UTC after normalization
    spotify_track_uri: str | None = None

    @property
    def spotify_track_id(self) -> str | None:
        """Extract track ID from URI, e.g. 'spotify:track:ABC123' -> 'ABC123'."""
        if self.spotify_track_uri and self.spotify_track_uri.startswith("spotify:track:"):
            return self.spotify_track_uri.removeprefix("spotify:track:")
        return None

    @property
    def local_track_id(self) -> str:
        """Generate deterministic local ID: local:<sha1(artist|track|album)>."""
        components = f"{self.artist_name}|{self.track_name}|{self.album_name or ''}"
        digest = hashlib.sha1(components.encode("utf-8")).hexdigest()
        return f"local:{digest}"

    @property
    def local_artist_id(self) -> str:
        """Generate deterministic local artist ID: local:<sha1(artist_name)>."""
        digest = hashlib.sha1(self.artist_name.encode("utf-8")).hexdigest()
        return f"local:{digest}"
