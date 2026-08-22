# Spotify MCP History Collector

A containerized system that enables ChatGPT-style assistants to analyze Spotify listening patterns, manage AI-created playlists, and maintain a persistent music taste profile — all backed by a continuously-collected playback history.

**The core problem:** Spotify's API only provides a limited window of recent playback history (roughly the last 50 tracks). This system solves that by continuously polling to accumulate plays over time, supporting bulk import of Spotify's "Download your data" ZIP exports, and running a best-effort initial sync via API paging — then exposing all of that data through 34 MCP tool endpoints that any AI assistant can call.

---

## Architecture

Five containerized services work together:

| Service | Tech | Port | Role |
|---|---|---|---|
| **spotify-mcp-api** | FastAPI | 8000 | Spotify OAuth, 34 MCP tool endpoints, admin API, cache |
| **spotify-history-collector** | Python worker | -- | Polls Spotify API, processes ZIP imports, runs initial sync |
| **admin-frontend** | FastAPI + Jinja2/HTMX | 8001 | Admin dashboard: users, jobs, imports, logs, settings |
| **explorer** | FastAPI + Jinja2/HTMX | 8002 | User-facing music history browser with JWT auth |
| **postgres** | PostgreSQL 16 | 5434 (host) | All data storage (24 tables) |

```
                                 +------------------+
                                 |    PostgreSQL     |
                                 |   (24 tables)     |
                                 +--------+---------+
                                          |
                          +---------------+---------------+
                          |                               |
                  +-------+--------+             +--------+-------+
                  | spotify-mcp-api|             |   collector    |
                  |   (FastAPI)    |             | (Python worker)|
                  +--+----+----+--+             +--------+-------+
                     |    |    |                         |
            +--------+    |    +---------+               |
            |             |              |               |
    +-------+---+  +------+------+  +---+--------+      |
    | /auth/*   |  | /mcp/call   |  | /admin/*   |      |
    | OAuth flow|  | Tool invoke |  | Management |      |
    +-------+---+  +------+------+  +---+--------+      |
            ^             ^              ^               |
            |             |              |         Spotify API
         User         ChatGPT      +----+----+    (polling, sync,
       (browser)     (or any AI)   | frontend |    token refresh)
                                   | :8001    |
                                   +----------+
                                   +----------+
                                   | explorer |
                                   | :8002    |
                                   +----------+
                                        ^
                                     User
                                   (browser,
                                   JWT auth)
```

**Data flow:**

1. User authorizes Spotify via OAuth (`/auth/login` -> `/auth/callback`)
2. API stores encrypted refresh token and user profile in Postgres
3. Collector runs in priority order: pending ZIP imports -> initial sync -> incremental polling
4. MCP tool endpoints serve history analysis and memory operations to ChatGPT or other AI clients
5. Admin frontend manages users, monitors sync/import status, and browses logs
6. Explorer lets users browse their own listening history, taste profile, and AI-created playlists

---

## Quick Start (5 minutes)

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- A [Spotify Developer](https://developer.spotify.com/dashboard) application (for client ID and secret)

### 1. Clone and configure

```bash
git clone https://github.com/gmyuval/spotify-mcp-history-collector.git
cd spotify-mcp-history-collector
cp .env.example .env
```

Edit `.env` and fill in the required values:

```bash
# Required -- from https://developer.spotify.com/dashboard
SPOTIFY_CLIENT_ID=your_client_id_here
SPOTIFY_CLIENT_SECRET=your_client_secret_here

# Required -- generate with:
#   uv run --locked python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
TOKEN_ENCRYPTION_KEY=your_encryption_key_here

# Required -- any secret string for admin API/frontend auth
ADMIN_TOKEN=your_admin_token_here

# Required -- generate with: uv run --locked python -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET_KEY=your_jwt_secret_here
```

Make sure your Spotify app's redirect URI includes `http://localhost:8000/auth/callback`.

### 2. Start services

```bash
docker-compose up --build -d
```

Services start in dependency order: postgres (health check) -> api (health check) -> collector, frontend, explorer.

### 3. Run database migrations

```bash
docker-compose exec api alembic upgrade head
```

### 4. Authorize Spotify

Open [http://localhost:8000/auth/login](http://localhost:8000/auth/login) in your browser and complete the Spotify OAuth flow.

### 5. Open the admin dashboard

Open [http://localhost:8001](http://localhost:8001) to monitor sync status, manage users, upload ZIP imports, browse logs, and configure settings.

### 6. Open the user explorer

Open [http://localhost:8002](http://localhost:8002) to browse your listening history, taste profile, and AI-created playlists.

### 7. Query via MCP tools

Once the collector has gathered some history (polls every 10 minutes by default):

```bash
curl -X POST http://localhost:8000/mcp/call \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"tool": "history.taste_summary", "days": 90, "user_id": 1}'
```

---

## Configuration Reference

All configuration is via environment variables. Copy `.env.example` to `.env` and adjust as needed.

### Database

| Variable | Default | Description |
|---|---|---|
| `POSTGRES_PASSWORD` | `postgres` | PostgreSQL password |

### Spotify OAuth (API + Collector)

| Variable | Default | Description |
|---|---|---|
| `SPOTIFY_CLIENT_ID` | *(required)* | From Spotify Developer Dashboard |
| `SPOTIFY_CLIENT_SECRET` | *(required)* | From Spotify Developer Dashboard |
| `SPOTIFY_REDIRECT_URI` | `http://localhost:8000/auth/callback` | OAuth callback URL |

### Security

| Variable | Default | Description |
|---|---|---|
| `TOKEN_ENCRYPTION_KEY` | *(required)* | Fernet key for encrypting refresh tokens at rest |
| `JWT_SECRET_KEY` | *(required)* | HMAC secret for signing JWT access tokens (explorer auth) |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | Explorer JWT access token TTL |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Explorer JWT refresh token TTL |
| `ADMIN_AUTH_MODE` | `token` | Admin auth method: `token` or `basic` |
| `ADMIN_TOKEN` | *(required if token mode)* | Bearer token for admin API access |
| `ADMIN_USERNAME` | -- | Username for basic auth mode |
| `ADMIN_PASSWORD` | -- | Password for basic auth mode |

### API Settings

| Variable | Default | Description |
|---|---|---|
| `CORS_ALLOWED_ORIGINS` | `http://localhost:8001` | Comma-separated allowed CORS origins |
| `RATE_LIMIT_AUTH_PER_MINUTE` | `10` | Rate limit on auth endpoints |
| `RATE_LIMIT_MCP_PER_MINUTE` | `60` | Rate limit on MCP tool calls |
| `LOG_RETENTION_DAYS` | `30` | Days to retain structured log entries |

### Collector Settings

| Variable | Default | Description |
|---|---|---|
| `COLLECTOR_INTERVAL_SECONDS` | `600` | Seconds between polling cycles (10 minutes) |
| `INITIAL_SYNC_ENABLED` | `true` | Enable backward-paging initial sync |
| `INITIAL_SYNC_MAX_DAYS` | `30` | Maximum days to page back during initial sync |
| `INITIAL_SYNC_MAX_REQUESTS` | `200` | Maximum API requests per initial sync |
| `INITIAL_SYNC_CONCURRENCY` | `2` | Concurrent users for initial sync |
| `IMPORT_MAX_ZIP_SIZE_MB` | `500` | Maximum ZIP file size for imports |
| `IMPORT_MAX_RECORDS` | `5000000` | Maximum records per ZIP import |

### Frontend / Explorer Settings

| Variable | Default | Description |
|---|---|---|
| `API_BASE_URL` | `http://api:8000` | Internal Docker URL for API (used by frontend/explorer containers) |
| `API_PUBLIC_URL` | `http://localhost:8000` | Browser-facing API URL (used by explorer for OAuth redirects) |
| `FRONTEND_AUTH_MODE` | `token` | Must match `ADMIN_AUTH_MODE` |

---

## MCP Tools

34 tools across 5 categories, all invoked via `POST /mcp/call` with flat parameters:

```json
{
  "tool": "history.taste_summary",
  "days": 90,
  "user_id": 1
}
```

The tool catalog is available at `GET /mcp/tools`.

### History Tools (database-backed analysis)

| Tool | Description |
|---|---|
| `history.taste_summary` | Top artists, tracks, genres, listening stats over N days |
| `history.top_artists` | Top artists by play count with configurable limit |
| `history.top_tracks` | Top tracks by play count with configurable limit |
| `history.listening_heatmap` | Play counts by weekday and hour |
| `history.repeat_rate` | Track repeat statistics and one-hit plays |
| `history.coverage` | Data completeness metrics (days covered, gaps, sources) |

### Spotify Live Tools (real-time API calls)

| Tool | Description |
|---|---|
| `spotify.get_top` | Spotify's native "top items" API (short/medium/long term) |
| `spotify.search` | Search Spotify for tracks, artists, or albums |
| `spotify.get_track` | Detailed track info (artists, album, duration, popularity) |
| `spotify.get_artist` | Detailed artist info (genres, popularity, followers) |
| `spotify.get_album` | Album details with full track listing |
| `spotify.list_playlists` | List user's Spotify playlists |
| `spotify.get_playlist` | Playlist details with full track listing (all pages) |
| `spotify.create_playlist` | Create a new Spotify playlist |
| `spotify.add_tracks` | Add tracks to a playlist (max 100, accepts IDs or URIs) |
| `spotify.remove_tracks` | Remove tracks from a playlist (max 100) |
| `spotify.update_playlist` | Update playlist name, description, or visibility |

### Memory Tools (persistent AI memory)

| Tool | Description |
|---|---|
| `memory.log_preference` | Record a like/dislike/rule/feedback/note preference event |
| `memory.get_taste_profile` | Retrieve the user's taste profile (genres, artists, moods, rules) |
| `memory.update_taste_profile` | Merge-patch the taste profile (shallow merge) |
| `memory.clear_profile` | Reset taste profile to empty; optionally clear preference events |
| `memory.log_playlist_create` | Create an AI-managed playlist in the ledger |
| `memory.log_playlist_mutation` | Record a track add/remove/reorder mutation |
| `memory.get_playlists` | List AI-managed playlists with pagination |
| `memory.get_playlist` | Get playlist state with full event history |
| `memory.reconstruct_playlist` | Replay mutations from a snapshot to a target version |
| `memory.backfill_playlist` | Sync an existing Spotify playlist into the ledger |
| `memory.search` | Full-text search across playlists, preference events, and taste profile |
| `memory.export_user_data` | Export all user memory data as structured JSON |
| `memory.delete_user_data` | Delete all user memory data (irreversible) |

### Ops Tools (operational status)

| Tool | Description |
|---|---|
| `ops.list_users` | List all registered users |
| `ops.sync_status` | Current sync checkpoint state for a user |
| `ops.latest_job_runs` | Recent job execution history |
| `ops.latest_import_jobs` | Recent ZIP import job status |

### ChatGPT Integration

The recommended integration path is **Custom GPT Actions** (OpenAPI over HTTPS):

1. Deploy the API to a public HTTPS endpoint
2. Configure a Custom GPT Action using `docs/chatgpt-openapi.json` as the schema
3. Use token auth (`Authorization: Bearer <token>`) stored as a GPT secret
4. Follow the setup guide in `docs/chatgpt-gpt-setup.md`
5. Upload `docs/chatgpt-tool-catalog.md` as a GPT knowledge document

The API accepts flat parameters (all at the top level alongside `tool`) for ChatGPT compatibility.

---

## Admin API

Endpoints under `/admin/`, protected by token or basic auth:

- **Users**: list, detail, create, update, delete, pause/resume sync, trigger sync
- **Jobs**: list job runs (filtered by type, user, status)
- **Imports**: list import jobs, upload ZIP file
- **Logs**: list logs (filtered by level, source), purge old entries
- **Status**: sync status overview across all users
- **Settings**: list/get/update/reset admin-configurable tunables (search weights, page sizes, etc.)

Admin-configurable settings cover search relevance weights, result limits, and playlist pagination — all adjustable at runtime without restarting services.

---

## Development Setup

### Prerequisites

- [uv 0.12.3](https://docs.astral.sh/uv/getting-started/installation/)
- [Docker](https://docs.docker.com/get-docker/) and Docker Compose

Install the repository-pinned uv release if it is not already available:

```bash
# Linux/macOS
curl -LsSf https://astral.sh/uv/0.12.3/install.sh | sh
```

```powershell
# Windows PowerShell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/0.12.3/install.ps1 | iex"
```

From the repository root, one locked command provisions Python 3.14.7, all five workspace packages,
and development/test tooling:

```bash
uv sync --locked --all-packages --all-extras --all-groups
uv run --locked pre-commit install
```

The project rejects a different uv release through `tool.uv.required-version`, selects Python from
`.python-version`, and fails if package metadata and `uv.lock` disagree. Activating `.venv` is not
required. `make setup` is an optional alias for the same commands on systems with Make.

### Running services locally

```bash
# Start only Postgres
docker-compose up -d postgres

# Run API locally
uv run --locked uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Run collector locally
uv run --locked python -m collector.main

# Run admin frontend locally
uv run --locked uvicorn frontend.main:app --host 0.0.0.0 --port 8001 --reload

# Run explorer locally
uv run --locked uvicorn explorer.main:app --host 0.0.0.0 --port 8002 --reload
```

### Code quality commands

```bash
uv lock --check
uv run --locked python scripts/validate_uv_workflow.py
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy services/shared/src services/api/src services/collector/src services/frontend/src services/explorer/src
uv run --locked pre-commit run --all-files

# Keep package suites isolated so their fixtures cannot collide.
uv run --locked pytest services/shared/tests/
uv run --locked pytest services/api/tests/
uv run --locked pytest services/collector/tests/
uv run --locked pytest services/frontend/tests/
uv run --locked pytest services/explorer/tests/
```

### Pre-commit hooks

Installed during setup. On every `git commit`, the following run automatically:

- **ruff** (v0.15.0) -- lint check with auto-fix + format
- **mypy** -- strict type checking across all source directories

To run manually: `uv run --locked pre-commit run --all-files`

### Dependency management

The root uv workspace and the five package `pyproject.toml` files are the development and CI source
of truth. `uv.lock` is committed and cross-platform.

```bash
uv lock             # intentionally update uv.lock
uv lock --check     # fail if metadata and uv.lock drift
```

Production images temporarily continue to install the committed pip-tools `requirements*.txt`
files. SPM-4 will decide whether images later consume `uv.lock` or pip-compatible exports derived
from it. Until that decision, do not widen Docker build contexts or point Docker/deploy at
`uv.lock`. Keep the temporary requirements path synchronized and checked with:

```bash
uv run --locked python scripts/compile_docker_requirements.py
uv run --locked python scripts/compile_docker_requirements.py --check
```

### Database migrations

```bash
# Inside container
docker-compose exec api alembic upgrade head

# Locally (requires DATABASE_URL in env or .env)
uv --directory services/api run --locked alembic upgrade head

# Create a new migration
uv --directory services/api run --locked alembic revision --autogenerate -m "description of change"
```

---

## Project Structure

```
services/
├── shared/                        # Shared packages (used by api + collector)
│   └── src/shared/
│       ├── config/                # DatabaseSettings, constants
│       ├── crypto.py              # TokenEncryptor (Fernet encryption)
│       ├── db/                    # Base, enums, DatabaseManager, models/, search.py
│       ├── spotify/               # SpotifyClient, Pydantic models, exceptions
│       ├── zip_import/            # Parser, normalizers, models for ZIP formats
│       └── logging/               # Shared logging utilities
├── api/                           # spotify-mcp-api (FastAPI, port 8000)
│   ├── Dockerfile
│   ├── alembic/                   # Database migrations (9 revisions)
│   └── src/app/
│       ├── main.py                # FastAPI app with lifespan
│       ├── settings.py            # AppSettings (all env vars)
│       ├── dependencies.py        # DatabaseManager instance
│       ├── middleware.py          # CORS, rate limiting, request logging
│       ├── auth/                  # Spotify OAuth, JWT service, token management
│       ├── mcp/                   # MCP tool registry, dispatcher, router
│       │   └── tools/             # 34 tool handlers across 5 modules
│       ├── admin/                 # Admin API (auth, users, jobs, settings)
│       ├── explorer/              # Explorer API endpoints (/api/me/*)
│       ├── history/               # History queries, service, schemas
│       ├── spotify/               # Re-exports SpotifyClient from shared
│       └── logging/               # DatabaseLogHandler, request logging middleware
├── collector/                     # spotify-history-collector (Python worker)
│   ├── Dockerfile
│   └── src/collector/
│       ├── main.py                # Priority-based run loop
│       ├── settings.py            # CollectorSettings
│       ├── polling.py             # Incremental polling service
│       ├── initial_sync.py        # Backward-paging initial sync
│       ├── zip_import.py          # ZIP import job processing
│       ├── job_tracking.py        # Job run lifecycle management
│       └── tokens.py              # Token refresh for collector
├── frontend/                      # admin-frontend (FastAPI + Jinja2/HTMX, port 8001)
│   ├── Dockerfile
│   └── src/frontend/
│       ├── main.py                # FrontendApp with Jinja2, static files
│       ├── settings.py            # FrontendSettings
│       ├── api_client.py          # AdminApiClient (httpx wrapper)
│       ├── routes/                # dashboard, users, jobs, imports, logs, settings
│       └── templates/             # Page templates + HTMX partials
└── explorer/                      # explorer (FastAPI + Jinja2/HTMX, port 8002)
    ├── Dockerfile
    └── src/explorer/
        ├── main.py                # ExplorerApp with JWT auth middleware
        ├── settings.py            # ExplorerSettings
        ├── api_client.py          # ExplorerApiClient (httpx wrapper)
        └── routes/                # dashboard, history, taste, playlists, memory playlists
```

---

## Testing

The current branch collects 870 package tests plus 23 dependency-free agent-contract tests. The
package total is the measured pytest collection; it supersedes the earlier 874-function static
orientation count.

| Suite | Tests | Command |
|---|---|---|
| Shared | 24 | `uv run --locked pytest services/shared/tests/` |
| API | 625 (618 unit + 7 integration) | `uv run --locked pytest services/api/tests/` |
| Collector | 53 | `uv run --locked pytest services/collector/tests/` |
| Admin Frontend | 66 | `uv run --locked pytest services/frontend/tests/` |
| Explorer | 102 | `uv run --locked pytest services/explorer/tests/` |
| Agent contract | 23 | `uv run --locked python -m unittest discover -s tests/contracts -p "test_*.py"` |
| **All package suites** | **870** | `make test` |

**Important:** Run package suites separately (or via `make test`) because their fixtures can
conflict when collected together from the repository root. `make check` adds the agent-contract,
lock-drift, quality, pre-commit, Docker-requirement, and Compose configuration gates.

Integration tests (marked `@pytest.mark.integration`) require a live PostgreSQL instance and are skipped by default.

---

## Database Schema

24 tables across six groups:

**Core music data:**
- `users` -- Spotify user profiles and credentials
- `spotify_tokens` -- Encrypted refresh tokens + cached access tokens
- `tracks` -- Track metadata (Spotify IDs + local IDs from ZIP imports)
- `artists` -- Artist metadata
- `track_artists` -- Many-to-many relationship
- `plays` -- Individual play events (unique on `user_id, played_at, track_id`)
- `audio_features` -- Optional enrichment (danceability, energy, etc.)

**Spotify cache:**
- `cached_playlists` -- Cached playlist metadata and tracks
- `cached_playlist_tracks` -- Per-track rows for playlist cache
- `spotify_entity_cache` -- General-purpose entity cache (tracks, artists, albums)

**AI memory:**
- `taste_profiles` -- Per-user taste profile (JSONB, versioned)
- `preference_events` -- Append-only preference log (like/dislike/rule/feedback/note)
- `memory_playlists` -- AI-managed playlist registry
- `playlist_snapshots` -- Point-in-time snapshots of playlist state
- `playlist_events` -- Ordered mutation log (add/remove/reorder)

**Access control:**
- `permissions` -- Named permission strings
- `roles` -- User roles (admin, user, etc.)
- `role_permissions` -- Role-to-permission assignments
- `user_roles` -- User-to-role assignments

**Operational:**
- `sync_checkpoints` -- Per-user sync state
- `job_runs` -- Job execution history (import_zip, initial_sync, poll, enrich)
- `import_jobs` -- ZIP upload/ingestion tracking

**Configuration & observability:**
- `app_settings` -- Admin-configurable runtime tunables
- `logs` -- Structured log events for UI browsing (with configurable retention)

---

## How the Collector Works

The collector runs a continuous loop with a configurable interval (default: 10 minutes) and processes work in priority order:

1. **ZIP imports** -- Process any pending `import_jobs` first (bulk historical data)
2. **Initial sync** -- Backward-page through Spotify's recently-played API for users that haven't completed initial sync
3. **Incremental polling** -- Fetch new plays for all active users

**ZIP import support:** Upload Spotify's "Download your data" exports (Extended Streaming History) through the admin frontend or API. Handles both `endsong_*.json` and `StreamingHistory*.json` formats with streaming JSON parsing, batch transactions, and safety caps on file size and record count.

**Initial sync strategy:** Pages backward through `/me/player/recently-played` using the `before` parameter, stopping when it hits an empty batch, no progress, the configured day limit, or the request cap.

**Play deduplication:** All plays are deduped via a unique constraint on `(user_id, played_at, track_id)`, so overlapping imports and polling never create duplicates.

---

## Health Checks

```bash
curl http://localhost:8000/healthz   # API
curl http://localhost:8001/healthz   # Admin frontend
curl http://localhost:8002/healthz   # Explorer
```

All return `200 OK` with a JSON body when healthy. Docker Compose uses these for dependency ordering and restart policies.

---

## Key Technical Decisions

- **Python 3.14** -- PEP 649 lazy annotation evaluation is the default; no `from __future__ import annotations` needed
- **Async everywhere** -- `asyncpg` + SQLAlchemy 2.0 async sessions, `httpx.AsyncClient` for all HTTP
- **Pydantic v2** for all request/response models and settings
- **Tokens encrypted at rest** using Fernet symmetric encryption; JWT auth via HS256
- **Deterministic local track IDs** for ZIP imports without Spotify URIs: `local:<sha1(artist|track|album)>`
- **Database-first design** -- all sync state, job history, memory, and logs stored in Postgres (no external queues or caches)
- **In-process TTL cache** for admin settings (5-minute TTL per key, per worker); settings are runtime-configurable without restart
- **Strict type checking** -- mypy strict mode, complete type hints, `StrEnum` for all enumerations

---

## License

See [LICENSE](LICENSE).
