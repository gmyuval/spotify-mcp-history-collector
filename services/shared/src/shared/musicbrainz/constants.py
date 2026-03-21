"""MusicBrainz API URLs and defaults."""

# MusicBrainz Web Service v2
MB_API_BASE = "https://musicbrainz.org/ws/2"

# Endpoints (relative to base)
MB_RECORDING_PATH = "/recording"
MB_ARTIST_PATH = "/artist"
MB_RELEASE_PATH = "/release"

# Rate limiting
MB_RATE_LIMIT_INTERVAL = 1.0  # seconds between requests (API TOS: max 1 req/sec)
MB_RATE_LIMIT_BACKOFF = 2.0  # seconds to wait after a 503

# Cache
MB_DEFAULT_CACHE_TTL = 7 * 86400  # 7 days

# Request
MB_REQUEST_TIMEOUT = 15.0  # seconds

# Artist search endpoint
MB_ARTIST_SEARCH_PATH = "/artist"
