"""Centralized constants for the API service."""

from shared.spotify.constants import SPOTIFY_TOKEN_URL as SPOTIFY_TOKEN_URL  # re-export

# Spotify OAuth URLs
SPOTIFY_AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_ME_URL = "https://api.spotify.com/v1/me"

# Spotify OAuth scopes required by this application
SPOTIFY_SCOPES = (
    "user-read-recently-played user-top-read user-read-email user-read-private "
    "playlist-read-private playlist-modify-public playlist-modify-private"
)

# Default configuration values
DEFAULT_SPOTIFY_REDIRECT_URI = "http://localhost:8000/auth/callback"
DEFAULT_OAUTH_STATE_TTL_SECONDS = 300  # 5 minutes
DEFAULT_TOKEN_EXPIRY_BUFFER_SECONDS = 60  # Refresh tokens this many seconds before expiry
