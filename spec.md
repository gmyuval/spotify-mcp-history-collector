# Spotify MCP Server + History Collector + Admin Frontend (Python/FastAPI/Docker) — Developer Spec

## 1) Goal

Build a containerized system that enables a ChatGPT-style assistant to analyze Spotify listening patterns by **collecting playback history over time** and exposing it via an MCP-compatible tool interface.

### Services

1. **spotify-mcp-api** (FastAPI)
   - Spotify OAuth (login/callback)
   - MCP-like tool catalog + tool invocation endpoints
   - History query + analysis endpoints (90-day summary, top artists, etc.)
   - Admin APIs for users, sync/import status, and logs

2. **spotify-history-collector** (Python worker)
   - Periodically polls Spotify **Recently Played** and stores plays (deduped)
   - Performs **initial sync** on first run to backfill as much history as Spotify allows via API paging
   - Supports **ZIP ingestion** of Spotify “Download your data” exports (Extended Streaming History) for deeper backfill
   - Optional metadata enrichment (audio features, artist genres)

3. **admin-frontend** (FastAPI UI service)
   - Management UI: users, token status, sync/import status, job runs
   - Analytics views: top artists/tracks, heatmaps, taste summary
   - Log viewer (API + collector logs) with filtering/search
   - Trigger actions: initial sync, import ZIP, resync, pause/resume, diagnostics

4. **postgres**
   - Stores users, tokens, plays, metadata, sync checkpoints, job runs, import jobs, and logs

**Why this system?** Spotify’s Web API does not provide a full “last 90 days raw playback log.” Reliable 90+ day analysis requires **continuous collection** (poll + store). Backfill is **best-effort** via API paging and/or user exports.

---

## 2) Requirements (hard)

- **Python >= 3.14**
- **FastAPI** for API and frontend services
- **Docker** and **docker-compose**
- **Complete type hints** everywhere
- **DB**: PostgreSQL
- **ChatGPT integration** as a tool (see Section 12)

---

## 3) High-level architecture

### Components
- `spotify-mcp-api` (FastAPI)
- `spotify-history-collector` (worker)
- `admin-frontend` (FastAPI UI)
- `postgres`

*(Optional later)* Redis for locks/caching; Loki/ELK for logs.

### Data flow
1. User authorizes Spotify via API OAuth endpoints.
2. API stores encrypted refresh token and user profile in Postgres.
3. Collector:
   - Ingests pending ZIP imports (if any)
   - Performs **initial API sync** (best-effort backfill)
   - Performs periodic incremental polling (every N minutes)
4. API provides MCP tool endpoints consumed by ChatGPT (or any client).
5. Frontend calls API to manage users, monitor sync/import, and view logs.

---

## 4) Spotify OAuth requirements

### Scopes
Minimum:
- `user-read-recently-played`
- `user-top-read`

Optional but useful:
- `user-read-email`
- `user-read-private`

### OAuth flow
API provides:
- `GET /auth/login` → redirects to Spotify authorize URL
- `GET /auth/callback` → exchanges code for tokens, stores refresh token (encrypted)

Token refresh:
- performed by collector and/or API on demand

Security note:
- `TOKEN_ENCRYPTION_KEY` env var encrypts refresh tokens at rest (never store raw refresh tokens).

---

## 5) Backfill options: API initial sync + ZIP import

Spotify Web API **does not** provide arbitrary long-range playback logs. The `/me/player/recently-played` endpoint provides a limited window and caps results per request (typically 50), with time-based paging.

Therefore:
- **Incremental collection** (polling) is required for reliable long-term history.
- **API initial sync** is best-effort and limited by Spotify’s accessible history window.
- **ZIP import** of Spotify’s “Download your data” export enables deeper backfill (subject to what the export contains).

### 5.1 API initial sync (best-effort)

On first startup (or after token registration), the collector should attempt to page backwards using `before` until it can no longer retrieve earlier results or hits configured safety caps.

**Config**
- `INITIAL_SYNC_ENABLED: bool` (default `true`)
- `INITIAL_SYNC_MAX_DAYS: int` (default `30`)
- `INITIAL_SYNC_MAX_REQUESTS: int` (default `200`)
- `INITIAL_SYNC_STOP_ON_NO_PROGRESS: bool` (default `true`)
- `INITIAL_SYNC_CONCURRENCY: int` (default `2`)

**Paging algorithm**
- Start with `before=now`, `limit=50`
- For each batch:
  - Upsert tracks/artists (when IDs are present)
  - Insert plays
  - Track oldest `played_at`
  - Next `before = oldest_played_at - 1ms`

**Stop conditions**
- Empty batch
- Oldest `played_at` does not move
- Reached `INITIAL_SYNC_MAX_DAYS`
- Reached `INITIAL_SYNC_MAX_REQUESTS`
- Excessive 429s beyond backoff policy

### 5.2 ZIP import (Extended Streaming History) — user-provided backfill

Support ingesting a ZIP file that a user manually downloads from Spotify via “Download your data” → **Extended streaming history**.

**Privacy note**
Extended history may contain sensitive fields (depending on export format). The ingestion must:
- Strip/ignore sensitive fields by default (e.g., IP address, user agent)
- Persist only fields required for analysis
- Provide a config flag to persist extra fields *only if explicitly enabled*

**Supported formats**
Spotify exports have evolved. The importer should support at least:
- `endsong_*.json` (common in extended history exports)
- `StreamingHistory*.json` / `Streaming_History_Audio_*.json` (account data exports)

**Normalization mapping**
Importer normalizes each record into an internal structure:
- `played_at`: parse `ts` (ISO) or `endTime` (string) depending on file format
- `ms_played`: `msPlayed` when available
- `track_name`: `trackName` or `master_metadata_track_name` (when present)
- `artist_name`: `artistName` or `master_metadata_album_artist_name` (when present)
- `album_name`: where available
- `spotify_track_uri`: `spotify_track_uri` when present
- Optional fields (store only if enabled): `reasonStart`, `reasonEnd`, `shuffle`, `skipped`, `offline`, etc.

**Linking imported plays to track IDs**
- If `spotify_track_uri` is present, derive Spotify track ID and use it.
- Otherwise, create deterministic local IDs:
  - `local_track_id = "local:" + sha1(artist_name + "|" + track_name + "|" + album_name)`
- Store these as rows in `tracks` with `track_id=local_track_id`, `source="import_zip"`.
- Optional: enqueue enrichment to resolve real Spotify IDs via Spotify search (best-effort).

**How ZIP import is triggered**
At least one mechanism (both are acceptable):

- **Admin API upload**
  - `POST /admin/users/{user_id}/imports/zip` (multipart upload)
  - API stores ZIP in a shared volume (or object storage) and creates an `import_jobs` row
  - Collector picks up pending jobs

- **Watched directory**
  - Collector scans `IMPORT_WATCH_DIR` for new ZIPs and ingests them

**Importer safety**
- `IMPORT_MAX_ZIP_SIZE_MB` (default `500`)
- `IMPORT_MAX_RECORDS` (default `5_000_000`)
- Streaming JSON parsing (do not load entire file into memory)
- Batch transactions (e.g., 5k–20k records per commit)

---

## 6) Database (PostgreSQL) schema

### 6.1 Core tables

#### `users`
- `id: uuid` (PK)
- `spotify_user_id: text` (unique)
- `email: text | null`
- `display_name: text | null`
- `created_at: timestamptz`
- `updated_at: timestamptz`

#### `spotify_tokens`
- `user_id: uuid` (PK, FK users.id)
- `refresh_token_enc: text`
- `access_token: text | null`
- `access_token_expires_at: timestamptz | null`
- `scope: text`
- `token_type: text`
- `updated_at: timestamptz`

#### `tracks`
- `track_id: text` (PK)  
  - Spotify ID when known, otherwise `local:<sha1...>` for imported plays without Spotify IDs
- `name: text`
- `album_id: text | null`
- `album_name: text | null`
- `duration_ms: int | null` (nullable for imported tracks if unknown)
- `explicit: bool | null`
- `popularity: int | null`
- `preview_url: text | null`
- `uri: text | null` (Spotify URI when known)
- `source: text` (`spotify_api|import_zip`)
- `updated_at: timestamptz`

#### `artists`
- `artist_id: text` (PK)  
  - Spotify ID when known, otherwise `local:<sha1...>` if needed
- `name: text`
- `genres: jsonb` (list[str]) (optional)
- `popularity: int | null`
- `uri: text | null`
- `source: text` (`spotify_api|import_zip`)
- `updated_at: timestamptz`

#### `track_artists`
- `track_id: text` (FK tracks.track_id)
- `artist_id: text` (FK artists.artist_id)
- `position: int`
- PK: (`track_id`, `artist_id`)

#### `plays`
- `id: bigserial` (PK)
- `user_id: uuid` (FK)
- `played_at: timestamptz`
- `track_id: text` (FK)
- `ms_played: int | null`
- `context_type: text | null` (playlist/album/artist)
- `context_uri: text | null`
- `source: text` (`spotify_api|import_zip`)
- Unique constraint: (`user_id`, `played_at`, `track_id`)
- Indexes:
  - (`user_id`, `played_at` DESC)
  - (`track_id`)

#### `audio_features` (optional)
- `track_id: text` (PK, FK tracks.track_id)
- `danceability: float`
- `energy: float`
- `valence: float`
- `tempo: float`
- `instrumentalness: float`
- `acousticness: float`
- `liveness: float`
- `speechiness: float`
- `loudness: float`
- `mode: int`
- `key: int`
- `time_signature: int`
- `updated_at: timestamptz`

### 6.2 Operational tables

#### `sync_checkpoints`
Tracks sync progress per user.
- `user_id: uuid` (PK, FK users.id)
- `initial_sync_started_at: timestamptz | null`
- `initial_sync_completed_at: timestamptz | null`
- `initial_sync_earliest_played_at: timestamptz | null`
- `last_poll_started_at: timestamptz | null`
- `last_poll_completed_at: timestamptz | null`
- `last_poll_latest_played_at: timestamptz | null`
- `status: text` (`idle|importing|initial_sync|polling|error|paused`)
- `error_message: text | null`
- `updated_at: timestamptz`

#### `job_runs`
Collector job execution records.
- `id: bigserial` (PK)
- `job_type: text` (`import_zip|initial_sync|poll|enrich`)
- `user_id: uuid | null`
- `started_at: timestamptz`
- `finished_at: timestamptz | null`
- `status: text` (`success|error|partial`)
- `stats: jsonb` (counts: fetched, inserted, updated, rate_limits, files_processed)
- `error_message: text | null`

#### `import_jobs`
Tracks ZIP uploads/ingestions.
- `id: bigserial` (PK)
- `user_id: uuid` (FK)
- `uploaded_at: timestamptz`
- `started_at: timestamptz | null`
- `finished_at: timestamptz | null`
- `status: text` (`pending|running|success|error`)
- `storage_path: text` (path or object key)
- `file_size_bytes: bigint`
- `format_detected: text | null` (`endsong|streaming_history|mixed`)
- `records_ingested: bigint | null`
- `earliest_played_at: timestamptz | null`
- `latest_played_at: timestamptz | null`
- `error_message: text | null`

#### `logs`
Structured log events stored in DB (for UI browsing).
- `id: bigserial` (PK)
- `service: text` (`api|collector|frontend`)
- `level: text` (`debug|info|warning|error`)
- `timestamp: timestamptz`
- `message: text`
- `context: jsonb | null` (user_id, request_id, tool_name, job_run_id, etc.)
- Indexes:
  - (`service`, `timestamp` DESC)
  - optional GIN index on `context`

Retention:
- scheduled purge of logs older than N days.

---

## 7) Service responsibilities

## 7A) spotify-mcp-api (FastAPI)

### Endpoints (non-MCP)
- `GET /healthz`
- `GET /auth/login`
- `GET /auth/callback`
- `POST /auth/logout` (optional)

### Admin API endpoints (consumed by frontend)
- `GET /admin/users`
- `GET /admin/users/{user_id}`
- `POST /admin/users/{user_id}/pause`
- `POST /admin/users/{user_id}/resume`
- `POST /admin/users/{user_id}/initial-sync`
- `POST /admin/users/{user_id}/imports/zip` (upload ZIP and create `import_jobs`)
- `GET /admin/sync-status`
- `GET /admin/job-runs?user_id=...`
- `GET /admin/import-jobs?user_id=...`
- `GET /admin/logs?service=...&level=...&q=...&since=...`

### MCP interface endpoints (HTTP-based)
- `GET /mcp/tools`
- `POST /mcp/call`

#### `POST /mcp/call` request format
```json
{
  "tool": "history.taste_summary",
  "args": { "days": 90, "user_id": "..." }
}
```

### Tools to implement (initial)

#### DB-backed history tools
- `history.taste_summary(days: int = 90, user_id: UUID) -> TasteSummary`
- `history.top_artists(days: int = 90, limit: int = 20, user_id: UUID) -> list[ArtistCount]`
- `history.top_tracks(days: int = 90, limit: int = 20, user_id: UUID) -> list[TrackCount]`
- `history.listening_heatmap(days: int = 90, user_id: UUID) -> Heatmap`
- `history.repeat_rate(days: int = 90, user_id: UUID) -> RepeatStats`
- `history.coverage(days: int = 90, user_id: UUID) -> CoverageStats` (data completeness for the requested window)

#### Spotify live tools
- `spotify.get_top(entity: Literal["artists","tracks"], time_range: Literal["short_term","medium_term","long_term"], limit: int = 20, user_id: UUID) -> TopResponse`
- `spotify.search(q: str, type: list[Literal["track","artist","album","playlist"]], limit: int = 10, user_id: UUID) -> SearchResponse`

#### Ops tools (optional)
- `ops.sync_status(user_id: UUID) -> SyncStatus`
- `ops.latest_job_runs(user_id: UUID, limit: int = 20) -> list[JobRunSummary]`
- `ops.latest_import_jobs(user_id: UUID, limit: int = 20) -> list[ImportJobSummary]`

### Typed models / validation
- Use **Pydantic v2** for all request/response bodies.
- Full type hints everywhere (`from __future__ import annotations`).

### Spotify client wrapper
- Use `httpx.AsyncClient` with typed wrapper methods:
  - `get_recently_played(...)`
  - `get_top_tracks(...)`
  - `get_top_artists(...)`
  - `get_tracks(...)`
  - `get_audio_features(...)`
  - `get_artists(...)`

### DB access & migrations
- SQLAlchemy 2.0 async + `asyncpg`
- Alembic migrations
- Session context manager pattern

---

## 7B) spotify-history-collector (worker)

### Responsibilities
- Periodic polling for new plays
- API initial backfill (initial sync)
- ZIP import ingestion and normalization
- Optional enrichment (audio features, genres)
- Update `sync_checkpoints`, `job_runs`, `import_jobs`, and structured logs

### Collector run loop (priority order)
1. Pick pending `import_jobs` and process them.
2. For each user: if initial sync enabled and incomplete, run initial sync.
3. For each user: run incremental poll (unless paused).

### Concurrency & rate limiting
- `asyncio` + `httpx.AsyncClient`
- Limit concurrency with semaphore(s)
- Exponential backoff on 429 and 5xx
- For import jobs: avoid external calls except optional enrichment

### ZIP import ingestion details
- Detect ZIP format by filenames / JSON keys.
- Stream parse JSON arrays.
- Normalize records and insert in batches.
- Dedupe by DB uniqueness constraints.
- Update `import_jobs` (records ingested, earliest/latest timestamps).
- Write `job_runs` and DB log events.

---

## 7C) admin-frontend (FastAPI UI)

### Implementation (Python-only)
- FastAPI serving:
  - Server-rendered pages (Jinja2) + HTMX (recommended)
  - Or a single-page app served as static assets (still delivered via FastAPI)
- Auth:
  - Start with bearer token or basic auth (configurable)
  - Replace with SSO later if needed

### Pages
- Dashboard (health + recent activity)
- Users (token status + sync/import status)
- Imports (upload ZIP + view import jobs)
- Jobs (job runs list/detail)
- Logs (filter by service/level/time/search)
- Analytics (taste summary, top artists/tracks, heatmap)

---

## 8) Configuration

### Shared
- `DATABASE_URL`
- `TOKEN_ENCRYPTION_KEY`

### API
- `SPOTIFY_CLIENT_ID`
- `SPOTIFY_CLIENT_SECRET`
- `SPOTIFY_REDIRECT_URI`
- `ADMIN_AUTH_MODE` (`basic|token`)
- `ADMIN_TOKEN` (if token auth)
- `UPLOAD_DIR` (shared volume path for ZIP uploads)

### Collector
- `SPOTIFY_CLIENT_ID`
- `SPOTIFY_CLIENT_SECRET`
- `COLLECTOR_INTERVAL_SECONDS` (default `600`)
- `INITIAL_SYNC_ENABLED` (default `true`)
- `INITIAL_SYNC_MAX_DAYS` (default `30`)
- `INITIAL_SYNC_MAX_REQUESTS` (default `200`)
- `IMPORT_WATCH_DIR` (optional; if using watched directory imports)
- `IMPORT_MAX_ZIP_SIZE_MB` (default `500`)
- `IMPORT_MAX_RECORDS` (default `5_000_000`)

### Frontend
- `API_BASE_URL` (e.g., `http://api:8000` inside compose)
- `FRONTEND_AUTH_MODE` (mirror admin auth)

---

## 9) Repository layout (suggested)

- `spotify-mcp/`
  - `docker-compose.yml`
  - `.env.example`
  - `services/`
    - `api/`
      - `Dockerfile`
      - `pyproject.toml`
      - `src/app/`
        - `main.py`
        - `settings.py`
        - `auth/` (Spotify OAuth)
        - `mcp/` (tools + dispatcher)
        - `admin/` (admin APIs)
        - `db/` (models + session + alembic)
        - `history/` (queries + analysis)
        - `spotify/` (typed Spotify client)
        - `logging/` (DB log sink helpers)
    - `collector/`
      - `Dockerfile`
      - `pyproject.toml`
      - `src/collector/`
        - `main.py`
        - `settings.py`
        - `runloop.py`
        - `import_zip.py`
        - `initial_sync.py`
        - `polling.py`
        - `spotify_client.py`
        - `db.py`
        - `logging.py`
    - `frontend/`
      - `Dockerfile`
      - `pyproject.toml`
      - `src/frontend/`
        - `main.py` (FastAPI)
        - `templates/` (Jinja2)
        - `static/` (CSS/JS)

---

## 10) Docker / docker-compose

Services:
- `postgres`
- `api`
- `collector`
- `frontend`

Key details:
- Postgres healthcheck
- API depends_on Postgres healthy
- Collector depends_on Postgres healthy
- Frontend depends_on API

Example DB URL:
- `DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/spotify_mcp`

---

## 11) “Taste summary” tool (output contract)

`history.taste_summary(days=90, user_id=...)` returns:
- play count + unique tracks + unique artists
- top artists/tracks by play count
- repeat rate and concentration (e.g., top 10 share)
- listening heatmap by weekday/hour
- audio profile (if enriched): avg/median energy, danceability, valence, tempo
- taste clusters (optional): 3–6 clusters via simple rules or k-means
- coverage stats (how complete the requested window is)

Typed response model `TasteSummary`:
- `window_start: datetime`
- `window_end: datetime`
- `plays: int`
- `unique_tracks: int`
- `unique_artists: int`
- `top_artists: list[ArtistCount]`
- `top_tracks: list[TrackCount]`
- `repeat_stats: RepeatStats`
- `heatmap: Heatmap`
- `audio_profile: AudioProfile | None`
- `clusters: list[TasteCluster] | None`
- `coverage: CoverageStats`

---

## 12) Integration with ChatGPT as a tool

### Objective
Enable ChatGPT to call this system as a tool so it can answer:
- “Analyze my last 90 days”
- “What are my top artists this month?”
- “Compare this month to last month”
- “What does my taste cluster into?”

### Recommended integration: Custom GPT Actions (OpenAPI over HTTPS)
- FastAPI automatically exposes OpenAPI.
- Configure a Custom GPT Action pointing at `spotify-mcp-api`.
- Use token auth (`Authorization: Bearer <token>` or `X-Admin-Token`) stored as a secret in the GPT configuration.

Suggested endpoints for Actions:
- `POST /mcp/call` (primary)
- `GET /mcp/tools` (optional)

### Alternative: MCP client integration
- Use `/mcp/tools` and `/mcp/call` as an MCP-like transport for clients that support it.

### Auth and user mapping
- For multi-user support, tool args include `user_id`, or the auth token maps to a user.
- Never expose refresh tokens or PII in tool outputs.

---

## 13) Non-functional requirements

### Type hints
- Full typing on all functions/classes
- Recommended strict mypy:
  - `disallow_untyped_defs = True`
  - `warn_return_any = True`
  - `no_implicit_optional = True`

### Testing
- Unit tests:
  - token encryption/decryption
  - dedupe logic
  - initial sync paging logic (stop conditions)
  - ZIP import normalization + batching
  - history queries (90-day window)
- Integration tests:
  - Postgres in docker + API endpoints
  - Mock Spotify API via `respx`

### Observability
- Structured JSON logs in all services
- DB log sink for UI viewing (with retention)
- `job_runs`, `sync_checkpoints`, `import_jobs` for operational insight

---

## 14) Implementation plan (developer checklist)

1. Bootstrap repo + docker-compose + Postgres
2. Implement DB models + Alembic migrations
3. Implement Spotify OAuth endpoints + refresh token encryption
4. Implement typed Spotify client wrapper (`httpx`)
5. Implement collector:
   - ZIP import job processing + safety caps
   - initial API sync workflow + stop conditions
   - incremental polling workflow
   - job_runs + sync_checkpoints + logs updates
6. Implement MCP endpoints:
   - `/mcp/tools` catalog
   - `/mcp/call` dispatcher
7. Implement admin endpoints for UI (users, sync, imports, jobs, logs)
8. Implement admin frontend (FastAPI + Jinja2/HTMX)
9. Add tests + lint + mypy
10. Document ChatGPT tool integration steps (Actions or MCP client)
