"""Spotify API client and models."""

from shared.spotify.client import SpotifyClient
from shared.spotify.exceptions import (
    SpotifyAuthError,
    SpotifyClientError,
    SpotifyRateLimitError,
    SpotifyRequestError,
    SpotifyServerError,
)

__all__ = [
    "SpotifyClient",
    "SpotifyAuthError",
    "SpotifyClientError",
    "SpotifyRateLimitError",
    "SpotifyRequestError",
    "SpotifyServerError",
]
