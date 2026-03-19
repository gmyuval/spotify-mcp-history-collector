"""Soundcharts API URLs and defaults."""

# Soundcharts Customer API v2
SC_API_BASE = "https://customer.api.soundcharts.com/api/v2"

# Endpoints (relative to base)
SC_SONG_BY_PLATFORM_PATH = "/song/by-platform/spotify"  # + /{spotify_track_id}
SC_SONG_AUDIO_FEATURES_PATH = "/song/{song_uuid}/spotify/audio-features"

# Auth headers
SC_APP_ID_HEADER = "x-app-id"
SC_API_KEY_HEADER = "x-api-key"

# Cache
SC_DEFAULT_CACHE_TTL = 30 * 86400  # 30 days (paid per call — cache aggressively)

# Request
SC_REQUEST_TIMEOUT = 15.0  # seconds
