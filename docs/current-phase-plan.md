# Phase 4a — Entity Detail Pages + Spotify Enrichment

**Branch:** `feat/phase-4a-detail-pages`
**Version:** 0.4.0 → 0.5.0
**PRD reference:** `docs/prd-dev-step2.md` § Phase 4a

---

## Overview

Replace the "Under Construction" placeholder pages for track, artist, and album detail with fully functional pages. Uses DB data + optional live Spotify API enrichment. No new external services or infrastructure.

---

## Data Sources

| Source | Provides | Already available? |
|--------|----------|--------------------|
| **DB (tracks/artists/plays)** | Name, duration, album, play count, first/last played, listening time | Yes |
| **DB (audio_features)** | Danceability, energy, valence, tempo, etc. | Table exists, unpopulated — show gracefully |
| **Spotify API (live)** | Images, popularity, preview URLs, followers, genres, album art | Yes — `SpotifyClient.get_track()`, `get_artist()`, `get_album()` |

Spotify enrichment is **optional** — pages render with DB data alone if the user has no Spotify token or API returns errors.

---

## File Checklist

### API layer (`services/api/`)

- [ ] `src/app/explorer/schemas.py` — Add `TrackDetail`, `ArtistDetail`, `AlbumDetail`, `RecentPlayItem` response schemas
- [ ] `src/app/explorer/service.py` — Add `get_track_detail()`, `get_artist_detail()`, `get_album_detail()` + Spotify enrichment helpers
- [ ] `src/app/explorer/router.py` — Add `GET /tracks/{track_id}`, `GET /artists/{artist_id}`, `GET /albums/{album_spotify_id}`
- [ ] **NEW** `src/app/explorer/enrichment_cache.py` — Simple in-memory TTL cache for Spotify API responses (24h TTL, max 500 entries)

### Explorer frontend (`services/explorer/`)

- [ ] `src/explorer/api_client.py` — Add `get_track_detail()`, `get_artist_detail()`, `get_album_detail()` methods
- [ ] `src/explorer/routes/tracks.py` — Replace `coming_soon.html` with actual data fetch + `track_detail.html`
- [ ] `src/explorer/routes/artists.py` — Replace `coming_soon.html` with actual data fetch + `artist_detail.html`
- [ ] **NEW** `src/explorer/routes/albums.py` — Album detail route at `/albums/{album_spotify_id}`
- [ ] `src/explorer/routes/__init__.py` — Export `albums_router`
- [ ] `src/explorer/main.py` — Register albums router
- [ ] **NEW** `src/explorer/templates/track_detail.html` — Header card, stats, audio features radar (ECharts), recent plays
- [ ] **NEW** `src/explorer/templates/artist_detail.html` — Header card with image, genre badges, stats, top tracks
- [ ] **NEW** `src/explorer/templates/album_detail.html` — Header card with cover art, stats, track listing
- [ ] `src/explorer/templates/base.html` — Add ECharts CDN script

### Tests

- [ ] **NEW** `services/api/tests/test_explorer/test_detail_endpoints.py` — Track/artist/album detail: found, not found, user isolation, audio features
- [ ] **NEW** `services/explorer/tests/test_detail_routes.py` — Route rendering, 404 handling, enrichment optional

### Version bump

- [ ] `services/shared/src/shared/version.py` — `0.4.0` → `0.5.0`

---

## Page Designs

### Track Detail (`/tracks/{track_id}`)

- **Header card:** Track name, artist(s) (linked to `/artists/{id}`), album name (linked to `/albums/{album_id}`), duration, Spotify external link
- **Spotify enrichment (if available):** Album cover art, popularity bar, ISRC, preview player
- **Personal Stats card:** Total plays, first/last played, total listening time
- **Audio Features card (if data exists):** Radar chart (ECharts) — danceability, energy, valence, acousticness, instrumentalness, speechiness
- **Recent Plays table:** Paginated play history for this track

### Artist Detail (`/artists/{artist_id}`)

- **Header card:** Artist name, Spotify external link
- **Spotify enrichment (if available):** Artist image, genres (as badges), popularity, followers count
- **Personal Stats card:** Total plays, unique tracks, total listening time, first/last played
- **Top Tracks table:** Most-played tracks by this artist (linked to `/tracks/{id}`)

### Album Detail (`/albums/{album_spotify_id}`)

- **Header card:** Album name, artist(s), Spotify external link
- **Spotify enrichment (if available):** Album cover art, release date, label, total tracks
- **Personal Stats card:** Total plays across all album tracks, unique tracks played
- **Track Listing table:** All user-played tracks from this album with play counts (linked to `/tracks/{id}`)

Album detail uses `album_spotify_id` as the path parameter (no separate album DB table exists).

---

## API Contracts

### `GET /api/me/tracks/{track_id}` — Track Detail

Response:

```json
{
  "track_id": 42,
  "name": "Master of Puppets",
  "spotify_track_id": "6NwbeybX6TDtXlpXvnUOZC",
  "duration_ms": 515387,
  "album_name": "Master of Puppets",
  "album_spotify_id": "2Lq2qX3hYhiuPckC8Flj21",
  "artists": [{"artist_id": 7, "name": "Metallica"}],
  "play_count": 23,
  "first_played": "2025-06-15T14:30:00Z",
  "last_played": "2026-03-10T22:15:00Z",
  "total_ms_played": 11853801,
  "audio_features": {
    "danceability": 0.28,
    "energy": 0.87,
    "valence": 0.12,
    "acousticness": 0.003,
    "instrumentalness": 0.55,
    "speechiness": 0.05
  },
  "recent_plays": [
    {"played_at": "2026-03-10T22:15:00Z", "ms_played": 515387, "context_type": "playlist"}
  ],
  "spotify": {
    "images": [{"url": "https://i.scdn.co/image/...", "height": 640, "width": 640}],
    "popularity": 78,
    "isrc": "USBL10500280",
    "preview_url": "https://p.scdn.co/mp3-preview/...",
    "external_url": "https://open.spotify.com/track/6NwbeybX6TDtXlpXvnUOZC"
  }
}
```

### `GET /api/me/artists/{artist_id}` — Artist Detail

Response:

```json
{
  "artist_id": 7,
  "name": "Metallica",
  "spotify_artist_id": "2ye2Wgw4gimLv2eAKyk1NB",
  "play_count": 342,
  "unique_tracks": 45,
  "total_ms_played": 95832000,
  "first_played": "2025-01-20T10:00:00Z",
  "last_played": "2026-03-15T18:30:00Z",
  "top_tracks": [
    {"track_id": 42, "name": "Master of Puppets", "play_count": 23}
  ],
  "spotify": {
    "images": [{"url": "https://i.scdn.co/image/...", "height": 640, "width": 640}],
    "genres": ["thrash metal", "metal", "hard rock"],
    "popularity": 82,
    "followers": 24500000,
    "external_url": "https://open.spotify.com/artist/2ye2Wgw4gimLv2eAKyk1NB"
  }
}
```

### `GET /api/me/albums/{album_spotify_id}` — Album Detail

Response:

```json
{
  "album_spotify_id": "2Lq2qX3hYhiuPckC8Flj21",
  "name": "Master of Puppets",
  "artist_names": ["Metallica"],
  "play_count": 87,
  "unique_tracks": 8,
  "tracks": [
    {"track_id": 42, "name": "Master of Puppets", "play_count": 23, "duration_ms": 515387}
  ],
  "spotify": {
    "images": [{"url": "https://i.scdn.co/image/...", "height": 640, "width": 640}],
    "release_date": "1986-03-03",
    "label": "Blackened Recordings",
    "total_tracks": 8,
    "external_url": "https://open.spotify.com/album/2Lq2qX3hYhiuPckC8Flj21"
  }
}
```

---

## ECharts Integration

- Apache ECharts via CDN (`<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js">`)
- Audio features radar chart on track detail page
- Dark theme matching Bootstrap dark
- No build step required
- Prepared for reuse in Phase 5 (Analytics)

---

## In-Memory Enrichment Cache

Simple module-level TTL dict for Spotify API responses. Avoids repeated API calls for the same entity within a session.

- 24-hour default TTL
- Max 500 entries, oldest-first eviction when full
- Keys: `track:{spotify_id}`, `artist:{spotify_id}`, `album:{spotify_id}`
- Replaced by Valkey `CacheBackend` in Phase 4b

---

## Implementation Order

1. Response schemas (`schemas.py`)
2. Enrichment cache module
3. Service layer queries (`service.py` — DB queries + Spotify enrichment)
4. API endpoints (`router.py`)
5. Explorer API client methods
6. Explorer routes (replace placeholders + new album route)
7. Templates (track, artist, album detail + ECharts)
8. Tests
9. Version bump to 0.5.0
10. Docker test (`docker-compose up --build`), verify detail pages render
11. `docker-compose down`
12. Present changes for approval

---

## Out of Scope

- MusicBrainz enrichment (Phase 4b)
- Soundcharts / audio features population (Phase 4b)
- Valkey infrastructure (Phase 4b)
- Analytics page (Phase 5)
- HTMX pagination on recent plays (keep simple for now, full page)
