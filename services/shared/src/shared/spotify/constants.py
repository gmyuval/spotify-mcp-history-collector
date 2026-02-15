"""Spotify API URLs and retry defaults."""

# Spotify Auth
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"

# Spotify Web API base
SPOTIFY_API_BASE = "https://api.spotify.com/v1"

# Spotify Web API endpoints
RECENTLY_PLAYED_URL = f"{SPOTIFY_API_BASE}/me/player/recently-played"
ME_URL = f"{SPOTIFY_API_BASE}/me"
TRACKS_URL = f"{SPOTIFY_API_BASE}/tracks"
ARTISTS_URL = f"{SPOTIFY_API_BASE}/artists"
AUDIO_FEATURES_URL = f"{SPOTIFY_API_BASE}/audio-features"
TOP_ARTISTS_URL = f"{SPOTIFY_API_BASE}/me/top/artists"
TOP_TRACKS_URL = f"{SPOTIFY_API_BASE}/me/top/tracks"
SEARCH_URL = f"{SPOTIFY_API_BASE}/search"
ALBUMS_URL = f"{SPOTIFY_API_BASE}/albums"
USER_PLAYLISTS_URL = f"{SPOTIFY_API_BASE}/me/playlists"
PLAYLIST_URL = f"{SPOTIFY_API_BASE}/playlists"

# Retry defaults
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BASE_DELAY = 1.0  # seconds
DEFAULT_CONCURRENCY_LIMIT = 5
DEFAULT_REQUEST_TIMEOUT = 30.0  # seconds
