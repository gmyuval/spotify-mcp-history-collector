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
│       ├── auth/              # Spotify OAuth flow
│       ├── mcp/               # MCP tool catalog + dispatcher
│       ├── admin/             # Admin API endpoints + auth middleware
│       ├── history/           # History queries + analysis
│       ├── spotify/           # Typed Spotify client wrapper
│       ├── db/                # Re-exports from shared
│       └── logging/           # DB log sink + request middleware
├── collector/                 # spotify-history-collector (worker)
│   ├── Dockerfile
│   └── src/collector/
│       └── main.py            # Priority-based run loop
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
- `spotify.get_track(track_id, user_id)` - Detailed track info (artists, album, duration, popularity)
- `spotify.get_artist(artist_id, user_id)` - Detailed artist info (genres, popularity, followers)
- `spotify.get_album(album_id, user_id)` - Album details with full track listing
- `spotify.list_playlists(limit, user_id)` - List user's Spotify playlists
- `spotify.get_playlist(playlist_id, user_id)` - Playlist details with tracks

### Ops Tools
- `ops.list_users()` - List all registered users
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

Custom GPT Actions (OpenAPI over HTTPS) with Bearer token auth.

- `POST /mcp/call` — Primary tool invocation (all params flat alongside `tool`)
- `GET /mcp/tools` — Tool catalog (requires Bearer token)
- OpenAPI schema: `docs/chatgpt-openapi.json` (flat params, no nested `arguments`)
- GPT setup guide: `docs/chatgpt-gpt-setup.md`
- The server normalizes all arg formats (flat, nested `arguments`, legacy `args`)
- `search_type` field is aliased to `type` for JSON Schema compatibility

**Request format (flat params — required for ChatGPT compatibility):**
```json
{
  "tool": "history.taste_summary",
  "user_id": 1,
  "days": 90
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

All core features are complete and deployed to production. 12 MCP tools, 175+ API tests, 28 collector tests, 40 frontend tests.

CI/CD via GitHub Actions: tests gate all deploys, manual dispatch supports branch deploys for testing.

### Architecture Notes
- **Shared code pattern**: Code needed by both api and collector goes in `services/shared/`. Docker build context is `./services` so both can COPY shared.
- **Token management**: `app.auth.tokens.TokenManager` (API) and `collector.tokens.CollectorTokenManager` (collector) are intentionally separate. They share `shared.crypto.TokenEncryptor`.
- **DB datetimes**: All columns use `DateTime(timezone=True)` (`TIMESTAMPTZ`). Always use `datetime.now(UTC)`. SQLite (tests) returns naive datetimes — use `.replace(tzinfo=None)` only in test assertions.
- **Test isolation**: API and collector tests must be run separately (`pytest services/api/tests/` and `cd services/collector && pytest tests/`) due to conftest BigInteger-SQLite compilation conflicts.
- **PostgreSQL vs SQLite**: Heatmap query uses `EXTRACT(DOW/HOUR)` on PostgreSQL, `strftime` on SQLite. Dialect detection via `session.bind.dialect.name`.
- **MCP registry**: Decorator-based `MCPToolRegistry` singleton. Tool modules self-register at import. Handlers receive `(args: dict, session: AsyncSession)`.

### Future Work
- **Audio Features Enrichment**: `audio_features` table exists but is unpopulated. `SpotifyClient.get_audio_features()` is ready. Add enrichment job to collector.
- **Local Track Resolution**: ZIP imports without Spotify URIs use `local:<sha1>` IDs. Implement resolution via `SpotifyClient.search()`.
- **Analytics page**: Deferred.
- **Docker integration testing**: Frontend ↔ API ↔ DB end-to-end.
