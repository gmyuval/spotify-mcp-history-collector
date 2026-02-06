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

## Commands

### Environment Setup
```bash
# Create conda environment
conda env create -f environment.yml
conda activate spotify-mcp

# Install dependencies
pip install -r requirements.txt -r requirements-dev.txt
```

### Database
```bash
# Run migrations (from services/api/ directory)
alembic upgrade head

# Create new migration
alembic revision --autogenerate -m "description"

# Rollback migration
alembic downgrade -1
```

### Development
```bash
# Start all services
docker-compose up

# Start specific service
docker-compose up api
docker-compose up collector
docker-compose up frontend

# Run with rebuild
docker-compose up --build

# View logs
docker-compose logs -f api
docker-compose logs -f collector
```

### Testing
```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_file.py

# Run with coverage
pytest --cov=src --cov-report=html

# Run type checking
mypy src/
```

### Linting
```bash
# Run linters (configuration in pyproject.toml)
ruff check .
ruff format .
```

## Repository Structure (Planned)

```
services/
├── api/                    # spotify-mcp-api
│   ├── src/app/
│   │   ├── auth/          # Spotify OAuth flow
│   │   ├── mcp/           # MCP tool catalog + dispatcher
│   │   ├── admin/         # Admin API endpoints
│   │   ├── history/       # History queries + analysis
│   │   ├── spotify/       # Typed Spotify client wrapper
│   │   ├── db/            # SQLAlchemy models + Alembic
│   │   └── logging/       # DB log sink helpers
│   └── tests/
├── collector/              # spotify-history-collector
│   ├── src/collector/
│   │   ├── runloop.py     # Main collector loop
│   │   ├── import_zip.py  # ZIP import processing
│   │   ├── initial_sync.py # Best-effort API backfill
│   │   ├── polling.py     # Incremental polling
│   │   └── spotify_client.py # Spotify API client
│   └── tests/
└── frontend/               # admin-frontend
    ├── src/frontend/
    │   ├── templates/     # Jinja2 templates
    │   └── static/        # CSS/JS
    └── tests/
```

## Key Technical Decisions

### Type Safety
- **Python 3.14** required (as specified in spec.md)
- Complete type hints everywhere (`from __future__ import annotations`)
- Strict mypy configuration:
  - `disallow_untyped_defs = True`
  - `warn_return_any = True`
  - `no_implicit_optional = True`
- Pydantic v2 for all request/response models

### Security
- Refresh tokens encrypted at rest using `TOKEN_ENCRYPTION_KEY`
- Never store raw refresh tokens in database
- Never expose refresh tokens or PII in MCP tool outputs
- ZIP imports strip sensitive fields (IP, user agent) by default

### Database (PostgreSQL + SQLAlchemy 2.0)
- Async operations with `asyncpg`
- Session context manager pattern
- Alembic for migrations

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

- **No package.json exists yet** - This is a Python-only project, TypeScript references in the /init command are not applicable
- **Repository is at initial commit stage** - Directory structure from spec.md needs to be created
- **Follow spec.md closely** - It's a comprehensive specification with detailed requirements
- When implementing, create the `services/` directory structure as outlined in spec.md Section 9
- All services use FastAPI, even the frontend (server-rendered with Jinja2 + HTMX recommended)
