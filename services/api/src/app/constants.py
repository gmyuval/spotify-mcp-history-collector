"""Centralized constants for the API service."""

import enum
from dataclasses import dataclass

from shared.spotify.constants import SPOTIFY_TOKEN_URL as SPOTIFY_TOKEN_URL  # re-export

# --- Service identity ---


class ServiceName(enum.StrEnum):
    """Service names used for logging and identification."""

    API = "api"
    COLLECTOR = "collector"
    FRONTEND = "frontend"
    EXPLORER = "explorer"


# --- Application metadata ---

APP_TITLE = "Spotify MCP API"
APP_DESCRIPTION = "Spotify OAuth, MCP tool endpoints, and admin APIs"
APP_VERSION = "0.1.0"


# --- Route configuration ---


@dataclass(frozen=True, slots=True)
class _Route:
    """A route prefix paired with its OpenAPI tag."""

    prefix: str
    tag: str


class Routes:
    """API route prefixes and tags — single source of truth."""

    AUTH = _Route("/auth", "auth")
    ADMIN = _Route("/admin", "admin")
    HISTORY = _Route("/history", "history")
    MCP = _Route("/mcp", "mcp")
    EXPLORER = _Route("/api/me", "explorer")
    HEALTH = "/healthz"


# --- Spotify OAuth ---

SPOTIFY_AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_ME_URL = "https://api.spotify.com/v1/me"

SPOTIFY_SCOPES = (
    "user-read-recently-played user-top-read user-read-email user-read-private "
    "playlist-read-private playlist-modify-public playlist-modify-private"
)

# Default configuration values
DEFAULT_SPOTIFY_REDIRECT_URI = "http://localhost:8000/auth/callback"
DEFAULT_OAUTH_STATE_TTL_SECONDS = 300  # 5 minutes
DEFAULT_TOKEN_EXPIRY_BUFFER_SECONDS = 60  # Refresh tokens this many seconds before expiry
