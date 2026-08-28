"""Spotify API client and models."""

from shared.spotify.client import SpotifyClient
from shared.spotify.embed import SpotifyEmbedClient
from shared.spotify.exceptions import (
    SpotifyAuthError,
    SpotifyClientError,
    SpotifyEmbedError,
    SpotifyQuotaExceededError,
    SpotifyRateLimitError,
    SpotifyRequestError,
    SpotifyServerError,
)
from shared.spotify.models import EmbedTrackItem

__all__ = [
    "SpotifyClient",
    "SpotifyEmbedClient",
    "EmbedTrackItem",
    "SpotifyAuthError",
    "SpotifyClientError",
    "SpotifyEmbedError",
    "SpotifyQuotaExceededError",
    "SpotifyRateLimitError",
    "SpotifyRequestError",
    "SpotifyServerError",
]
