# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a containerized system that enables ChatGPT-style assistants to analyze Spotify listening patterns by collecting playback history over time and exposing it via an MCP-compatible tool interface.

**Key Components:**
1. **spotify-mcp-api** (FastAPI) - Spotify OAuth, MCP tool endpoints, admin APIs
2. **spotify-history-collector** (Python worker) - Polls Spotify API, ingests ZIP exports, stores plays
3. **admin-frontend** (FastAPI UI) - Management UI for users, sync status, analytics, logs
4. **postgres** - Data storage

**Core Challenge:** Spotify's API doesn't provide full 90+ day playback history. This system solves it by:
- Continuous polling to collect plays over time
- Best-effort initial sync via API paging
- ZIP import support for Spotify "Download your data" exports (Extended Streaming History)

## Architecture & Data Flow

1. User authorizes Spotify via OAuth (`/auth/login` → `/auth/callback`)
2. API stores encrypted refresh token and user profile in Postgres
3. Collector runs in priority order:
   - Process pending ZIP imports from `import_jobs` table
   - Run initial sync for users (if enabled and incomplete)
   - Run incremental polling for all active users
4. MCP tool endpoints provide history analysis to ChatGPT or other clients
5. Admin frontend manages users, monitors sync/import status, views logs

**Database-First Design:**
- All sync state tracked in `sync_checkpoints` table
- Job execution recorded in `job_runs` and `import_jobs`
- Structured logs stored in `logs` table for UI browsing
- Plays deduped via unique constraint: `(user_id, played_at, track_id)`

## Workflow

- **Always work on a feature branch** — never commit directly to main
- **Present changes for review** before committing — list modified files with short explanations, wait for approval
- **After approval**: commit, push to origin, create PR on GitHub via `gh pr create`
- **Pre-commit hooks are active**: ruff (v0.15.0 lint+format) + mypy run on every commit; all must pass

## Commands

### Environment Setup
```bash
# Option A: Conda (recommended)
conda env create -f environment.yml
conda activate spotify-mcp
pre-commit install

# Option B: venv + make
python -m venv .venv && .venv\Scripts\activate  # Windows
make setup
```

### Dependency Management (pip-tools)
```bash
# Regenerate pinned requirements.txt from pyproject.toml
make compile-deps

# Upgrade all pins
make upgrade-deps
```

### Database
```bash
# Run migrations (inside Docker)
docker-compose exec api alembic upgrade head

# Run migrations (locally, from services/api/)
alembic upgrade head

# Create new migration
cd services/api && alembic revision --autogenerate -m "description"
```

### Development
```bash
make docker-up       # docker-compose up --build -d
make docker-down     # docker-compose down
make lint            # ruff check + format --check
make format          # ruff auto-fix + reformat
make typecheck       # mypy across all packages
make test            # pytest
make test-cov        # pytest with HTML coverage
```

## Repository Structure

```
services/
├── shared/                    # Shared database package (used by api + collector)
│   ├── pyproject.toml
│   └── src/shared/
│       ├── config/            # DatabaseSettings, DEFAULT_DATABASE_URL
│       └── db/
│           ├── base.py        # DeclarativeBase
│           ├── enums.py       # 6 StrEnums
│           ├── session.py     # DatabaseManager class
│           └── models/        # user.py, music.py, operations.py, log.py
├── api/                       # spotify-mcp-api (FastAPI)
│   ├── Dockerfile
│   ├── alembic/               # Database migrations
│   └── src/app/
│       ├── dependencies.py    # db_manager = DatabaseManager.from_env()
│       ├── main.py            # FastAPI app with lifespan
│       ├── auth/              # Spotify OAuth flow (stub)
│       ├── mcp/               # MCP tool catalog + dispatcher (stub)
│       ├── admin/             # Admin API endpoints (stub)
│       ├── history/           # History queries + analysis (stub)
│       ├── spotify/           # Typed Spotify client wrapper (stub)
│       ├── db/                # Re-exports from shared
│       └── logging/           # DB log sink helpers (stub)
├── collector/                 # spotify-history-collector (worker)
│   ├── Dockerfile
│   └── src/collector/
│       └── main.py            # Entry point (runloop placeholder)
└── frontend/                  # admin-frontend (FastAPI + Jinja2)
    ├── Dockerfile
    └── src/frontend/
        └── main.py
```

## Key Technical Decisions

### Type Safety
- **Python 3.14** required — PEP 649 lazy annotation evaluation is default; do NOT use `from __future__ import annotations`
- Complete type hints everywhere, use `X | None` instead of `Optional[X]`
- Use `enum.StrEnum` instead of `(str, enum.Enum)` — ruff UP042 promoted to safe fix
- Strict mypy configuration (see root `pyproject.toml`), `mypy_path` covers all source dirs
- Pydantic v2 for all request/response models

### Security
- Refresh tokens encrypted at rest using `TOKEN_ENCRYPTION_KEY`
- Never store raw refresh tokens in database
- Never expose refresh tokens or PII in MCP tool outputs
- ZIP imports strip sensitive fields (IP, user agent) by default

### Database (PostgreSQL + SQLAlchemy 2.0)
- Async operations with `asyncpg`
- `DatabaseManager` class in `shared.db.session` — OOP session management with `from_env()`, `session()`, `dependency()`, `dispose()`
- All models and enums live in `services/shared/src/shared/db/`
- Alembic for migrations (`services/api/alembic/`, `prepend_sys_path = src:../shared/src`)
- Docker images use `python:3.14-slim`

### Spotify API Client
- `httpx.AsyncClient` for all HTTP calls
- Exponential backoff on 429 (rate limits) and 5xx errors
- Concurrency control via semaphores
- Token refresh handled transparently

### ZIP Import Safety
- Streaming JSON parsing (never load entire file into memory)
- Batch transactions (5k-20k records per commit)
- Safety caps:
  - `IMPORT_MAX_ZIP_SIZE_MB` (default 500)
  - `IMPORT_MAX_RECORDS` (default 5,000,000)
- Support multiple formats: `endsong_*.json`, `StreamingHistory*.json`, etc.

### Local Track IDs
When ZIP imports lack Spotify URIs:
- Generate deterministic local IDs: `local:<sha1(artist|track|album)>`
- Store in `tracks` table with `source="import_zip"`
- Optional enrichment to resolve real Spotify IDs via search

## MCP Tools Implementation

### History Tools (DB-backed)
- `history.taste_summary(days, user_id)` - Comprehensive analysis
- `history.top_artists(days, limit, user_id)` - Top artists by play count
- `history.top_tracks(days, limit, user_id)` - Top tracks by play count
- `history.listening_heatmap(days, user_id)` - Weekday/hour patterns
- `history.repeat_rate(days, user_id)` - Track repeat statistics
- `history.coverage(days, user_id)` - Data completeness metrics

### Spotify Live Tools
- `spotify.get_top(entity, time_range, limit, user_id)` - Spotify's native "top" API
- `spotify.search(q, type, limit, user_id)` - Search tracks/artists/albums

### Ops Tools
- `ops.sync_status(user_id)` - Current sync state
- `ops.latest_job_runs(user_id, limit)` - Recent job history
- `ops.latest_import_jobs(user_id, limit)` - Recent imports

## Initial Sync Strategy

**Problem:** Spotify's `/me/player/recently-played` has limited history window and caps results at 50 per request.

**Solution:** Best-effort paging backwards using `before` parameter:
1. Start with `before=now`, `limit=50`
2. For each batch:
   - Upsert tracks/artists (when IDs present)
   - Insert plays (deduped by DB constraint)
   - Track oldest `played_at`
   - Next `before = oldest_played_at - 1ms`
3. Stop when:
   - Empty batch
   - No progress (oldest `played_at` unchanged)
   - Reached `INITIAL_SYNC_MAX_DAYS` (default 30)
   - Reached `INITIAL_SYNC_MAX_REQUESTS` (default 200)
   - Excessive 429s beyond backoff policy

**Config:**
- `INITIAL_SYNC_ENABLED` (default `true`)
- `INITIAL_SYNC_MAX_DAYS` (default `30`)
- `INITIAL_SYNC_MAX_REQUESTS` (default `200`)
- `INITIAL_SYNC_CONCURRENCY` (default `2`)

## Collector Run Loop Priority

1. **ZIP imports** - Process pending `import_jobs` first
2. **Initial sync** - For users where initial sync is enabled and incomplete
3. **Incremental polling** - For all active users (unless paused)

**Why this order?**
- ZIP imports provide bulk historical data
- Initial sync does best-effort backfill before starting incremental collection
- Incremental polling maintains currency

## Database Schema Highlights

### Core Tables
- `users` - Spotify user profiles
- `spotify_tokens` - Encrypted refresh tokens + access tokens
- `tracks` - Track metadata (Spotify IDs + local IDs from imports)
- `artists` - Artist metadata (Spotify IDs + local IDs from imports)
- `track_artists` - Many-to-many relationship
- `plays` - Individual play events (unique on `user_id`, `played_at`, `track_id`)
- `audio_features` - Optional enrichment (danceability, energy, etc.)

### Operational Tables
- `sync_checkpoints` - Per-user sync state (`initial_sync_completed_at`, `last_poll_latest_played_at`, etc.)
- `job_runs` - Job execution history (`import_zip|initial_sync|poll|enrich`)
- `import_jobs` - ZIP upload/ingestion tracking
- `logs` - Structured log events for UI browsing (with retention policy)

## Configuration Environment Variables

### Shared
- `DATABASE_URL` - PostgreSQL connection string
- `TOKEN_ENCRYPTION_KEY` - For encrypting refresh tokens

### API Service
- `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_REDIRECT_URI`
- `ADMIN_AUTH_MODE` (`basic|token`)
- `ADMIN_TOKEN` (if token auth)
- `UPLOAD_DIR` (shared volume for ZIP uploads)

### Collector Service
- `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`
- `COLLECTOR_INTERVAL_SECONDS` (default `600`)
- Initial sync config (see Initial Sync Strategy section)
- `IMPORT_WATCH_DIR` (optional watched directory)
- `IMPORT_MAX_ZIP_SIZE_MB`, `IMPORT_MAX_RECORDS`

### Frontend Service
- `API_BASE_URL` (e.g., `http://api:8000`)
- `FRONTEND_AUTH_MODE` (mirror admin auth)

## ChatGPT Integration

**Recommended:** Custom GPT Actions (OpenAPI over HTTPS)
- FastAPI auto-generates OpenAPI spec
- Configure Custom GPT Action pointing at `spotify-mcp-api`
- Use token auth (`Authorization: Bearer <token>`) stored as GPT secret

**Endpoints for Actions:**
- `POST /mcp/call` - Primary tool invocation
- `GET /mcp/tools` - Tool catalog (optional)

**Request format:**
```json
{
  "tool": "history.taste_summary",
  "args": { "days": 90, "user_id": "..." }
}
```

## Testing Strategy

### Unit Tests
- Token encryption/decryption
- Play deduplication logic
- Initial sync paging + stop conditions
- ZIP import normalization + batching
- History queries (90-day windows, date ranges)

### Integration Tests
- Postgres in Docker + API endpoints
- Mock Spotify API via `respx`
- OAuth flow (with mock)
- Collector run loop scenarios
- ZIP import end-to-end

## Development Notes

- **Python-only project** — no package.json, no TypeScript
- **Follow spec.md closely** — comprehensive specification with detailed requirements
- All services use FastAPI, even the frontend (server-rendered with Jinja2 + HTMX recommended)
- Root `pyproject.toml` has unified tool config (ruff, mypy, pytest); per-package pyproject.toml has package metadata + deps
- `environment.yml` uses editable installs (`-e services/shared`, etc.) — pip resolves deps from pyproject.toml automatically
- Docker build context for api/collector is `./services` (so they can COPY the shared package)
- Frontend has no DB dependency — does NOT copy shared package

## Implementation Status

### Completed

#### Phase 1: Foundation
- Database schema (all 11 tables, 6 enums, Alembic migration `001_initial_schema`)
- Shared DB package (`services/shared/`) with DatabaseManager, split models, enums, config
- FastAPI apps (api + frontend) with health endpoints and lifespan
- Collector placeholder (infinite loop waiting for runloop)
- Docker Compose with health checks, all services running on Python 3.14
- Dev tooling: Makefile, pre-commit (ruff + mypy), pip-tools, README

#### Phase 2: OAuth & Token Management
- `services/api/src/app/auth/` — Full Spotify OAuth flow (login, callback, state validation)
- `services/api/src/app/auth/crypto.py` — TokenEncryptor (Fernet encryption, now re-exports from `shared.crypto`)
- `services/api/src/app/auth/tokens.py` — TokenManager (get/refresh access tokens)
- `services/api/src/app/auth/state.py` — OAuthStateManager (HMAC-SHA256 signed CSRF state)
- Tests: `api/tests/test_auth/` — crypto, state, tokens, router (21 tests)

#### Phase 3: Spotify API Client & Basic Data Models
- `services/shared/src/shared/spotify/` — Spotify client package:
  - `client.py` — `SpotifyClient` with retry logic (429/5xx backoff, 401 token-refresh callback, semaphore concurrency). Methods: `get_recently_played()`, `get_tracks()`, `get_artists()`, `get_audio_features()`, `get_top_artists()`, `get_top_tracks()`, `search()`
  - `models.py` — 20+ Pydantic models for all Spotify API responses (tracks, artists, albums, play history, search, audio features, top items, batch endpoints)
  - `exceptions.py` — `SpotifyClientError`, `SpotifyAuthError`, `SpotifyRateLimitError`, `SpotifyServerError`, `SpotifyRequestError`
  - `constants.py` — All Spotify API URLs and retry defaults
- `services/shared/src/shared/crypto.py` — `TokenEncryptor` (moved from api, shared by both services)
- `services/shared/src/shared/db/operations.py` — `MusicRepository` class: `upsert_track()`, `upsert_artist()`, `link_track_artists()`, `insert_play()`, `process_play_history_item()`, `batch_process_play_history()`
- `services/collector/src/collector/settings.py` — `CollectorSettings` (all env vars with defaults)
- `services/collector/src/collector/tokens.py` — `CollectorTokenManager` (get/refresh tokens for collector)
- `services/collector/src/collector/polling.py` — `PollingService.poll_user()` end-to-end polling flow
- `app/spotify/__init__.py` re-exports `SpotifyClient` from shared; `app/constants.py` re-exports `SPOTIFY_TOKEN_URL` from shared
- Tests: `api/tests/test_spotify/` (29 tests), `api/tests/test_db/` (11 tests), `collector/tests/` (9 tests) — total 49 new tests

#### Phase 4: Initial Sync & Collector Run Loop
- `services/collector/src/collector/initial_sync.py` — Backward paging through recently-played with stop conditions
- `services/collector/src/collector/main.py` — Priority-based run loop (ZIP imports → initial sync → polling)
- `services/collector/src/collector/job_tracking.py` — JobRun lifecycle management
- Tests: `collector/tests/` — initial_sync (7), job_tracking (3), runloop (5)

#### Phase 5: ZIP Import Pipeline
- `services/shared/src/shared/zip_import/` — Parser, normalizers, models for Extended + Account Data formats
- `services/collector/src/collector/zip_import.py` — ZipImportService processing pending import jobs
- `services/api/src/app/admin/router.py` — Upload endpoint for ZIP files
- Tests: `api/tests/test_zip_import/` (17), `collector/tests/test_zip_import_service.py` (4), `api/tests/test_admin/` (5)
- Verified with real 18,894-play dataset spanning 10+ years

#### Phase 6: MCP Tool Endpoints & History Queries
- `services/api/src/app/history/` — schemas.py, queries.py, service.py, router.py — 6 history analysis endpoints
- `services/api/src/app/mcp/` — schemas.py, registry.py, router.py — MCP dispatcher with tool catalog
- `services/api/src/app/mcp/tools/` — history_tools.py (6), ops_tools.py (3), spotify_tools.py (2) — 11 total MCP tools
- Alembic migration `002_timestamp_to_timestamptz` — all DateTime columns now TIMESTAMPTZ
- Tests: `api/tests/test_history/` (21), `api/tests/test_mcp/` (18) — 39 new tests
- All 11 MCP tools verified with real data and live Spotify API

#### Phase 7: Admin API & Authentication
- `services/api/src/app/admin/router.py` — 13 admin endpoints: users CRUD, sync control, job runs, import jobs, logs, purge, sync status
- `services/api/src/app/admin/auth.py` — `AdminAuthMiddleware` supporting token and basic auth modes (`ADMIN_AUTH_MODE`)
- `services/api/src/app/admin/schemas.py` — Pydantic request/response models for all admin endpoints
- `services/api/src/app/logging/handler.py` — `DatabaseLogHandler` (async background DB writer with batching)
- `services/api/src/app/logging/middleware.py` — Request logging middleware (structured log entries per request)
- Tests: `api/tests/test_admin/` — auth (11), users (10), operations (10), logs (7), import_upload (5) — 43 new tests
- Total API tests: 171

#### Phase 8: Admin Frontend (in progress)
- `services/frontend/src/frontend/settings.py` — `FrontendSettings(BaseSettings)` with API_BASE_URL, auth config
- `services/frontend/src/frontend/api_client.py` — `AdminApiClient` (httpx.AsyncClient wrapper) with all 13 admin API methods + `ApiError`
- `services/frontend/src/frontend/main.py` — `FrontendApp` class with Jinja2, static files, lifespan, route registration
- `services/frontend/src/frontend/routes/` — 5 route modules: dashboard, users, jobs, imports, logs
- `services/frontend/src/frontend/templates/` — 7 page templates + 8 HTMX partials (Bootstrap 5 + HTMX)
- `services/frontend/src/frontend/static/css/style.css` — Sidebar layout, badge colors, responsive styles
- Pages: Dashboard (sync status + recent activity), Users (list + detail + pause/resume/trigger/delete), Jobs (filtered list), Imports (list + ZIP upload), Logs (filtered + purge)
- Tests: `frontend/tests/` — conftest, test_api_client (19), test_routes (21) — 40 tests
- Total project tests: 239 (API 171 + Collector 28 + Frontend 40)

### Not Yet Implemented
- Analytics page (deferred to post-Phase 9)
- Docker integration testing (frontend ↔ API ↔ DB end-to-end)

### Architecture Notes for Future Phases
- **Shared code pattern**: Code needed by both api and collector goes in `services/shared/`. Both services import from it. Docker build context is `./services` so both can COPY shared.
- **Token management duplication**: `app.auth.tokens.TokenManager` (for API) and `collector.tokens.CollectorTokenManager` (for collector) are intentionally separate to avoid coupling. They share `shared.crypto.TokenEncryptor`.
- **DB datetime convention**: All DB columns use `DateTime(timezone=True)` (PostgreSQL `TIMESTAMPTZ`). Always use `datetime.now(UTC)` for tz-aware UTC datetimes. Do NOT strip tzinfo — all values should be tz-aware. Note: SQLite (used in tests) may return naive datetimes; use `.replace(tzinfo=None)` only in test assertions when comparing against SQLite values.
- **Test isolation**: API and collector tests must be run separately (`pytest services/api/tests/` and `cd services/collector && pytest tests/`) due to conftest BigInteger-SQLite compilation conflicts when run together from root.

### Phase 6 Insights & Lessons Learned

#### Timezone Handling
- **TIMESTAMPTZ from the start**: Starting with naive `TIMESTAMP` and adding `.replace(tzinfo=None)` hacks at every boundary was unsustainable (~30 occurrences by Phase 5). Migrating to `TIMESTAMPTZ` eliminated the entire category of naive-vs-aware bugs. Future projects should use TIMESTAMPTZ from day one.
- **SQLite test gap**: SQLite ignores `DateTime(timezone=True)` entirely — it stores tz-aware datetimes as text and reads them back as naive strings. This means tests using SQLite can miss tz-related bugs that only surface in PostgreSQL. Consider adding a small set of PostgreSQL integration tests (via testcontainers or Docker) for datetime-sensitive code paths.
- **Defensive tz checks in polling.py**: Even with TIMESTAMPTZ, the polling service needs defensive checks (`if dt.tzinfo is None: dt = dt.replace(tzinfo=UTC)`) because SQLite tests produce naive values. This is an acceptable compromise documented with comments.

#### MCP Registry Pattern
- The decorator-based `MCPToolRegistry` with a global singleton works well for 11 tools. Each tool module self-registers at import time via `@registry.register(...)`, and `mcp/tools/__init__.py` imports all modules to trigger registration.
- Tool handlers receive `(args: dict, session: AsyncSession)` — this keeps them testable (pass a test session) and decoupled from HTTP concerns.
- The `/mcp/call` endpoint catches all handler exceptions and wraps them in `MCPCallResponse(success=False, error=...)` rather than raising HTTP errors. This matches MCP protocol semantics where errors are part of the response, not HTTP status codes.

#### History Query Compatibility
- **PostgreSQL vs SQLite for heatmap**: The heatmap query uses `EXTRACT(DOW/HOUR FROM ...)` on PostgreSQL but must fall back to `strftime('%w'/'%H', ...)` for SQLite. Dialect detection via `session.bind.dialect.name` handles this, but it's a maintenance burden. Future queries should consider this pattern if they use DB-specific functions.
- **Query performance**: With ~19k plays, all queries return in <100ms. At scale (millions of plays), the heatmap and coverage queries may benefit from a materialized view or pre-aggregated summary table. The `plays` table already has an index on `(user_id, played_at)` which covers the primary access pattern.

#### Testing Patterns
- **Test factories**: The test suites create sample data (users, tracks, artists, plays) inline in each test file. A shared test factory/fixture module could reduce boilerplate in future phases.
- **MCP tool tests vs history tests**: MCP tools are tested at two levels — direct history service tests (unit) and through the MCP dispatcher (integration). This provides good coverage without over-mocking.

### Pointers for Next Phases

#### Phase 9: Audio Features Enrichment
- The `audio_features` table exists but is unpopulated. `SpotifyClient.get_audio_features()` is implemented.
- Add an enrichment job type to the collector that batch-fetches audio features for tracks missing them.
- This enables future MCP tools like "what's my average danceability?" or "find my most energetic tracks."

#### Phase 10: Local Track Resolution
- ZIP imports without Spotify URIs create local IDs (`local:<sha1>`). These tracks can't be enriched with audio features or linked to real Spotify metadata.
- Implement a resolution job that uses `SpotifyClient.search()` to match local tracks to real Spotify IDs.
- Merge strategy needed: update track IDs, re-link plays, handle duplicates.

#### General
- **Test count**: 239 tests (171 API + 28 collector + 40 frontend). Each new phase should maintain or increase coverage.
- **Pre-commit hooks**: ruff v0.15.0 + mypy strict — all commits must pass. Do not use `--no-verify`.
- **Branch strategy**: Feature branches off main, PRs via `gh pr create`, squash merge.
