# Implementation Plan: Spotify MCP History Collector

## Execution Workflow

**After each phase completion:**
1. All phase tasks will be implemented
2. Tests will be run to verify everything works
3. A summary of the work completed will be presented
4. Changes will be committed with the specified commit message
5. Move to the next phase

---

## Context

This is a greenfield implementation of a complete Spotify playback history collection and analysis system. The project enables ChatGPT-style assistants to analyze listening patterns by continuously collecting Spotify playback data and exposing it via MCP-compatible tool endpoints.

**Why this is needed:**
- Spotify's Web API only provides limited recent history (typically last 50 plays)
- Long-term analysis (90+ days) requires continuous collection over time
- Users need their complete listening history accessible to AI assistants

**Goal:** Build a production-ready, fully-typed, containerized Python system following the detailed specification in spec.md.

---

## Phase Completion Status

| Phase | Description | Status | PR |
|-------|-------------|--------|-----|
| 1 | Project Bootstrap & Database Foundation | **DONE** | #1 |
| 2 | Spotify OAuth & Token Management | **DONE** | #2 |
| 3 | Spotify API Client & Basic Data Models | **DONE** | #3 |
| 4 | Initial Sync & Collector Run Loop | **DONE** | #4 |
| 5 | ZIP Import System | **DONE** | #5 |
| 6 | MCP Tool Endpoints & History Queries + TIMESTAMPTZ | **DONE** | #6 |
| 7 | Admin API & Authentication | **DONE** | #7 |
| 8 | Admin Frontend | **DONE** | #8 |
| 9 | Production Readiness & Documentation | **IN PROGRESS** | — |

**Note:** The original plan had 9 phases but the actual execution differed:
- Original Phase 6 (Collector Worker) was absorbed into Phase 4 (run loop, main.py) and Phase 5 (ZIP import integration). However, the admin user-management endpoints planned in original Phase 6 were deferred.
- Original Phase 7 (MCP Tools) was executed as our Phase 6, combined with a TIMESTAMPTZ migration.
- Original Phases 8–9 remain. The scope has been reorganized below into 3 remaining phases (7–9).

---

## Implementation Phases (Completed)

### Phase 1: Project Bootstrap & Database Foundation

**Objective:** Set up project structure, Docker environment, and complete database schema with migrations.

**Tasks:**
1. Create directory structure:
   - `services/api/`, `services/collector/`, `services/frontend/`
   - Each with `src/`, `tests/`, `Dockerfile`, `pyproject.toml`
2. Set up `pyproject.toml` for each service with:
   - FastAPI, SQLAlchemy 2.0, asyncpg, Alembic
   - httpx, pydantic v2, cryptography
   - Dev dependencies: pytest, pytest-asyncio, pytest-cov, mypy, ruff, respx
3. Create `docker-compose.yml`:
   - postgres service with healthcheck
   - api, collector, frontend services (depends_on postgres)
   - shared volume for ZIP uploads
   - network configuration
4. Populate `requirements.txt` and `requirements-dev.txt` from pyproject.toml files
5. Create `.env.example` with all required environment variables
6. Implement complete database schema in `services/api/src/app/db/models.py`:
   - All tables from spec.md Section 6 (users, spotify_tokens, tracks, artists, track_artists, plays, audio_features, sync_checkpoints, job_runs, import_jobs, logs)
   - Proper indexes, foreign keys, unique constraints
   - Type hints for all columns
7. Set up Alembic in `services/api/`:
   - `alembic.ini` configuration
   - Initial migration with complete schema
   - Database session factory with async context manager
8. Create shared database utilities:
   - Connection management
   - Session factory
   - Base model classes

**Definition of Done:**
- ✅ All directory structure created per spec.md Section 9
- ✅ Docker compose starts all services successfully
- ✅ Alembic migrations run without errors: `alembic upgrade head`
- ✅ All tables exist in Postgres with correct schema
- ✅ Can connect to database from all services
- ✅ `mypy services/api/src` passes with strict settings

**Testing:**
```bash
# Start postgres
docker-compose up postgres -d
# Run migrations from api service
cd services/api
alembic upgrade head
# Verify tables
docker-compose exec postgres psql -U postgres -d spotify_mcp -c "\dt"
# Should show all 11 tables
```

**Commit Message:**
```
feat: bootstrap project with Docker setup and complete database schema

- Add Docker Compose configuration for all services
- Implement complete PostgreSQL schema with SQLAlchemy models
- Set up Alembic migrations framework
- Add development dependencies (pytest, mypy, ruff)
- Create .env.example with all configuration variables

All tables: users, spotify_tokens, tracks, artists, track_artists,
plays, audio_features, sync_checkpoints, job_runs, import_jobs, logs
```

---

### Phase 2: Spotify OAuth & Token Management

**Objective:** Implement complete OAuth flow, token storage with encryption, and token refresh logic.

**Tasks:**
1. Implement token encryption in `services/api/src/app/auth/crypto.py`:
   - `encrypt_token()` and `decrypt_token()` using Fernet (cryptography library)
   - Uses `TOKEN_ENCRYPTION_KEY` from env
2. Create Spotify OAuth endpoints in `services/api/src/app/auth/spotify.py`:
   - `GET /auth/login` - Generate Spotify authorize URL
   - `GET /auth/callback` - Exchange code for tokens
   - Store encrypted refresh token, user profile
3. Implement token refresh logic in `services/api/src/app/auth/tokens.py`:
   - `refresh_access_token(user_id)` - Refresh if expired
   - `get_valid_token(user_id)` - Get token, refresh if needed
   - Update `spotify_tokens` table
4. Create FastAPI app in `services/api/src/app/main.py`:
   - Settings management (Pydantic BaseSettings)
   - CORS configuration
   - Health check endpoint: `GET /healthz`
   - Include auth router
5. Add unit tests:
   - Token encryption/decryption roundtrip
   - OAuth callback parsing
   - Token refresh logic (mocked Spotify API)

**Definition of Done:**
- ✅ Can navigate to `/auth/login` and get redirected to Spotify
- ✅ OAuth callback successfully stores encrypted refresh token
- ✅ Can retrieve and decrypt stored refresh token
- ✅ Token refresh works when access token expires
- ✅ All auth unit tests pass
- ✅ `mypy` passes on all auth modules

**Testing:**
```bash
# Start API service
docker-compose up api -d
# Visit http://localhost:8000/auth/login in browser
# Complete OAuth flow
# Verify token stored:
docker-compose exec postgres psql -U postgres -d spotify_mcp \
  -c "SELECT spotify_user_id, created_at FROM users;"
# Run unit tests
docker-compose exec api pytest tests/test_auth/
```

**Commit Message:**
```
feat: implement Spotify OAuth flow with encrypted token storage

- Add login and callback endpoints for Spotify authorization
- Implement Fernet-based token encryption for refresh tokens
- Add automatic token refresh when access token expires
- Create token management utilities for services
- Add comprehensive unit tests for auth flow

Security: Refresh tokens encrypted at rest, never exposed in logs
```

---

### Phase 3: Spotify API Client & Basic Data Models

**Objective:** Create typed Spotify API client wrapper and implement basic play collection.

**Tasks:**
1. Implement typed Spotify client in `services/api/src/app/spotify/client.py`:
   - `SpotifyClient` class with `httpx.AsyncClient`
   - Methods: `get_recently_played()`, `get_user_profile()`, `get_tracks()`, `get_artists()`, `get_audio_features()`
   - Pydantic models for all responses in `services/api/src/app/spotify/models.py`
   - Automatic token refresh on 401
   - Rate limit handling with exponential backoff on 429
   - Proper typing with generics for paginated responses
2. Implement data ingestion utilities in `services/api/src/app/db/operations.py`:
   - `upsert_track()` - Insert or update track metadata
   - `upsert_artist()` - Insert or update artist metadata
   - `insert_play()` - Insert play record (respects unique constraint)
   - `batch_upsert_tracks()` and `batch_insert_plays()` for efficiency
3. Create basic polling logic in `services/collector/src/collector/polling.py`:
   - `poll_user_recently_played(user_id)` function
   - Fetch recently played tracks
   - Upsert tracks and artists
   - Insert plays with deduplication
   - Update `sync_checkpoints.last_poll_*` fields
4. Add unit tests:
   - Spotify client methods with `respx` for mocking
   - Batch upsert operations
   - Play deduplication logic

**Definition of Done:**
- ✅ Can fetch recently played tracks from Spotify API
- ✅ Tracks, artists, and plays stored correctly in database
- ✅ Duplicate plays handled via unique constraint
- ✅ Rate limiting (429) handled with backoff
- ✅ Token refresh happens automatically on 401
- ✅ All Spotify client unit tests pass
- ✅ `mypy` passes on spotify and db modules

**Testing:**
```bash
# Run collector once manually to test polling
docker-compose exec collector python -c "
from collector.polling import poll_user_recently_played
from collector.db import get_session
import asyncio

async def test():
    # Get first user from DB
    async with get_session() as session:
        result = await session.execute('SELECT id FROM users LIMIT 1')
        user_id = result.scalar_one()
    await poll_user_recently_played(user_id)
    print('Polling successful!')

asyncio.run(test())
"
# Verify plays inserted
docker-compose exec postgres psql -U postgres -d spotify_mcp \
  -c "SELECT COUNT(*) FROM plays;"
# Run tests
docker-compose exec collector pytest tests/test_polling.py
```

**Commit Message:**
```
feat: add typed Spotify API client and basic play collection

- Implement SpotifyClient with rate limiting and auto token refresh
- Add Pydantic models for all Spotify API responses
- Create database operations for upserting tracks/artists/plays
- Implement basic polling logic for recently played tracks
- Add unit tests with mocked Spotify API responses

Handles: 429 rate limits, 401 token refresh, play deduplication
```

---

### Phase 4: Initial Sync Implementation

**Objective:** Implement best-effort API backfill with configurable paging and stop conditions.

**Tasks:**
1. Create initial sync logic in `services/collector/src/collector/initial_sync.py`:
   - `initial_sync_user(user_id)` function
   - Paging algorithm:
     - Start with `before=now`, `limit=50`
     - For each batch: upsert tracks/artists, insert plays, track oldest `played_at`
     - Next `before = oldest_played_at - 1ms`
   - Stop conditions (from spec.md Section 5.1):
     - Empty batch
     - No progress (oldest `played_at` unchanged)
     - Reached `INITIAL_SYNC_MAX_DAYS`
     - Reached `INITIAL_SYNC_MAX_REQUESTS`
     - Excessive 429s beyond backoff policy
   - Update `sync_checkpoints` table:
     - `initial_sync_started_at`
     - `initial_sync_completed_at`
     - `initial_sync_earliest_played_at`
     - `status` field
2. Add configuration in `services/collector/src/collector/settings.py`:
   - `INITIAL_SYNC_ENABLED` (default True)
   - `INITIAL_SYNC_MAX_DAYS` (default 30)
   - `INITIAL_SYNC_MAX_REQUESTS` (default 200)
   - `INITIAL_SYNC_CONCURRENCY` (default 2)
3. Create job tracking in `services/collector/src/collector/job_tracking.py`:
   - `start_job_run()` - Create job_runs record
   - `finish_job_run()` - Update with stats and status
   - `log_to_db()` - Insert structured log events
4. Add unit tests:
   - Stop condition: empty batch
   - Stop condition: no progress
   - Stop condition: max days reached
   - Stop condition: max requests reached
   - Sync checkpoints updated correctly

**Definition of Done:**
- ✅ Initial sync can backfill 30 days of history (or until API limit)
- ✅ All stop conditions work correctly
- ✅ `sync_checkpoints` table updated with accurate timestamps
- ✅ `job_runs` records created with statistics (fetched, inserted counts)
- ✅ Structured logs written to `logs` table
- ✅ All initial sync unit tests pass
- ✅ `mypy` passes on collector modules

**Testing:**
```bash
# Run initial sync for a user
docker-compose exec collector python -c "
from collector.initial_sync import initial_sync_user
from collector.db import get_session
import asyncio

async def test():
    async with get_session() as session:
        result = await session.execute('SELECT id FROM users LIMIT 1')
        user_id = result.scalar_one()
    stats = await initial_sync_user(user_id)
    print(f'Initial sync completed: {stats}')

asyncio.run(test())
"
# Verify sync checkpoint
docker-compose exec postgres psql -U postgres -d spotify_mcp \
  -c "SELECT status, initial_sync_completed_at,
      initial_sync_earliest_played_at FROM sync_checkpoints;"
# Verify plays count increased
docker-compose exec postgres psql -U postgres -d spotify_mcp \
  -c "SELECT COUNT(*), MIN(played_at), MAX(played_at) FROM plays;"
# Run tests
docker-compose exec collector pytest tests/test_initial_sync.py
```

**Commit Message:**
```
feat: implement initial sync with best-effort API backfill

- Add paging algorithm to backfill history via Spotify API
- Implement all stop conditions (empty batch, no progress, max days/requests)
- Track sync progress in sync_checkpoints table
- Create job_runs records with detailed statistics
- Add structured logging to database
- Comprehensive unit tests for all stop conditions

Initial sync attempts to backfill up to 30 days of listening history
```

---

### Phase 5: ZIP Import System

**Objective:** Support ingestion of Spotify "Download your data" exports with multiple format support.

**Tasks:**
1. Create import job models and admin endpoint in `services/api/src/app/admin/imports.py`:
   - `POST /admin/users/{user_id}/imports/zip` - Upload ZIP endpoint
   - Store ZIP to `UPLOAD_DIR` shared volume
   - Create `import_jobs` record with status='pending'
2. Implement ZIP import logic in `services/collector/src/collector/import_zip.py`:
   - `process_import_job(job_id)` function
   - Format detection:
     - `endsong_*.json` files
     - `StreamingHistory*.json` / `Streaming_History_Audio_*.json`
   - Streaming JSON parsing (use `ijson` library)
   - Normalization mapping (spec.md Section 5.2):
     - `played_at` from `ts` or `endTime`
     - `ms_played` from `msPlayed`
     - Track/artist/album names from various fields
     - `spotify_track_uri` when present
   - Local track ID generation:
     - When no Spotify URI: `local:<sha1(artist|track|album)>`
     - Store in `tracks` table with `source="import_zip"`
   - Batch processing (5k-20k records per transaction)
   - Safety caps:
     - `IMPORT_MAX_ZIP_SIZE_MB` (default 500)
     - `IMPORT_MAX_RECORDS` (default 5,000,000)
   - Update `import_jobs` with:
     - `records_ingested`
     - `earliest_played_at` / `latest_played_at`
     - `format_detected`
     - `status` (success/error)
3. Add configuration to `services/collector/src/collector/settings.py`:
   - `IMPORT_MAX_ZIP_SIZE_MB`
   - `IMPORT_MAX_RECORDS`
   - `UPLOAD_DIR`
4. Add unit tests:
   - Format detection (endsong vs streaming_history)
   - Normalization of different JSON formats
   - Local track ID generation (deterministic)
   - Batch processing
   - Safety caps enforcement

**Definition of Done:**
- ✅ Can upload ZIP file via admin endpoint
- ✅ ZIP stored in shared volume with `import_jobs` record created
- ✅ Collector processes pending import jobs
- ✅ Both `endsong_*.json` and `StreamingHistory*.json` formats supported
- ✅ Local track IDs generated deterministically
- ✅ Batch processing works (no OOM on large files)
- ✅ Safety caps prevent oversized imports
- ✅ `import_jobs` table updated with accurate statistics
- ✅ All import unit tests pass
- ✅ `mypy` passes on import modules

**Testing:**
```bash
# Create test ZIP with sample data
mkdir -p /tmp/test_export
cat > /tmp/test_export/endsong_0.json << 'EOF'
[
  {
    "ts": "2024-01-15T10:30:00Z",
    "master_metadata_track_name": "Test Song",
    "master_metadata_album_artist_name": "Test Artist",
    "master_metadata_album_album_name": "Test Album",
    "spotify_track_uri": "spotify:track:abc123",
    "ms_played": 240000
  }
]
EOF
cd /tmp && zip -r test_export.zip test_export/

# Upload ZIP
curl -X POST http://localhost:8000/admin/users/{user_id}/imports/zip \
  -F "file=@test_export.zip" \
  -H "Authorization: Bearer {admin_token}"

# Verify import_jobs record created
docker-compose exec postgres psql -U postgres -d spotify_mcp \
  -c "SELECT id, status, file_size_bytes FROM import_jobs;"

# Run collector to process
docker-compose exec collector python -c "
from collector.import_zip import process_pending_imports
import asyncio
asyncio.run(process_pending_imports())
"

# Verify import completed
docker-compose exec postgres psql -U postgres -d spotify_mcp \
  -c "SELECT status, records_ingested, format_detected FROM import_jobs;"
docker-compose exec postgres psql -U postgres -d spotify_mcp \
  -c "SELECT COUNT(*) FROM plays WHERE source='import_zip';"

# Run tests
docker-compose exec collector pytest tests/test_import_zip.py
```

**Commit Message:**
```
feat: implement ZIP import for Spotify data exports

- Add admin endpoint for ZIP upload with multipart support
- Implement streaming JSON parser for large export files
- Support multiple formats (endsong_*.json, StreamingHistory*.json)
- Generate deterministic local track IDs for records without Spotify URIs
- Add batch processing to prevent OOM on large imports
- Enforce safety caps (max size 500MB, max records 5M)
- Track import progress in import_jobs table

Can now backfill years of history from Spotify's data export feature
```

---

### Phase 7: Admin API & Authentication

**Objective:** Complete the admin REST API and add authentication to admin + MCP endpoints.

**Context:** Currently only 2 admin endpoints exist (ZIP upload and import-job status). The `ADMIN_AUTH_MODE` and `ADMIN_TOKEN` env vars are defined but unused. MCP and admin endpoints have no authentication.

**Tasks:**
1. Implement admin authentication middleware in `services/api/src/app/admin/auth.py`:
   - FastAPI dependency that validates auth based on `ADMIN_AUTH_MODE`
   - Token auth: validate `Authorization: Bearer {ADMIN_TOKEN}` header
   - Basic auth: validate username/password against env vars
   - Apply to all admin endpoints via router-level dependency
2. Implement user management endpoints in `services/api/src/app/admin/router.py` (extend existing):
   - `GET /admin/users` — List all users with sync status (join users + sync_checkpoints)
   - `GET /admin/users/{user_id}` — User detail with full sync state, token status, recent jobs
   - `POST /admin/users/{user_id}/pause` — Set sync_checkpoint status to `paused`
   - `POST /admin/users/{user_id}/resume` — Set sync_checkpoint status to `idle`
   - `POST /admin/users/{user_id}/trigger-sync` — Reset initial sync checkpoint to trigger re-sync
   - `DELETE /admin/users/{user_id}` — Delete user and all associated data
3. Implement operational endpoints:
   - `GET /admin/sync-status` — Global overview: user count, active syncs, recent errors
   - `GET /admin/job-runs?user_id=&job_type=&status=&limit=&offset=` — Paginated job history
   - `GET /admin/import-jobs?user_id=&status=&limit=&offset=` — Paginated import history
4. Implement structured DB logging:
   - `services/api/src/app/logging/handler.py` — Async DB log handler writing to `logs` table
   - `GET /admin/logs?service=&level=&user_id=&q=&since=&limit=&offset=` — Log viewer with filtering
   - Log retention: `POST /admin/maintenance/purge-logs?older_than_days=30`
5. Add Pydantic response schemas for all new endpoints
6. Add tests for auth middleware, all admin endpoints, and log handler

**New Files:**
- `services/api/src/app/admin/auth.py` — Admin auth dependency
- `services/api/src/app/admin/schemas.py` — Extended with new response models
- `services/api/src/app/logging/handler.py` — DB log handler
- `services/api/tests/test_admin/test_auth.py` — Auth middleware tests
- `services/api/tests/test_admin/test_users.py` — User management endpoint tests
- `services/api/tests/test_admin/test_operations.py` — Job/import/log endpoint tests

**Modified Files:**
- `services/api/src/app/admin/router.py` — Add all new endpoints + auth dependency
- `services/api/src/app/logging/__init__.py` — Export handler
- `services/api/src/app/settings.py` — Add `ADMIN_AUTH_MODE`, `ADMIN_TOKEN`, `LOG_RETENTION_DAYS`

**Definition of Done:**
- All admin endpoints implemented with proper auth
- Token and basic auth modes both work
- Unauthenticated requests return 401
- Pause/resume/trigger-sync modify sync_checkpoints correctly
- Log viewer supports filtering by service, level, user, text search
- DB log handler can be attached to Python logging
- All new tests pass, ruff + mypy clean

---

### Phase 8: Admin Frontend

**Objective:** Build server-rendered management UI for monitoring and operating the system.

**Context:** Frontend service has only a FastAPI skeleton with health endpoint. It should call the API service (never touch DB directly) and use Jinja2 + HTMX for interactivity.

**Tasks:**
1. Set up frontend infrastructure:
   - `services/frontend/src/frontend/api_client.py` — Typed async client for all admin API endpoints
   - `services/frontend/src/frontend/templates/base.html` — Layout with navigation sidebar
   - `services/frontend/src/frontend/static/` — CSS, HTMX library, Chart.js
2. Implement pages:
   - **Dashboard** (`/`) — System health: user count, active syncs, recent jobs, error summary
   - **Users** (`/users`) — Table of all users with sync status, token expiry, actions
   - **User Detail** (`/users/{id}`) — Full sync state, recent jobs, import history, pause/resume/trigger buttons
   - **Imports** (`/imports`) — Upload form + import job list with status, stats, date range
   - **Jobs** (`/jobs`) — Job runs table with filtering (user, type, status), detail view
   - **Logs** (`/logs`) — Searchable log viewer with service/level filters, auto-refresh via HTMX polling
   - **Analytics** (`/analytics/{user_id}`) — Taste summary stats, top artists/tracks charts, listening heatmap visualization
3. Wire HTMX for dynamic updates:
   - Polling for dashboard stats refresh
   - Inline actions (pause/resume/trigger) with immediate feedback
   - Infinite scroll or pagination for logs/jobs tables
   - Upload progress for ZIP imports
4. Add frontend auth (mirror admin auth — forward token/basic credentials to API)

**New Files:**
- `services/frontend/src/frontend/api_client.py`
- `services/frontend/src/frontend/routes/` — Route modules (dashboard, users, imports, jobs, logs, analytics)
- `services/frontend/src/frontend/templates/*.html` — 8 templates (base + 7 pages)
- `services/frontend/src/frontend/static/css/style.css`
- `services/frontend/src/frontend/static/js/` — HTMX, Chart.js (vendored or CDN)

**Modified Files:**
- `services/frontend/src/frontend/main.py` — Register routes, template config, static files
- `services/frontend/Dockerfile` — Add template/static COPY steps if needed

**Definition of Done:**
- All 7 pages render correctly
- HTMX actions work (pause/resume/trigger, upload, refresh)
- Analytics page shows charts (top artists/tracks bar chart, heatmap grid)
- Frontend auth forwards credentials to API correctly
- Runs in Docker alongside other services
- Manual verification of all pages

---

### Phase 9: Production Readiness & Documentation

**Objective:** Harden the system for production use and create comprehensive documentation.

**Tasks:**
1. Security hardening:
   - Rate limiting on public endpoints (auth, MCP)
   - Security headers middleware (HSTS, X-Content-Type-Options, etc.)
   - CSRF protection for frontend form submissions
   - Review all endpoints for proper authorization
   - Ensure no tokens/PII in logs or error responses
2. Observability:
   - Structured JSON logging across all services
   - Request-ID middleware for trace correlation
   - Metrics endpoint (Prometheus format) — basic counters for requests, errors, poll/sync cycles
3. Docker production hardening:
   - Restart policies (`unless-stopped`)
   - Resource limits (memory, CPU)
   - Health check tuning
   - `.dockerignore` cleanup
4. Documentation:
   - `README.md` — Project overview, architecture diagram, quick start guide, configuration reference
   - `docs/deployment.md` — Production deployment guide (Docker, env vars, backups, monitoring)
   - `docs/chatgpt-integration.md` — Setting up as ChatGPT Custom GPT Action (OpenAPI spec, auth, example prompts)
   - `docs/troubleshooting.md` — Common issues and solutions
   - OpenAPI docstrings for all endpoints with example requests/responses
5. Additional testing:
   - Integration tests for admin endpoints + frontend (via TestClient)
   - Error scenario tests (Spotify API failures, DB timeouts, invalid ZIPs)
   - Test coverage report (target: >80% for api and collector)

**Definition of Done:**
- Rate limiting active on public endpoints
- Structured JSON logs with request-ID correlation
- Docker Compose production-ready
- All documentation written and accurate
- Test coverage >80%
- Fresh deployment test passes end-to-end
- ChatGPT integration guide tested with real Custom GPT

---

## Post-Implementation Verification

After all phases are complete, perform end-to-end verification:

1. **Fresh deployment test:**
   ```bash
   # Clone repo to new directory
   git clone <repo> test-deploy
   cd test-deploy
   # Copy .env.example to .env and fill in values
   cp .env.example .env
   # Start system
   docker-compose up -d
   # Wait for healthy
   docker-compose ps
   # Authorize user
   open http://localhost:8000/auth/login
   ```

2. **Complete user journey:**
   - Authorize Spotify account
   - Upload ZIP export (if available)
   - Wait for initial sync to complete
   - Query MCP tools for analysis
   - View results in admin UI
   - Verify continuous polling works

3. **ChatGPT integration:**
   - Set up Custom GPT Action
   - Test tool invocations
   - Verify all tools work from ChatGPT interface

4. **Performance validation:**
   - Load 100k+ plays
   - Query taste_summary for 90 days
   - Verify response time < 2 seconds

5. **Resilience testing:**
   - Kill collector during sync
   - Restart → verify resume from checkpoint
   - Simulate Spotify API errors
   - Verify graceful error handling

---

## Notes on Implementation Approach

### Type Safety First
- Write all type hints before implementation
- Run `mypy` continuously during development
- Use Pydantic v2 for all data validation
- Never use `Any` type without justification

### Database First
- Design complete schema before any service logic
- Use Alembic migrations for all schema changes
- Test migrations (up and down) thoroughly
- Use database constraints for data integrity

### Testing Strategy
- Write tests alongside implementation (not after)
- Use pytest fixtures for common setup
- Mock external APIs (Spotify) with `respx`
- Use Docker for integration tests with real Postgres

### Error Handling
- Structured error responses with Pydantic models
- Log all errors to database with context
- Graceful degradation (continue with other users on individual failures)
- Exponential backoff for retries

### Security
- Never log tokens or PII
- Encrypt refresh tokens at rest
- Validate all user inputs
- Use parameterized queries (SQLAlchemy prevents SQL injection)
- Rate limit public endpoints

### Performance
- Use async/await everywhere
- Batch database operations
- Use indexes on frequently queried columns
- Stream large files (ZIP imports, log exports)
- Connection pooling for database

---

## Implementation Timeline Estimate

**Completed phases (1–6):** ~12 days of focused development

**Remaining phases:**
- Phase 7: 1–2 days (admin API + auth middleware + DB logging)
- Phase 8: 2–3 days (frontend UI with templates, HTMX, charts)
- Phase 9: 1–2 days (security hardening, documentation, deployment guide)

**Total remaining: 4–7 days of focused development**

---

## Key Files — Remaining Phases

### Phase 7 (Admin API & Auth)
- `services/api/src/app/admin/auth.py` — Auth dependency
- `services/api/src/app/admin/router.py` — Extend with user/job/log endpoints
- `services/api/src/app/admin/schemas.py` — New response models
- `services/api/src/app/logging/handler.py` — DB log handler
- `services/api/tests/test_admin/test_auth.py`
- `services/api/tests/test_admin/test_users.py`
- `services/api/tests/test_admin/test_operations.py`

### Phase 8 (Admin Frontend)
- `services/frontend/src/frontend/api_client.py`
- `services/frontend/src/frontend/routes/*.py` — Route modules
- `services/frontend/src/frontend/templates/*.html` — 8 templates
- `services/frontend/src/frontend/static/` — CSS, JS

### Phase 9 (Production Readiness)
- `README.md` — Comprehensive project README
- `docs/deployment.md`
- `docs/chatgpt-integration.md`
- `docs/troubleshooting.md`
- Security middleware, rate limiting, metrics endpoint
