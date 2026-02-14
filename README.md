# Spotify MCP History Collector

A containerized system that enables ChatGPT-style assistants to analyze Spotify listening patterns by collecting playback history over time and exposing it via MCP-compatible tool endpoints.

**The core problem:** Spotify's API only provides a limited window of recent playback history (roughly the last 50 tracks). This system solves that by continuously polling to accumulate plays over time, supporting bulk import of Spotify's "Download your data" ZIP exports, and running a best-effort initial sync via API paging -- then exposing all of that data through 11 MCP tool endpoints that any AI assistant can call.

---

## Architecture

Four containerized services work together:

| Service | Tech | Port | Role |
|---|---|---|---|
| **spotify-mcp-api** | FastAPI | 8000 | Spotify OAuth, 11 MCP tool endpoints, 13 admin API endpoints |
| **spotify-history-collector** | Python worker | -- | Polls Spotify API, processes ZIP imports, runs initial sync |
| **admin-frontend** | FastAPI + Jinja2/HTMX | 8001 | Dashboard, Users, Jobs, Imports, Logs management pages |
| **postgres** | PostgreSQL 16 | 5434 (host) | All data storage (11 tables, 6 enums) |

```
                                 +------------------+
                                 |    PostgreSQL     |
                                 |   (11 tables)     |
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
            |             |              |               |
         User         ChatGPT      +----+----+          |
       (browser)     (or any AI)   | frontend |    Spotify API
                                   | :8001    |    (polling, sync,
                                   +----------+     token refresh)
```

**Data flow:**

1. User authorizes Spotify via OAuth (`/auth/login` -> `/auth/callback`)
2. API stores encrypted refresh token and user profile in Postgres
3. Collector runs in priority order: pending ZIP imports -> initial sync -> incremental polling
4. MCP tool endpoints serve history analysis to ChatGPT or other AI clients
5. Admin frontend manages users, monitors sync/import status, and browses logs

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
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
TOKEN_ENCRYPTION_KEY=your_encryption_key_here

# Required -- any secret string for admin API/frontend auth
ADMIN_TOKEN=your_admin_token_here
```

Make sure your Spotify app's redirect URI is set to `http://localhost:8000/auth/callback` in the Spotify Developer Dashboard.

### 2. Start services

```bash
docker-compose up --build -d
```

Services start in dependency order: postgres (health check) -> api (health check) -> collector, frontend.

### 3. Run database migrations

```bash
docker-compose exec api alembic upgrade head
```

### 4. Authorize Spotify

Open [http://localhost:8000/auth/login](http://localhost:8000/auth/login) in your browser and complete the Spotify OAuth flow.

### 5. Open the admin dashboard

Open [http://localhost:8001](http://localhost:8001) to see the admin dashboard. From here you can monitor sync status, manage users, upload ZIP imports, and browse logs.

### 6. Query via MCP tools

Once the collector has gathered some history (it polls every 10 minutes by default), you can invoke MCP tools:

```bash
curl -X POST http://localhost:8000/mcp/call \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"tool": "history.taste_summary", "args": {"days": 90, "user_id": 1}}'
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

### Frontend Settings

| Variable | Default | Description |
|---|---|---|
| `API_BASE_URL` | `http://api:8000` | Internal URL for API (used by frontend container) |
| `FRONTEND_AUTH_MODE` | `token` | Must match `ADMIN_AUTH_MODE` |

---

## MCP Tools

11 tools across 3 categories, all invoked via `POST /mcp/call`:

```json
{
  "tool": "history.taste_summary",
  "args": { "days": 90, "user_id": 1 }
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

### Ops Tools (operational status)

| Tool | Description |
|---|---|
| `ops.sync_status` | Current sync checkpoint state for a user |
| `ops.latest_job_runs` | Recent job execution history |
| `ops.latest_import_jobs` | Recent ZIP import job status |

### ChatGPT Integration

The recommended integration path is **Custom GPT Actions** (OpenAPI over HTTPS):

1. FastAPI auto-generates an OpenAPI spec at `/openapi.json`
2. Configure a Custom GPT Action pointing at your deployed `spotify-mcp-api` instance
3. Use token auth (`Authorization: Bearer <token>`) stored as a GPT secret
4. The primary endpoint is `POST /mcp/call` with the JSON body shown above

---

## Admin API

13 endpoints under `/admin/`, protected by token or basic auth:

- **Users**: list, detail, create, update, delete, pause/resume sync, trigger sync
- **Jobs**: list job runs (filtered by type, user, status)
- **Imports**: list import jobs, upload ZIP file
- **Logs**: list logs (filtered by level, source), purge old entries
- **Status**: sync status overview across all users

---

## Development Setup

### Prerequisites

- [Conda](https://docs.conda.io/en/latest/miniconda.html) (recommended) **or** Python 3.14+ with venv
- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- (Windows) `make` via [Git Bash](https://gitforwindows.org/), [WSL](https://learn.microsoft.com/en-us/windows/wsl/), or [Chocolatey](https://chocolatey.org/) (`choco install make`)

### With Conda (recommended)

```bash
conda env create -f environment.yml
conda activate spotify-mcp
pre-commit install
```

`environment.yml` installs all four packages (`shared`, `api`, `collector`, `frontend`) as editable installs with dev dependencies. pip reads each package's `pyproject.toml` and resolves the full dependency tree automatically.

### Without Conda (venv)

```bash
python -m venv .venv

# Linux/macOS
source .venv/bin/activate

# Windows
.venv\Scripts\activate

make setup
```

`make setup` installs pip-tools, pre-commit, all four packages in editable mode with dev extras, and activates the pre-commit hooks.

### Verify the environment

```bash
# All 11 models should register
python -c "from shared.db import Base; print(len(Base.metadata.tables), 'tables')"

# Lint should pass
make lint

# Type checking
make typecheck
```

### Running services locally

Start Postgres via Docker, then run individual services with an IDE or debugger:

```bash
# Start only Postgres
docker-compose up -d postgres

# Run API locally
cd services/api && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Run collector locally
cd services/collector && python -m collector.main

# Run frontend locally
cd services/frontend && uvicorn frontend.main:app --host 0.0.0.0 --port 8001 --reload
```

### Code quality commands

```bash
make lint          # ruff lint + format check (no changes)
make format        # ruff auto-fix + reformat
make typecheck     # mypy across all packages
make test          # pytest (all tests)
make test-cov      # pytest with HTML coverage report
```

### Pre-commit hooks

Installed during setup. On every `git commit`, the following run automatically:

- **ruff** (v0.15.0) -- lint check with auto-fix + format
- **mypy** -- strict type checking across all source directories

To run manually: `pre-commit run --all-files`

### Dependency management (pip-tools)

Dependencies are defined in each package's `pyproject.toml` (source of truth). Pinned `requirements.txt` files are generated by pip-tools for reproducible Docker builds.

```bash
make compile-deps   # regenerate pinned requirements from pyproject.toml
make upgrade-deps   # upgrade all pins to latest allowed versions
```

### Database migrations

```bash
# Inside container
docker-compose exec api alembic upgrade head

# Locally (requires DATABASE_URL in env or .env)
cd services/api && alembic upgrade head

# Create a new migration
cd services/api && alembic revision --autogenerate -m "description of change"
```

---

## Project Structure

```
services/
├── shared/                        # Shared packages (used by api + collector)
│   └── src/shared/
│       ├── config/                # DatabaseSettings, constants
│       ├── crypto.py              # TokenEncryptor (Fernet encryption)
│       ├── db/                    # Base, enums, DatabaseManager, models/, operations
│       ├── spotify/               # SpotifyClient, Pydantic models, exceptions
│       ├── zip_import/            # Parser, normalizers, models for ZIP formats
│       └── logging/               # Shared logging utilities
├── api/                           # spotify-mcp-api (FastAPI, port 8000)
│   ├── Dockerfile
│   ├── alembic/                   # Database migrations
│   └── src/app/
│       ├── main.py                # FastAPI app with lifespan
│       ├── settings.py            # AppSettings (all env vars)
│       ├── dependencies.py        # DatabaseManager instance
│       ├── middleware.py          # CORS, rate limiting, request logging
│       ├── auth/                  # Spotify OAuth flow (login, callback, tokens, crypto)
│       ├── mcp/                   # MCP tool registry, dispatcher, router
│       │   └── tools/             # 11 tool handlers (history, spotify, ops)
│       ├── admin/                 # Admin API (13 endpoints, auth middleware)
│       ├── history/               # History queries, service, schemas, router
│       ├── spotify/               # Re-exports SpotifyClient from shared
│       └── logging/               # DatabaseLogHandler, request logging middleware
├── collector/                     # spotify-history-collector (Python worker)
│   ├── Dockerfile
│   └── src/collector/
│       ├── main.py                # Priority-based run loop
│       ├── settings.py            # CollectorSettings (all env vars)
│       ├── polling.py             # Incremental polling service
│       ├── initial_sync.py        # Backward-paging initial sync
│       ├── zip_import.py          # ZIP import job processing
│       ├── job_tracking.py        # Job run lifecycle management
│       └── tokens.py              # Token refresh for collector
└── frontend/                      # admin-frontend (FastAPI + Jinja2/HTMX, port 8001)
    ├── Dockerfile
    └── src/frontend/
        ├── main.py                # FrontendApp with Jinja2, static files
        ├── settings.py            # FrontendSettings
        ├── api_client.py          # AdminApiClient (httpx wrapper)
        ├── routes/                # dashboard, users, jobs, imports, logs
        ├── templates/             # 7 page templates + 8 HTMX partials
        └── static/                # CSS (Bootstrap 5 sidebar layout)
```

---

## Testing

239 tests across three test suites:

| Suite | Tests | Command |
|---|---|---|
| API | 171 | `pytest services/api/tests/` |
| Collector | 28 | `cd services/collector && pytest tests/` |
| Frontend | 40 | `pytest services/frontend/tests/` |
| **All** | **239** | `make test` |

**Important:** API and collector tests must be run separately (or via `make test`) due to conftest `BigInteger`-SQLite compilation conflicts when run together from the repository root. The `make test` target handles this correctly.

Test coverage reports are available via:

```bash
make test-cov    # generates HTML coverage report
```

---

## Database Schema

11 tables organized into three groups:

**Core data:**
- `users` -- Spotify user profiles
- `spotify_tokens` -- Encrypted refresh tokens + cached access tokens
- `tracks` -- Track metadata (Spotify IDs + local IDs from ZIP imports)
- `artists` -- Artist metadata
- `track_artists` -- Many-to-many relationship
- `plays` -- Individual play events (unique on `user_id, played_at, track_id`)
- `audio_features` -- Optional enrichment (danceability, energy, etc.)

**Operational:**
- `sync_checkpoints` -- Per-user sync state
- `job_runs` -- Job execution history (import_zip, initial_sync, poll, enrich)
- `import_jobs` -- ZIP upload/ingestion tracking

**Observability:**
- `logs` -- Structured log events for UI browsing (with configurable retention)

---

## How the Collector Works

The collector runs a continuous loop with a configurable interval (default: 10 minutes) and processes work in priority order:

1. **ZIP imports** -- Process any pending `import_jobs` first (bulk historical data)
2. **Initial sync** -- Backward-page through Spotify's recently-played API for users that haven't completed initial sync
3. **Incremental polling** -- Fetch new plays for all active users

**ZIP import support:** Upload Spotify's "Download your data" exports (Extended Streaming History) through the admin frontend or API. The system handles both `endsong_*.json` and `StreamingHistory*.json` formats with streaming JSON parsing, batch transactions, and safety caps on file size and record count.

**Initial sync strategy:** Pages backward through `/me/player/recently-played` using the `before` parameter, stopping when it hits an empty batch, no progress, the configured day limit, or the request cap.

**Play deduplication:** All plays are deduped via a unique constraint on `(user_id, played_at, track_id)`, so overlapping imports and polling never create duplicates.

---

## Health Checks

```bash
curl http://localhost:8000/healthz   # API
curl http://localhost:8001/healthz   # Frontend
```

Both return `200 OK` with a JSON body when healthy. Docker Compose uses these for dependency ordering and restart policies.

---

## Key Technical Decisions

- **Python 3.14** -- PEP 649 lazy annotation evaluation is the default; no `from __future__ import annotations` needed
- **Async everywhere** -- `asyncpg` + SQLAlchemy 2.0 async sessions, `httpx.AsyncClient` for all HTTP
- **Pydantic v2** for all request/response models and settings
- **Tokens encrypted at rest** using Fernet symmetric encryption
- **Deterministic local track IDs** for ZIP imports without Spotify URIs: `local:<sha1(artist|track|album)>`
- **Database-first design** -- all sync state, job history, and logs stored in Postgres (no external queues or caches)
- **Strict type checking** -- mypy strict mode, complete type hints, `StrEnum` for all enumerations

---

## License

See [LICENSE](LICENSE).
