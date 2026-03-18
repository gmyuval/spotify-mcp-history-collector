# PRD — Development Step 2

**Created:** 2026-03-11
**Status:** Approved
**Baseline version:** 0.1.0 (current deployed state)

---

## Executive Summary

14 work items organized into 8 phases, progressing from versioning & bug fixes to major feature additions. Each phase is developed on a separate branch and merged via PR. Version is bumped at each phase merge.

### Versioning Strategy

The project follows [Semantic Versioning](https://semver.org/) (MAJOR.MINOR.PATCH):
- **MINOR** bump for all feature phases (0.x.0 series)
- **MAJOR** bump for breaking changes (Phase 7: auth model change → 1.0.0)

Single source of truth: `services/shared/src/shared/version.py` (`__version__ = "0.1.0"`)
All other locations read from it (pyproject.toml via `dynamic`, API constants, Docker labels, healthz endpoints).
Git tags (`v0.1.0`, `v0.2.0`, ...) created on each merge to main. GitHub Releases created automatically via CI.

### Workflow Per Phase

1. Create feature branch from main
2. Implement changes
3. Test with local Docker setup (`docker-compose up --build`)
4. Present changes for approval (file list + summary)
5. Bump version, commit, push, create PR
6. Deploy to production via GitHub Actions while PR is reviewed
7. Verify all services come up and check functionality
8. After PR merge: tag main with version, create GitHub Release

---

## Phase 1 — Versioning, Bug Fixes & Quick Wins

**Branch:** `fix/phase-1-bugfixes`
**Version:** 0.1.0 → 0.2.0

### 1.1 App Versioning Infrastructure

**Current state:** `APP_VERSION = "0.1.0"` hardcoded in `services/api/src/app/constants.py`. Each `pyproject.toml` has its own `version = "0.1.0"` independently. No git tags, no GitHub Releases, no single source of truth.

**Implementation:**

*In-code versioning:*
- Create `services/shared/src/shared/version.py` with `__version__ = "0.1.0"` as the single source of truth
- All services import version from shared: `from shared.version import __version__`
- `services/api/src/app/constants.py` — replace hardcoded `APP_VERSION` with import from shared
- Each service's `pyproject.toml` — use `dynamic = ["version"]` with `[tool.setuptools.dynamic] version = {attr = "shared.version.__version__"}` (shared), or pin to match (api/collector/frontend/explorer)
- All healthz endpoints include `"version": __version__` in response JSON
- Docker images labeled with version: `LABEL version=$APP_VERSION`
- Add version display to explorer footer and admin sidebar

*GitHub versioning (tags + releases):*
- Tag current main retroactively as `v0.1.0` (baseline)
- Each phase merge to main produces a new git tag (`v0.2.0`, `v0.3.0`, …)
- New GitHub Actions workflow `.github/workflows/release.yml`:
  - Trigger: push to `main` branch
  - Reads version from `services/shared/src/shared/version.py`
  - Checks whether a tag for this version already exists — skips if so
  - Creates annotated git tag `v{version}` on the merge commit
  - Creates a GitHub Release using `gh release create`:
    - Title: `v{version}`
    - Body: auto-generated from commit messages since last tag (`git log --oneline <prev>..HEAD`)
    - Creates a full GitHub Release for the tagged version
- This means: bumping `version.py` + merging the PR is the only manual step; tagging and release notes are fully automated

**Files:**
- New: `services/shared/src/shared/version.py` — single source of truth
- `services/api/src/app/constants.py` — import from shared
- `services/collector/src/collector/main.py` — log version on startup
- `services/frontend/src/frontend/main.py` — expose version
- `services/explorer/src/explorer/main.py` — expose version
- `services/explorer/src/explorer/templates/base.html` — version in footer
- `services/frontend/src/frontend/templates/base.html` — version in sidebar
- All `pyproject.toml` files — align versions
- All `Dockerfile` files — add version label
- New: `.github/workflows/release.yml` — auto-tag + GitHub Release on main merge

### 1.2 Playlists Page Empty Bug

**Root Cause:** `/playlists` reads from the `cached_playlists` table, which is only populated when a user manually clicks "Fetch Tracks" on an individual playlist. If no tracks have ever been fetched, the page shows "No cached playlists found."

**Fix:** `GET /api/me/playlists` fetches the playlist list live from Spotify (via `SpotifyClient.get_user_playlists()`) and upserts into `cached_playlists` when cache is empty or stale (>1 hour TTL). Add a "Refresh" button for manual re-fetch.

**Files:**
- `services/api/src/app/explorer/service.py` — `get_playlists()`: Spotify fetch + cache upsert
- `services/explorer/src/explorer/templates/playlists.html` — "Refresh" button
- `services/explorer/src/explorer/routes/playlists.py` — refresh route

### 1.3 Admin Logs — user_id / job_run_id Never Populated

**Root Cause:** `DBLogHandler.emit()` reads `user_id`, `job_run_id`, `import_job_id` via `getattr(record, ...)`, but no code anywhere passes these in the `extra={}` dict when calling `logger.info()`, `logger.error()`, etc.

**Fix:**
- Create a `LogContext` helper using `contextvars` that auto-attaches `user_id` and `job_run_id` to log records
- In the collector, set context on job start (user_id from the job, job_run_id from tracked run)
- In the API, use request middleware to attach `user_id` from JWT
- `DBLogHandler.emit()` falls back to context vars when record attrs are missing

**Files:**
- New: `services/shared/src/shared/logging/context.py` — `LogContext` with contextvars
- `services/shared/src/shared/logging/handler.py` — context var fallback
- `services/collector/src/collector/job_tracking.py` — set context on job start
- New: `services/api/src/app/logging/middleware.py` — request middleware to set user_id
- Retrofit key log calls in collector (`polling.py`, `initial_sync.py`, `zip_import.py`)

### 1.4 Admin UI — Manual Job Trigger & Cancel

**Current state:** "Trigger Re-sync" exists on user detail page only. No cancel capability. No general trigger interface.

**Additions:**
- Action bar on admin jobs page with "Trigger Poll" / "Trigger Initial Sync" buttons (per-user dropdown)
- "Cancel" button on running jobs (sets cancellation flag in `job_runs`, collector checks between batches)
- New `cancelled_at` column on `job_runs` table

**Files:**
- `services/shared/src/shared/db/models/operations.py` — add `cancelled_at`
- New migration: `010_job_cancellation`
- `services/api/src/app/admin/router.py` — cancel endpoint, generalized trigger endpoints
- `services/frontend/src/frontend/routes/jobs.py` — trigger/cancel UI
- `services/frontend/src/frontend/templates/jobs.html` — buttons
- `services/collector/src/collector/job_tracking.py` — cancellation check helper

**Estimated scope:** ~22 files modified, 1 migration, 3 new modules

---

## Phase 2 — Explorer Navigation & Browsable Collections

**Branch:** `feat/phase-2-explorer-navigation`
**Version:** 0.2.0 → 0.3.0

### 2.1 Clickable Dashboard Stats

All 4 stat cards become clickable links:

| Card | Links to |
|------|----------|
| Total Plays | `/history` (existing) |
| Unique Tracks | `/tracks` (new) |
| Unique Artists | `/artists` (new) |
| Hours Listened | `/history` (existing) |

**New pages:**
- **`/tracks`** — Paginated track browser with search, sortable by play count / name / last played. Columns: Track, Artist(s), Play Count, Last Played. Rows link to `/tracks/{track_id}` (Phase 4).
- **`/artists`** — Paginated artist browser with search, sortable by play count / name. Columns: Artist, Play Count, Track Count. Rows link to `/artists/{artist_id}` (Phase 4).

### 2.2 Customizable Time Window for Top Artists/Tracks

- Dropdown selector (7d / 30d / 90d / 1y / All time) on dashboard
- HTMX-swaps top artists/tracks tables on change (no full page reload)
- Increase default to 10 items, add "See all" links to `/tracks` and `/artists`

**New API endpoints:**
- `GET /api/me/tracks?limit=50&offset=0&sort=play_count&q=...`
- `GET /api/me/artists?limit=50&offset=0&sort=play_count&q=...`

**Files:**
- `services/api/src/app/explorer/service.py` — parameterize `get_dashboard()` with `days`, new list queries
- `services/api/src/app/explorer/router.py` — accept `days` query param, new list endpoints
- `services/explorer/src/explorer/routes/dashboard.py` — pass days param
- `services/explorer/src/explorer/templates/dashboard.html` — time selector + HTMX partials
- New: `services/explorer/src/explorer/routes/tracks.py` — tracks browser
- New: `services/explorer/src/explorer/routes/artists.py` — artists browser
- New: templates `tracks.html`, `artists.html` + partials
- `services/explorer/src/explorer/api_client.py` — new methods
- `services/explorer/src/explorer/templates/base.html` — add nav items

**Estimated scope:** ~12 files modified, 4-6 new

---

## Phase 3 — MCP Protocol Compliance & Claude Integration

**Branch:** `feat/phase-3-mcp-protocol`
**Version:** 0.3.0 → 0.4.0

Our existing `/mcp/call` is a custom REST API designed for ChatGPT. It is not the Model Context Protocol. To work natively with Claude Desktop, Claude Code, and claude.ai Integrations, we need to implement the actual MCP specification: JSON-RPC 2.0 over HTTP with streamable HTTP and SSE transports.

This phase is placed before entity details (Phase 4) because it is self-contained, leverages the existing tool registry without modifications, and delivers immediate value for Claude users.

### 3.1 MCP JSON-RPC Server

**Protocol:** JSON-RPC 2.0, two transports in parallel:

| Transport | Endpoint | Used by |
|-----------|----------|---------|
| Streamable HTTP | `POST /mcp` | Claude Desktop 0.8+, Claude Code, future clients |
| SSE | `GET /mcp/sse` | Older Claude Desktop versions |

Both transports remain alongside existing `POST /mcp/call` (ChatGPT backward compatibility unchanged).

**JSON-RPC methods:**
- `initialize` — capability handshake, returns server info + supported capabilities
- `tools/list` — translates `MCPToolRegistry` into MCP schema format (name, description, inputSchema)
- `tools/call` — dispatches to existing tool handlers, wraps result as MCP `content` array
- `ping` — keep-alive / health check
- `notifications/cancelled` — honour cancellation signals (no-op safe)

**Tool schema translation:**
Our registry already stores `name`, `description`, `parameters` (JSON Schema). MCP's `tools/list` expects `name`, `description`, `inputSchema` — a near-identical structure. The translation adds `type: "object"` wrapper and maps appropriately.

**Result mapping:**
Tool handlers return raw dicts/lists. MCP `tools/call` response wraps these as:
```json
{"content": [{"type": "text", "text": "<json-serialised result>"}]}
```

### 3.2 Authentication

**Phase 3 — Bearer token:**
- All existing Bearer token middleware applies unchanged to the new `/mcp` routes
- Claude Desktop: add `headers: { "Authorization": "Bearer <token>" }` in `claude_desktop_config.json`
- Claude Code: `.mcp.json` in repo root with `headers` field

**Future — OAuth 2.0 (deferred to Phase 8):**
- claude.ai Integrations officially uses OAuth 2.0 for remote MCP connections
- Phase 3 documents a manual Bearer token workaround for claude.ai power users
- Full OAuth server (PKCE flow) deferred — builds naturally on Phase 7 auth infrastructure

### 3.3 Claude Desktop Config

Users add this to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or equivalent:
```json
{
  "mcpServers": {
    "spotify-history": {
      "url": "https://music.praxiscode.dev/mcp",
      "headers": {
        "Authorization": "Bearer <your-api-token>"
      }
    }
  }
}
```
All 34 existing tools become immediately available in Claude Desktop.

### 3.4 Claude Code MCP Config

Add `.mcp.json` to repo root for developers using Claude Code:
```json
{
  "mcpServers": {
    "spotify-history": {
      "url": "https://music.praxiscode.dev/mcp",
      "headers": {
        "Authorization": "Bearer <your-api-token>"
      }
    }
  }
}
```

### 3.5 API Token UI

Users need a way to generate/revoke Bearer tokens without admin involvement. Add a simple "API Tokens" page to the explorer:
- `GET /settings/tokens` — list tokens (name, created, last used)
- `POST /settings/tokens` — generate new named token
- `DELETE /settings/tokens/{id}` — revoke token

Tokens stored in new `api_tokens` table: `id`, `user_id`, `name`, `token_hash`, `created_at`, `last_used_at`, `revoked_at`.

New migration: `011_api_tokens`

### 3.6 Files

- New: `services/api/src/app/mcp/jsonrpc.py` — JSON-RPC 2.0 Pydantic message types
- New: `services/api/src/app/mcp/mcp_handler.py` — `initialize`, `tools/list`, `tools/call` logic
- New: `services/api/src/app/mcp/sse_transport.py` — SSE transport (legacy Claude Desktop)
- `services/api/src/app/mcp/router.py` — add `POST /mcp` + `GET /mcp/sse` routes
- `services/api/src/app/mcp/registry.py` — add `to_mcp_schema()` method
- New: `services/shared/src/shared/db/models/auth.py` (or `tokens.py`) — `ApiToken` model
- New migration: `011_api_tokens`
- `services/api/src/app/explorer/router.py` — token management endpoints
- New: `services/explorer/src/explorer/routes/settings.py` — token management UI
- New: `services/explorer/src/explorer/templates/settings/tokens.html`
- New: `.mcp.json` — Claude Code MCP config
- New: `docs/claude-integration-setup.md` — setup guide for Claude Desktop + Claude Code

**Estimated scope:** ~12 new files, 4 modified, 1 migration

---

## Phase 4a — Entity Detail Pages + Spotify Enrichment

**Branch:** `feat/phase-4a-detail-pages`
**Version:** 0.4.0 → 0.5.0

Delivers track, artist, and album detail pages using DB data + live Spotify API enrichment. Replaces the "Under Construction" placeholders from Phase 2. No new external services or infrastructure.

### 4a.1 Data Sources

| Source | Provides | Already available? |
|--------|----------|--------------------|
| **DB (tracks/artists/plays)** | Name, duration, album, play count, first/last played, listening time | Yes |
| **DB (audio_features)** | Danceability, energy, valence, tempo, etc. | Table exists, unpopulated — show gracefully |
| **Spotify API (live)** | Images, popularity, preview URLs, followers, genres, album art | Yes — `SpotifyClient.get_track()`, `get_artist()`, `get_album()` |

Spotify enrichment is **optional** — pages render with DB data alone if the user has no Spotify token or API returns errors. Spotify responses are cached in-memory with a simple TTL dict (no new infrastructure).

### 4a.2 Track Detail Page (`/tracks/{track_id}`)

- **Header card:** Track name, artist(s) (linked to `/artists/{id}`), album name (linked to `/albums/{album_id}`), duration, Spotify external link
- **Spotify enrichment (if available):** Album cover art, popularity bar, ISRC, preview player
- **Personal Stats card:** Total plays, first/last played, total listening time
- **Audio Features card (if data exists):** Radar chart (ECharts) of danceability, energy, valence, acousticness, instrumentalness, speechiness
- **Recent Plays table:** Paginated play history for this track (HTMX)

### 4a.3 Artist Detail Page (`/artists/{artist_id}`)

- **Header card:** Artist name, Spotify external link
- **Spotify enrichment (if available):** Artist image, genres (as badges), popularity, followers count
- **Personal Stats card:** Total plays, unique tracks, total listening time, first/last played
- **Top Tracks table:** Most-played tracks by this artist (linked to `/tracks/{id}`)

### 4a.4 Album Detail Page (`/albums/{album_id}`)

Album pages are a new concept — albums are identified by `spotify_album_id` stored on tracks. No separate album DB table exists.

- **Header card:** Album name, artist(s), Spotify external link
- **Spotify enrichment (if available):** Album cover art, release date, label, total tracks
- **Personal Stats card:** Total plays across all album tracks, unique tracks played
- **Track Listing table:** All user-played tracks from this album with play counts (linked to `/tracks/{id}`)

Album detail uses `spotify_album_id` as the path parameter (not an integer DB ID, since there's no album table).

### 4a.5 ECharts Integration

- Apache ECharts via CDN (`<script src="cdn/echarts.min.js">`) — no build step
- Used for audio features radar chart on track detail
- Dark theme via ECharts theme JSON (matches Bootstrap dark)
- Prepared for reuse in Phase 5 (Analytics)

### 4a.6 New API Endpoints

- `GET /api/me/tracks/{track_id}` — Track detail + personal stats + audio features
- `GET /api/me/artists/{artist_id}` — Artist detail + personal stats + top tracks
- `GET /api/me/albums/{album_id}` — Album detail (Spotify lookup) + user play stats

### 4a.7 In-Memory Spotify Enrichment Cache

Simple module-level TTL dict for Spotify API responses (track/artist/album metadata). 24-hour TTL, capped at 500 entries, LRU eviction. No external dependencies. Replaced by Valkey in Phase 4b.

### 4a.8 Files

**API layer (`services/api/`):**
- `src/app/explorer/router.py` — 3 new detail endpoints
- `src/app/explorer/service.py` — `get_track_detail()`, `get_artist_detail()`, `get_album_detail()` queries
- `src/app/explorer/schemas.py` — `TrackDetail`, `ArtistDetail`, `AlbumDetail` response schemas

**Explorer frontend (`services/explorer/`):**
- `src/explorer/routes/tracks.py` — Replace placeholder with data fetch
- `src/explorer/routes/artists.py` — Replace placeholder with data fetch
- New: `src/explorer/routes/albums.py` — Album detail route
- `src/explorer/api_client.py` — `get_track_detail()`, `get_artist_detail()`, `get_album_detail()` methods
- New: `src/explorer/templates/track_detail.html`
- New: `src/explorer/templates/artist_detail.html`
- New: `src/explorer/templates/album_detail.html`

**Tests:**
- API: track detail, artist detail, album detail (found, not found, user isolation)
- Explorer: detail route rendering, 404 handling, Spotify enrichment fallback

**Estimated scope:** ~8-10 new files, 6-8 modified, no migrations, no new dependencies

---

## Phase 4b — External Enrichment + Valkey

**Branch:** `feat/phase-4b-enrichment`
**Version:** 0.5.0 → 0.6.0

Adds external data sources (MusicBrainz, Soundcharts) and persistent caching infrastructure (Valkey). Enriches the detail pages built in Phase 4a with additional metadata.

### 4b.1 CacheBackend Abstraction + Valkey

MusicBrainz enforces a strict 1 req/sec rate limit. Soundcharts is a paid-per-call API. Without persistent caching, every service restart triggers a cold-cache burst of external calls that either costs money (Soundcharts) or risks throttling (MusicBrainz). In-memory caches are not sufficient.

**Design — `CacheBackend` protocol:**
```python
class CacheBackend(Protocol):
    async def get(self, key: str) -> dict | None: ...
    async def set(self, key: str, value: dict, ttl_seconds: int) -> None: ...
    async def delete(self, key: str) -> None: ...
```

Two implementations:
- `PostgresCacheBackend` — reuses existing `SpotifyEntityCache` table; used automatically when `VALKEY_URL` is not set
- `ValkeyBackend` — uses `redis.asyncio.Redis` (Redis-compatible protocol, works against Valkey); used when `VALKEY_URL` is set

**Cache key scheme:**
| Key pattern | Source | TTL |
|-------------|--------|-----|
| `mb:recording:{isrc}` | MusicBrainz | 7 days |
| `mb:artist:{mbid}` | MusicBrainz | 7 days |
| `mb:release:{mbid}` | MusicBrainz | 7 days |
| `sc:features:{spotify_id}` | Soundcharts | 30 days |
| `sp:track:{track_id}` | Spotify enrichment | 24 hours |
| `sp:artist:{artist_id}` | Spotify enrichment | 24 hours |
| `sp:album:{album_id}` | Spotify enrichment | 24 hours |

**Infrastructure:**
- Local dev: add `valkey` service to `docker-compose.yml` (`valkey/valkey:7` image, port 6379)
- Production: provision DigitalOcean managed Valkey (smallest plan ~$15/month, fra1 region)
- New env var: `VALKEY_URL` (e.g. `valkey://localhost:6379`) — optional; omit to fall back to PostgreSQL cache

### 4b.2 MusicBrainz Client

- New: `services/shared/src/shared/musicbrainz/client.py` — async httpx, 1 req/sec rate limit, polite User-Agent
- New: `services/shared/src/shared/musicbrainz/models.py` — Pydantic models for Recording, Artist, Release, ReleaseGroup
- ISRC lookup (preferred, exact match) with fallback to artist+title search
- All responses cached via `CacheBackend` with 7-day TTL

Enriches detail pages with: record label, producers/credits, original release date, country/area, relationships, external links.

### 4b.3 Soundcharts Client + Audio Features Provider

- New: `services/shared/src/shared/soundcharts/client.py` — async httpx, API key auth
- New: `services/shared/src/shared/soundcharts/models.py` — Pydantic models
- New: `services/shared/src/shared/audio/provider.py` — `AudioFeaturesProvider` interface
  - `SpotifyAudioFeaturesProvider` — wraps existing client, 403 → disabled
  - `SoundchartsAudioFeaturesProvider` — wraps Soundcharts client
  - `ChainedAudioFeaturesProvider` — tries providers in order
- New env var: `SOUNDCHARTS_API_KEY`

### 4b.4 Audio Features Enrichment Job

- Background collector job (lowest priority, after polling)
- Uses `ChainedAudioFeaturesProvider` (Spotify → Soundcharts)
- Batch: up to 100 tracks per request
- Graceful degradation: 403 from Spotify → Soundcharts → disable enrichment
- Populates existing `audio_features` table

### 4b.5 Files

**Cache layer:**
- New: `services/shared/src/shared/cache/backend.py` — `CacheBackend` Protocol
- New: `services/shared/src/shared/cache/postgres_backend.py` — PostgreSQL implementation
- New: `services/shared/src/shared/cache/valkey_backend.py` — Valkey/Redis implementation
- `services/api/src/app/dependencies.py` — `CacheBackend` dependency injection
- `docker-compose.yml` — add `valkey` service
- `docker-compose.prod.yml` — `VALKEY_URL`

**External clients:**
- New: `services/shared/src/shared/musicbrainz/client.py`
- New: `services/shared/src/shared/musicbrainz/models.py`
- New: `services/shared/src/shared/soundcharts/client.py`
- New: `services/shared/src/shared/soundcharts/models.py`
- New: `services/shared/src/shared/audio/provider.py`

**Detail page enrichment:**
- `services/api/src/app/explorer/service.py` — add MB + Soundcharts data to detail responses
- `services/explorer/src/explorer/templates/track_detail.html` — MB credits section
- `services/explorer/src/explorer/templates/artist_detail.html` — MB metadata section
- `services/explorer/src/explorer/templates/album_detail.html` — MB credits section

**Estimated scope:** ~15-20 new files, 8-10 modified, `docker-compose.yml` changes

---

## Phase 5 — Analytics & Visualization

**Branch:** `feat/phase-5-analytics`
**Version:** 0.6.0 → 0.7.0

### 5.1 Charting Library: Apache ECharts via CDN

- ~1MB CDN include (or tree-shaken subset)
- Built-in: heatmaps, calendar heatmaps, radar, treemaps, sunburst, data zoom, brush selection
- Dark theme via ECharts theme builder (custom JSON)
- No build step, no npm — `<script src="cdn/echarts.min.js">`
- API returns JSON data → Jinja2 template serializes into `setOption()` config

### 5.2 Listening Heatmap

- New page: `/analytics`
- Weekday × hour heatmap (7 rows × 24 cols) with ECharts
- Time scope dropdown: 7d / 30d / 90d / 1y / All time
- HTMX swaps chart data on scope change
- Reuses existing `HistoryQueries.listening_heatmap()` backend

### 5.3 Listening Timeline

- Plays per day/week/month bar chart
- Time range selector with ECharts dataZoom (built-in brush/scroll)
- Toggle: plays count vs. minutes listened

### 5.4 Genre Distribution

- Pie/sunburst chart of genres from artist data
- Drill-down: click genre → see artists in that genre

### 5.5 Discovery Rate

- New vs. repeat tracks over time (stacked area chart)
- Shows exploration patterns

### 5.6 New API Endpoints

- `GET /api/me/analytics/heatmap?days=90` — 7×24 matrix
- `GET /api/me/analytics/timeline?days=90&bucket=week` — Plays over time
- `GET /api/me/analytics/genres?days=90` — Genre distribution
- `GET /api/me/analytics/discovery?days=90` — New vs. repeat over time

**Files:**
- New: `services/explorer/src/explorer/routes/analytics.py`
- New: `services/explorer/src/explorer/templates/analytics.html` + partials per chart
- `services/api/src/app/explorer/router.py` — analytics endpoints
- `services/api/src/app/explorer/service.py` — analytics queries
- `services/explorer/src/explorer/templates/base.html` — nav item "Analytics"

**Estimated scope:** ~6 new files, 4-5 modified

---

## Phase 6 — Taste Page Redesign

**Branch:** `feat/phase-6-taste-redesign`
**Version:** 0.7.0 → 0.8.0

### 6.1 Visual Taste Dashboard

- **Radar chart** (ECharts) of energy/mood preferences
- **Genre cloud** with weighted sizing (more mentioned = bigger)
- **Color-coded cards:** likes (green), dislikes (red), rules (blue)

### 6.2 Full Inline Editing

- All profile fields editable via HTMX forms (not just genres/avoid)
- **Energy preferences:** Range sliders for energy_level, tempo_preference, etc.
- **Playlist rules:** Editable key-value pairs with add/remove
- **Free-form notes/feedback** textarea

### 6.3 Preference Events Timeline

- Visual timeline grouped by date (instead of plain table)
- Source badges (user / assistant / inferred)
- Filter by event type

### 6.4 AI Integration Hints

- Source indicators on each preference (user-set vs. AI-inferred)
- Quick accept/reject for AI-inferred suggestions

**Files:**
- `services/explorer/src/explorer/templates/taste.html` — major rewrite
- `services/explorer/src/explorer/routes/taste.py` — additional field-type routes
- New: partials for radar chart, genre cloud, event timeline
- `services/explorer/src/explorer/static/css/style.css` — taste-specific styles

**Estimated scope:** ~5-8 files

---

## Phase 7 — BYOK User Management & Email Auth

**Branch:** `feat/phase-7-byok-auth`
**Version:** 0.7.0 → 1.0.0 (breaking: new auth model)

Largest phase. Can be split into sub-phases (7a, 7b, 7c) as separate PRs if needed.

### 7a — Email/Password Auth Foundation

**New DB tables:**
- `user_credentials` — email, hashed_password (bcrypt), email_verified, verification_token, reset_token, reset_token_expires_at
- `invitations` — email, invited_by (user_id), role (key_holder / delegated), token, expires_at, accepted_at

**New migration:** `012_email_auth_invitations`

**Auth endpoints:**
- `POST /auth/register` — email/password registration (with invitation token)
- `POST /auth/login-email` — email/password login → JWT pair
- `GET /auth/verify-email?token=...` — email verification
- `POST /auth/forgot-password` — send reset link
- `POST /auth/reset-password` — set new password with reset token

**Email service:** Resend (simple API, free tier 100 emails/day)
- New: `services/shared/src/shared/email/service.py`
- HTML templates for invitation, verification, password reset emails

### 7b — BYOK Onboarding

**Onboarding wizard flow:**
1. Admin invites new user → email with invitation link
2. User clicks link → registration page (email pre-filled, set password)
3. After registration → onboarding wizard:
   - Step 1: Welcome + system explanation
   - Step 2: Create Spotify Developer App (screenshot guide)
   - Step 3: Enter Client ID + Client Secret → validated against Spotify API
   - Step 4: Authorize Spotify account (OAuth with their own key)
   - Step 5: Done — collector starts

**Key holder model:** Leverages existing `User.custom_client_id` / `custom_client_secret` fields + new `invited_by` FK and `is_key_holder` boolean flag.

### 7c — Delegated User Management

**Flow:**
1. Key holder goes to "My Team" page in explorer
2. Can invite up to 4 additional users (Spotify dev mode limit)
3. Invited user registers → authorizes with key holder's client ID/secret
4. Key holder can manage (pause/remove) delegated users

**Enforcement:**
- Max 4 delegated users per key holder (Spotify dev mode restriction)
- Delegated users inherit key holder's Spotify credentials for all API calls
- Key holder removal → all delegated users paused

### 7d — MCP OAuth for claude.ai Integrations

Build on the Phase 7 auth infrastructure to add proper OAuth 2.0 for the MCP server (enabling official claude.ai Integrations support):
- `GET /oauth/authorize` — authorization endpoint (PKCE)
- `POST /oauth/token` — token exchange
- `GET /oauth/callback` — redirect handler
- Register application in claude.ai Integrations catalog (if/when available)

**Files (across 7a-7d):**
- New migration: `012_email_auth_invitations`
- New: `services/shared/src/shared/db/models/auth.py` — UserCredential, Invitation models
- New: `services/shared/src/shared/email/service.py` — Resend email client
- `services/api/src/app/auth/router.py` — email auth endpoints + OAuth endpoints
- New: `services/api/src/app/auth/registration.py` — registration service
- New: `services/explorer/src/explorer/routes/onboarding.py` — onboarding wizard UI
- New: `services/explorer/src/explorer/routes/team.py` — delegated user management
- New: templates for registration, onboarding wizard, team management
- `services/frontend/src/frontend/routes/users.py` — invitation UI in admin

**Estimated scope:** ~25-35 new files, 10-15 modified, 1 migration

---

## Phase 8 — Deferred Tasks & Polish

**Branch:** `feat/phase-8-deferred-polish`
**Version:** 1.0.0 → 1.1.0

### 8.1 Local Track Resolution

- Resolve `local:<sha1>` IDs from ZIP imports via Spotify search
- Match by artist + track name, confidence scoring
- Batch processing in collector
- Store resolution mapping for future imports

### 8.2 Documentation Updates

- Update ChatGPT OpenAPI spec (`docs/chatgpt-openapi.json`)
- Update tool catalog (`docs/chatgpt-tool-catalog.md`)
- Update `CLAUDE.md` with new architecture (MusicBrainz, Soundcharts, email auth, ECharts, Valkey, MCP protocol)
- Update `docs/claude-integration-setup.md` with OAuth instructions from Phase 7d

**Estimated scope:** ~8-10 files

---

## Phase Execution Order & Dependencies

```
Phase 1 (Bug fixes, versioning, admin)         <- Start here, no dependencies
  |
Phase 2 (Navigation & browsing)                <- Needs Phase 1 (playlists fix)
  |
Phase 3 (MCP protocol + Claude integration)    <- Needs Phase 1 (API token table)
  |                                               Can run in parallel with Phase 2
  |
Phase 4a (Detail pages + Spotify enrichment)    <- Needs Phase 2 (track/artist browsers)
  |
Phase 4b (MB + Soundcharts + Valkey)            <- Needs Phase 4a (detail page templates)
  |
  +-- Phase 5 (Analytics + ECharts)            <- Can run in parallel with Phase 6
  |
  +-- Phase 6 (Taste redesign)                 <- Can run in parallel with Phase 5
  |
Phase 7 (BYOK auth)                            <- Independent of UI phases; largest
  |
Phase 8 (Deferred tasks & polish)              <- Final
```

---

## Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Charting library** | Apache ECharts via CDN | Built-in heatmaps, radar, data zoom, brush selection, dark theme. ~1MB. No architecture change needed — stays within Jinja2+HTMX. |
| **Audio features source** | Soundcharts (primary) + Spotify (fallback) | Soundcharts provides same 0.0-1.0 features as deprecated Spotify endpoint, lookup by Spotify ID/ISRC. Abstract provider interface for swappability. |
| **Metadata enrichment** | Spotify + MusicBrainz | Spotify for images/popularity. MusicBrainz for labels, credits, release dates, genre tags. ISRC-based lookup. Free, no API key. |
| **Cache layer** | In-memory TTL cache in Phase 4a; `CacheBackend` abstraction + Valkey in Phase 4b | Phase 4a uses simple in-memory cache (no infra). Phase 4b adds Valkey for MusicBrainz 1 req/sec + Soundcharts paid-per-call where persistent cache is essential. PostgreSQL fallback keeps tests simple. |
| **Email service** | Resend | Simple REST API, free tier 100 emails/day, sufficient for invitation flow. |
| **Stay on Jinja2+HTMX** | Yes | Switching to React/Svelte would mean rewriting all templates + adding build pipeline. ECharts provides the charting power we need client-side. |
| **MCP protocol** | JSON-RPC 2.0 over streamable HTTP + SSE | Standard MCP spec. Unlocks Claude Desktop, Claude Code, and future claude.ai Integrations. Existing `/mcp/call` kept for ChatGPT. |
| **MCP auth Phase 3** | Bearer token | Zero new infrastructure. Claude Desktop + Claude Code both support `headers` in config. OAuth added in Phase 7d on top of BYOK auth. |
| **Versioning** | Single source of truth in `shared/version.py` + git tags + GitHub Releases | All services read from one file. Tags enable rollback, releases provide changelog. CI automates tagging. |

---

## Version Roadmap

| Phase | Version | Type |
|-------|---------|------|
| Baseline (current) | 0.1.0 | — |
| Phase 1: Bug fixes, versioning & admin | 0.2.0 | infra/patch |
| Phase 2: Navigation & browsing | 0.3.0 | minor |
| Phase 3: MCP protocol + Claude integration | 0.4.0 | minor |
| Phase 4a: Detail pages + Spotify enrichment | 0.5.0 | minor |
| Phase 4b: MB + Soundcharts + Valkey | 0.6.0 | minor |
| Phase 5: Analytics + ECharts | 0.7.0 | minor |
| Phase 6: Taste redesign | 0.8.0 | minor |
| Phase 7: BYOK auth + MCP OAuth | 1.0.0 | major (breaking) |
| Phase 8: Deferred tasks & polish | 1.1.0 | minor |

---

## External Service Requirements

| Service | Purpose | What's Needed | Notes |
|---------|---------|---------------|-------|
| **Soundcharts** | Audio features (danceability, energy, etc.) | API key | Paid; pricing at developers.soundcharts.com |
| **MusicBrainz** | Metadata enrichment (labels, credits, dates) | None | Free; 1 req/sec limit; polite User-Agent required |
| **Resend** | Invitation & password reset emails | API key | Free tier: 100 emails/day |
| **DigitalOcean Valkey** | Persistent cache for external API responses | Provisioned in DO panel | ~$15/month, fra1 region, smallest plan |
| **Spotify** | Existing — OAuth, playback data, metadata | Already configured | — |

---

## New Environment Variables (by phase)

### Phase 3
```
# No new external service keys — Bearer tokens managed via new /settings/tokens UI
```

### Phase 4a

```dotenv
# No new env vars — uses existing Spotify credentials + in-memory cache
```

### Phase 4b

```dotenv
SOUNDCHARTS_API_KEY=        # Soundcharts API key for audio features
VALKEY_URL=                 # e.g. valkey://localhost:6379 (omit to use PostgreSQL cache)
```

### Phase 7
```
RESEND_API_KEY=             # Resend email service API key
RESEND_FROM_EMAIL=          # Sender address (e.g. noreply@music.praxiscode.dev)
APP_BASE_URL=               # Public URL for email links (e.g. https://music.praxiscode.dev)
```

---

## Infrastructure Evaluation: Managed Valkey & OpenSearch

### Valkey (DigitalOcean Managed Redis-compatible cache)

**Verdict: Yes — provisioned in Phase 4.**

Where it adds genuine value:
- **MusicBrainz caching** — strict 1 req/sec rate limit makes a persistent, TTL-native cache essential. Without it, every deploy triggers a cold-cache burst that risks throttling.
- **Soundcharts caching** — paid per-call API; duplicate calls for the same track across restarts cost money.
- **Restart-safe** — in-memory caches reset on every deploy; Valkey survives restarts and redeploys.

Design approach:
- `CacheBackend` abstraction introduced in Phase 4 so all caching goes through one interface
- `PostgresCacheBackend` used in tests (no extra service needed)
- `ValkeyBackend` used in production when `VALKEY_URL` is set
- Local dev: `valkey/valkey:7` in `docker-compose.yml`

---

### OpenSearch (DigitalOcean Managed Elasticsearch fork)

**Verdict: Not needed.**

Our FTS needs (track/artist name search) are fully covered by PostgreSQL `to_tsvector / plainto_tsquery` — already implemented and in production. Our logs are in a PostgreSQL `logs` table with a working admin UI viewer. Track and artist discovery search is delegated to Spotify's API. Our analytics are SQL aggregations, not log-stream analysis.

OpenSearch earns its keep at 10+ services emitting millions of log events per day, or for complex faceted search over unstructured documents. We have neither. Adding it would cost ~$50+/month for a managed service that replicates what PostgreSQL already does.
