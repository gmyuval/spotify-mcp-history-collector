# Phase 4b — External Enrichment + Valkey

**Branch:** `feat/phase-4b-enrichment`
**Version:** 0.5.0 → 0.6.0
**PRD reference:** `docs/prd-dev-step2.md` § Phase 4b
**Closes:** #46 (audio features enrichment job)

---

## Overview

Add persistent caching infrastructure (Valkey), external metadata sources (MusicBrainz, Soundcharts), audio features enrichment via a chained provider (Spotify → Soundcharts), and update detail pages with the new data. Replace the Phase 4a in-memory `EnrichmentCache` with a `CacheBackend` abstraction.

**Why Valkey?** MusicBrainz enforces 1 req/sec. Soundcharts is paid per call. Without persistent caching, every deploy/restart triggers a cold-cache burst that either risks throttling (MB) or costs money (Soundcharts). The in-memory cache from Phase 4a is lost on restart.

---

## Infrastructure: DigitalOcean Managed Valkey

**Provisioned:** 2026-03-19

| Property | Value |
|----------|-------|
| Cluster ID | `ac3494e7-01b8-473e-a6f3-c83d0d012d09` |
| Name | `spotify-mcp-valkey` |
| Engine | Valkey 8.0 |
| Region | fra1 (Frankfurt) |
| Size | db-s-1vcpu-1gb (1 node) |
| Host | `spotify-mcp-valkey-do-user-840119-0.d.db.ondigitalocean.com` |
| Port | `25061` |
| Protocol | `rediss://` (TLS) |
| Firewall | Restricted to `spotify-mcp-prod` droplet (ID: 551762993) |

**Production URI:**

```text
rediss://default:<REDACTED>@spotify-mcp-valkey-do-user-840119-0.d.db.ondigitalocean.com:25061
```

**Local dev:** `valkey/valkey:7` service in `docker-compose.yml` at `valkey://valkey:6379` (no TLS).

---

## Data Sources

| Source | Provides | Status |
|--------|----------|--------|
| **Spotify `get_audio_features()`** | danceability, energy, valence, tempo, etc. | Method exists — deprecated endpoint, may 403 |
| **Soundcharts API** | Same audio features (0.0–1.0 scale) — paid alternative | New client needed, `SOUNDCHARTS_API_KEY` required |
| **MusicBrainz API** | Record label, release date, country, genre tags, MBIDs, external links | Free, 1 req/sec, ISRC lookup |
| **Existing DB** | Track/artist/play data, empty `audio_features` table | Ready |
| **Valkey** | Persistent TTL cache for all external API responses | Provisioned (see above) |

---

## Architecture

### CacheBackend Protocol

```python
class CacheBackend(Protocol):
    async def get(self, key: str) -> dict | None: ...
    async def set(self, key: str, value: dict, ttl_seconds: int) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def close(self) -> None: ...
```

Two implementations:
- **`ValkeyCacheBackend`** — uses `redis.asyncio.Redis` (Valkey is Redis-compatible). Used when `VALKEY_URL` is set.
- **`PostgresCacheBackend`** — uses existing `SpotifyEntityCache` table. Used as fallback when `VALKEY_URL` is not set, and in tests.

### Cache Key Scheme

| Key pattern | Source | TTL |
|-------------|--------|-----|
| `sp:track:{spotify_id}` | Spotify enrichment | 24 hours |
| `sp:artist:{spotify_id}` | Spotify enrichment | 24 hours |
| `sp:album:{spotify_id}` | Spotify enrichment | 24 hours |
| `mb:recording:{isrc}` | MusicBrainz | 7 days |
| `mb:artist:{mbid}` | MusicBrainz | 7 days |
| `mb:release:{mbid}` | MusicBrainz | 7 days |
| `sc:features:{spotify_id}` | Soundcharts | 30 days |

### Audio Features Provider Chain

```python
class AudioFeaturesProvider(Protocol):
    async def get_features(self, spotify_track_ids: list[str]) -> dict[str, AudioFeaturesData]: ...

class SpotifyAudioFeaturesProvider:
    """Wraps SpotifyClient.get_audio_features(). On 403 → marks self disabled."""

class SoundchartsAudioFeaturesProvider:
    """Wraps SoundchartsClient. Requires SOUNDCHARTS_API_KEY."""

class ChainedAudioFeaturesProvider:
    """Tries providers in order. Spotify first (free), Soundcharts fallback (paid)."""
```

### Dependency Flow

```text
docker-compose.yml
  └── valkey service (port 6379, local) / DO managed (port 25061, prod)

services/shared/src/shared/cache/
  ├── backend.py          # CacheBackend Protocol
  ├── valkey_backend.py   # ValkeyCacheBackend (redis.asyncio)
  └── postgres_backend.py # PostgresCacheBackend (SpotifyEntityCache table)

services/shared/src/shared/musicbrainz/
  ├── client.py           # MusicBrainzClient (async, rate-limited)
  └── models.py           # MBRecording, MBArtist, MBRelease

services/shared/src/shared/soundcharts/
  ├── client.py           # SoundchartsClient (async, API key auth)
  └── models.py           # SoundchartsAudioFeatures

services/shared/src/shared/audio/
  └── provider.py         # AudioFeaturesProvider Protocol + 3 implementations

services/api/src/app/dependencies.py
  └── cache_backend = create_cache_backend()  # reads VALKEY_URL

services/api/src/app/explorer/service.py
  └── _enrich_*() methods use CacheBackend instead of EnrichmentCache

services/collector/src/collector/
  └── enrichment.py       # AudioFeaturesEnrichmentService (ChainedProvider)
```

---

## New Environment Variables

### Production (add to deploy workflow / server env)

```dotenv
# Valkey — DigitalOcean managed (already provisioned)
VALKEY_URL=rediss://default:<REDACTED>@spotify-mcp-valkey-do-user-840119-0.d.db.ondigitalocean.com:25061

# Soundcharts — paid API for audio features
SOUNDCHARTS_API_KEY=          # Obtain from developers.soundcharts.com

# MusicBrainz — polite User-Agent contact email
MUSICBRAINZ_CONTACT_EMAIL=admin@music.praxiscode.dev

# Audio features enrichment (collector)
ENRICH_AUDIO_FEATURES_ENABLED=true
ENRICH_BATCH_SIZE=100
ENRICH_MAX_PER_CYCLE=500
```

### Local dev (docker-compose.yml)

```dotenv
VALKEY_URL=valkey://valkey:6379
SOUNDCHARTS_API_KEY=          # Optional — leave empty to skip Soundcharts
MUSICBRAINZ_CONTACT_EMAIL=dev@localhost
ENRICH_AUDIO_FEATURES_ENABLED=true
ENRICH_BATCH_SIZE=100
ENRICH_MAX_PER_CYCLE=500
```

### Behavior when env vars are absent

| Variable | If unset |
|----------|----------|
| `VALKEY_URL` | Falls back to `PostgresCacheBackend` |
| `SOUNDCHARTS_API_KEY` | Soundcharts provider skipped in chain |
| `MUSICBRAINZ_CONTACT_EMAIL` | MusicBrainz client uses generic User-Agent |
| `ENRICH_AUDIO_FEATURES_ENABLED` | Defaults to `true` |

No new migrations required — `SpotifyEntityCache` table already exists for the Postgres cache backend, and `audio_features` table is ready.

---

## File Checklist

### Cache layer (`services/shared/`)

- [ ] **NEW** `src/shared/cache/__init__.py` — Package init, export `CacheBackend`
- [ ] **NEW** `src/shared/cache/backend.py` — `CacheBackend` Protocol definition
- [ ] **NEW** `src/shared/cache/valkey_backend.py` — `ValkeyCacheBackend` using `redis.asyncio`
- [ ] **NEW** `src/shared/cache/postgres_backend.py` — `PostgresCacheBackend` using `SpotifyEntityCache` model
- [ ] `pyproject.toml` — Add `redis>=5.0` dependency (redis.asyncio works with Valkey)

### MusicBrainz client (`services/shared/`)

- [ ] **NEW** `src/shared/musicbrainz/__init__.py` — Package init
- [ ] **NEW** `src/shared/musicbrainz/client.py` — `MusicBrainzClient`: async httpx, 1 req/sec rate limiter, ISRC lookup, artist+title fallback search
- [ ] **NEW** `src/shared/musicbrainz/models.py` — Pydantic models: `MBRecording`, `MBArtist`, `MBRelease`, `MBReleaseGroup`

### Soundcharts client (`services/shared/`)

- [ ] **NEW** `src/shared/soundcharts/__init__.py` — Package init
- [ ] **NEW** `src/shared/soundcharts/client.py` — `SoundchartsClient`: async httpx, API key auth, audio features lookup by Spotify ID/ISRC
- [ ] **NEW** `src/shared/soundcharts/models.py` — `SoundchartsAudioFeatures` Pydantic model

### Audio features provider (`services/shared/`)

- [ ] **NEW** `src/shared/audio/__init__.py` — Package init
- [ ] **NEW** `src/shared/audio/provider.py` — `AudioFeaturesProvider` Protocol + `SpotifyAudioFeaturesProvider` + `SoundchartsAudioFeaturesProvider` + `ChainedAudioFeaturesProvider`

### API service (`services/api/`)

- [ ] `src/app/dependencies.py` — Add `cache_backend` singleton (reads `VALKEY_URL`)
- [ ] `src/app/explorer/service.py` — Replace `EnrichmentCache` usage with `CacheBackend`, add MusicBrainz enrichment to detail methods
- [ ] `src/app/explorer/schemas.py` — Add `MusicBrainzTrackEnrichment`, `MusicBrainzArtistEnrichment`, `MusicBrainzAlbumEnrichment` response schemas
- [ ] `src/app/main.py` — Initialize/close `cache_backend` and `MusicBrainzClient` in lifespan
- [ ] **DELETE** `src/app/explorer/enrichment_cache.py` — Replaced by `CacheBackend`

### Collector service (`services/collector/`)

- [ ] **NEW** `src/collector/enrichment.py` — `AudioFeaturesEnrichmentService`: uses `ChainedAudioFeaturesProvider`, batch fetch + upsert to `audio_features` table
- [ ] `src/collector/runloop.py` — Add Phase 4 (enrichment) after polling
- [ ] `src/collector/settings.py` — Add `ENRICH_*`, `VALKEY_URL`, `SOUNDCHARTS_API_KEY` settings

### Explorer frontend (`services/explorer/`)

- [ ] `src/explorer/templates/track_detail.html` — Add MusicBrainz section: label, release date, country, external links
- [ ] `src/explorer/templates/artist_detail.html` — Add MusicBrainz section: area, disambiguation, external links
- [ ] `src/explorer/templates/album_detail.html` — Add MusicBrainz section: label, catalog number, country

### Docker

- [ ] `docker-compose.yml` — Add `valkey` service (`valkey/valkey:7`, port 6379, health check, `valkey_data` volume)
- [ ] `docker-compose.yml` — Add `VALKEY_URL`, `MUSICBRAINZ_CONTACT_EMAIL`, `ENRICH_*` env vars to `api` and `collector` services

### Dependency compilation

- [ ] `services/shared/requirements.txt` — Regenerate via `pip-compile`
- [ ] `services/api/requirements.txt` — Regenerate
- [ ] `services/collector/requirements.txt` — Regenerate

### Tests

- [ ] **NEW** `services/shared/tests/test_cache/test_valkey_backend.py` — Unit tests with mocked redis client
- [ ] **NEW** `services/shared/tests/test_cache/test_postgres_backend.py` — Unit tests with SQLite
- [ ] **NEW** `services/shared/tests/test_musicbrainz/test_client.py` — Unit tests with `respx` mock
- [ ] **NEW** `services/shared/tests/test_soundcharts/test_client.py` — Unit tests with `respx` mock
- [ ] **NEW** `services/shared/tests/test_audio/test_provider.py` — Unit tests for all 3 provider implementations
- [ ] **NEW** `services/collector/tests/test_enrichment.py` — Enrichment service tests
- [ ] `services/api/tests/test_explorer/test_detail_endpoints.py` — Update to cover MusicBrainz data in responses

### Deploy

- [ ] `.github/workflows/deploy.yml` — Add `VALKEY_URL`, `SOUNDCHARTS_API_KEY`, `MUSICBRAINZ_CONTACT_EMAIL`, `ENRICH_*` to env
- [ ] Verify Valkey firewall allows `spotify-mcp-prod` droplet

### Version bump

- [ ] `services/shared/src/shared/version.py` — `0.5.0` → `0.6.0`

---

## API Contract Changes

### Track Detail — Added `musicbrainz` field

```json
{
  "track_id": 42,
  "name": "Master of Puppets",
  "...existing fields...": "...",
  "musicbrainz": {
    "mbid": "abc123-...",
    "label": "Blackened Recordings",
    "release_date": "1986-03-03",
    "country": "US",
    "genres": ["thrash metal", "heavy metal"],
    "external_urls": {
      "musicbrainz": "https://musicbrainz.org/recording/abc123-..."
    }
  }
}
```

### Artist Detail — Added `musicbrainz` field

```json
{
  "artist_id": 7,
  "name": "Metallica",
  "...existing fields...": "...",
  "musicbrainz": {
    "mbid": "def456-...",
    "area": "Los Angeles, US",
    "disambiguation": "",
    "begin_date": "1981",
    "genres": ["thrash metal", "heavy metal", "hard rock"],
    "external_urls": {
      "musicbrainz": "https://musicbrainz.org/artist/def456-..."
    }
  }
}
```

### Album Detail — Added `musicbrainz` field

```json
{
  "album_spotify_id": "2Lq2qX3hYhiuPckC8Flj21",
  "...existing fields...": "...",
  "musicbrainz": {
    "mbid": "ghi789-...",
    "label": "Blackened Recordings",
    "catalog_number": "BLCKND003",
    "country": "US",
    "barcode": "0602527908311",
    "external_urls": {
      "musicbrainz": "https://musicbrainz.org/release/ghi789-..."
    }
  }
}
```

All `musicbrainz` fields are **nullable** — pages render without them if MusicBrainz lookup fails or ISRC is unavailable.

---

## MusicBrainz Client Design

### Rate Limiting

- `asyncio.Semaphore(1)` + `asyncio.sleep(1.0)` between requests (strict 1 req/sec)
- User-Agent: `SpotifyMCPHistoryCollector/0.6.0 (contact: {MUSICBRAINZ_CONTACT_EMAIL})` — required by MB API TOS

### Lookup Strategy

1. **ISRC lookup** (preferred): `GET /ws/2/recording?query=isrc:{isrc}&fmt=json` — exact match
2. **Artist+title fallback**: `GET /ws/2/recording?query=artist:{name} AND recording:{title}&fmt=json&limit=3` — fuzzy, pick best match
3. Cache all responses for 7 days via `CacheBackend`

### Response Includes (via `inc` parameter)

- `artist-credits` — artist names and MBIDs
- `releases` — linked releases (albums)
- `release-groups` — release group type (album/single/EP)
- `genres` — MusicBrainz genre tags

---

## Soundcharts Client Design

### Authentication

- API key passed via `x-app-id` and `x-api-key` headers
- Base URL: `https://customer.api.soundcharts.com/api/v2`

### Audio Features Endpoint

- `GET /song/by-platform/spotify/{spotify_track_id}` — get Soundcharts song ID
- `GET /song/{song_uuid}/audio-features` — get audio features
- Returns: danceability, energy, valence, tempo, acousticness, speechiness, instrumentalness, liveness, loudness, key, mode, time_signature (same 0.0–1.0 scale as Spotify)

### Error Handling

- 401/403: Invalid or expired API key → disable provider, log error
- 404: Track not found in Soundcharts → skip, return None
- 429: Rate limited → respect `Retry-After`, exponential backoff
- All responses cached for 30 days via `CacheBackend` (paid per call)

---

## Audio Features Enrichment Job

### Collector Integration

Added as **Phase 4** in the run loop (lowest priority):

```text
Phase 1: ZIP imports
Phase 2: Initial sync (if needed)
Phase 3: Incremental polling
Phase 4: Audio features enrichment  <-- NEW
```

### Logic

1. Query tracks with `spotify_track_id IS NOT NULL` and no `audio_features` row
2. Batch into groups of `ENRICH_BATCH_SIZE` (default 100, Spotify API max)
3. Call `ChainedAudioFeaturesProvider.get_features(track_ids)`:
   - Try `SpotifyAudioFeaturesProvider` first (free, uses any active user's token)
   - On 403 (deprecated endpoint) → fall through to `SoundchartsAudioFeaturesProvider`
   - On no `SOUNDCHARTS_API_KEY` → skip, log warning
4. Upsert results into `audio_features` table
5. Stop after `ENRICH_MAX_PER_CYCLE` tracks (default 500) to avoid hogging the cycle
6. Record job in `job_runs` table with `job_type=enrich`

### Error Handling

- **403 from Spotify** (deprecated endpoint): Mark Spotify provider as disabled for this cycle, fall through to Soundcharts
- **401/403 from Soundcharts**: Invalid API key → disable provider, log error
- **429 (rate limit)**: Respect `Retry-After` header via backoff
- **Partial failures**: Individual tracks that fail don't block the batch — skip and continue
- **No active users with tokens AND no Soundcharts key**: Skip enrichment cycle entirely

---

## Implementation Order

1. `CacheBackend` protocol + `PostgresCacheBackend` + `ValkeyCacheBackend`
2. Add `redis>=5.0` to shared deps, `make compile-deps`
3. `MusicBrainzClient` + models
4. `SoundchartsClient` + models
5. `AudioFeaturesProvider` protocol + Spotify + Soundcharts + Chained implementations
6. Add `valkey` service to `docker-compose.yml`
7. Wire `cache_backend` into API `dependencies.py` + `main.py` lifespan
8. Refactor `ExplorerService` enrichment methods to use `CacheBackend`
9. Add MusicBrainz enrichment to detail service methods + schemas
10. `AudioFeaturesEnrichmentService` in collector
11. Update collector run loop + settings
12. Update detail page templates with MusicBrainz sections
13. Tests (cache backends, MusicBrainz client, Soundcharts client, providers, enrichment service, updated detail endpoints)
14. Version bump to 0.6.0
15. Set Valkey firewall rules (restrict to `spotify-mcp-prod` droplet)
16. Update deploy workflow with new env vars
17. Docker test (`docker-compose up --build`), verify:
    - Valkey service starts and is reachable
    - Detail pages render with/without MusicBrainz data
    - Audio features enrichment runs (Spotify → Soundcharts chain)
    - Cache falls back to PostgreSQL when `VALKEY_URL` unset
18. `docker-compose down`
19. Present changes for approval

---

## Template Updates

### Track Detail — MusicBrainz Section

Below the existing Spotify enrichment section, add a "Recording Info" card (only rendered when `track.musicbrainz` is not None):

- **Label:** Record label name
- **Release Date:** Original release date
- **Country:** Release country
- **Genres:** MusicBrainz genre tags as badges (supplements Spotify genres)
- **MusicBrainz link:** External URL to MB recording page

### Artist Detail — MusicBrainz Section

Below genre badges, add an "Artist Info" card:

- **Origin:** Area/country
- **Active since:** Begin date
- **MusicBrainz genres:** Genre tags (often more specific than Spotify)
- **MusicBrainz link:** External URL

### Album Detail — MusicBrainz Section

Below Spotify enrichment, add a "Release Info" card:

- **Label:** Record label
- **Catalog #:** Catalog number
- **Country:** Release country
- **Barcode:** If available
- **MusicBrainz link:** External URL

---

## Out of Scope (mapped to future phases)

| Item | Planned Phase | Issue |
|------|---------------|-------|
| MusicBrainz batch pre-enrichment in collector | Phase 5 or later | — |
| Local track resolution (`local:<sha1>` → Spotify IDs) | Phase 8 | #47 |
| Analytics page | Phase 5 | #48 |
| MCP OAuth for claude.ai Integrations | Phase 7d | — |
