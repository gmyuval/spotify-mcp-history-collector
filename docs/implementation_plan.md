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

**Current state:** Empty repository with only spec.md, environment.yml, and basic project files.

**Goal:** Build a production-ready, fully-typed, containerized Python system following the detailed specification in spec.md.

---

## Implementation Phases

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

### Phase 6: Collector Worker Service

**Objective:** Implement autonomous collector run loop with job prioritization.

**Tasks:**
1. Implement main run loop in `services/collector/src/collector/runloop.py`:
   - `run_collector()` main async function
   - Priority order (spec.md Section 7B):
     1. Pick pending `import_jobs` and process them
     2. For each user: if initial sync enabled and incomplete, run initial sync
     3. For each user: run incremental poll (unless paused)
   - Respect `sync_checkpoints.status`:
     - Skip if `paused`
     - Skip initial sync if already completed
   - Sleep between cycles: `COLLECTOR_INTERVAL_SECONDS` (default 600)
2. Create collector entrypoint in `services/collector/src/collector/main.py`:
   - Load settings from environment
   - Initialize database connection
   - Start run loop
   - Graceful shutdown on SIGTERM
3. Add concurrency control:
   - Semaphore for concurrent user processing
   - Semaphore for Spotify API calls
   - Per-user locking to prevent concurrent syncs
4. Implement pause/resume admin endpoints in `services/api/src/app/admin/users.py`:
   - `POST /admin/users/{user_id}/pause` - Set status='paused'
   - `POST /admin/users/{user_id}/resume` - Set status='idle'
   - `POST /admin/users/{user_id}/initial-sync` - Trigger initial sync
5. Add integration tests:
   - Full collector cycle (import → initial sync → poll)
   - Pause/resume functionality
   - Concurrent user processing

**Definition of Done:**
- ✅ Collector runs autonomously in Docker container
- ✅ Processes jobs in correct priority order
- ✅ Respects pause/resume status from admin endpoints
- ✅ Handles errors gracefully (logs to DB, continues with other users)
- ✅ Graceful shutdown on container stop
- ✅ Concurrency limits prevent API overload
- ✅ All collector integration tests pass
- ✅ `mypy` passes on all collector modules

**Testing:**
```bash
# Start full stack
docker-compose up -d

# Authorize a user (via browser)
open http://localhost:8000/auth/login

# Upload ZIP (optional)
curl -X POST http://localhost:8000/admin/users/{user_id}/imports/zip \
  -F "file=@export.zip" -H "Authorization: Bearer {token}"

# Watch collector logs
docker-compose logs -f collector

# Should see:
# - Processing import job (if uploaded)
# - Running initial sync for user
# - Polling for new plays every 10 minutes

# Test pause
curl -X POST http://localhost:8000/admin/users/{user_id}/pause \
  -H "Authorization: Bearer {token}"
# Verify collector skips paused user

# Test resume
curl -X POST http://localhost:8000/admin/users/{user_id}/resume \
  -H "Authorization: Bearer {token}"
# Verify collector resumes processing

# Check job_runs
docker-compose exec postgres psql -U postgres -d spotify_mcp \
  -c "SELECT job_type, status, started_at FROM job_runs ORDER BY started_at DESC LIMIT 10;"

# Run integration tests
docker-compose exec collector pytest tests/test_integration/
```

**Commit Message:**
```
feat: implement autonomous collector worker service

- Add main run loop with job prioritization (imports → initial sync → polling)
- Implement pause/resume functionality via admin endpoints
- Add concurrency control with semaphores for API rate limiting
- Create graceful shutdown handling for container lifecycle
- Add comprehensive integration tests for full collector cycle

Collector now runs autonomously, processing all users continuously
```

---

### Phase 7: MCP Tool Endpoints

**Objective:** Implement all MCP tool endpoints for history analysis and Spotify live queries.

**Tasks:**
1. Create MCP tool catalog in `services/api/src/app/mcp/tools.py`:
   - Tool registry with schemas
   - `GET /mcp/tools` - Return all available tools with descriptions and parameters
   - Tool definitions (spec.md Section 7A):
     - History tools: `history.taste_summary`, `history.top_artists`, `history.top_tracks`, `history.listening_heatmap`, `history.repeat_rate`, `history.coverage`
     - Spotify live tools: `spotify.get_top`, `spotify.search`
     - Ops tools: `ops.sync_status`, `ops.latest_job_runs`, `ops.latest_import_jobs`
2. Implement tool dispatcher in `services/api/src/app/mcp/dispatcher.py`:
   - `POST /mcp/call` endpoint
   - Request model: `{"tool": "...", "args": {...}}`
   - Route to appropriate handler
   - Validate args against tool schema
   - Return typed response
3. Implement history analysis in `services/api/src/app/history/queries.py`:
   - `taste_summary(days, user_id)`:
     - Play count, unique tracks/artists
     - Top artists/tracks by play count
     - Repeat rate and concentration
     - Listening heatmap (weekday/hour)
     - Coverage stats (data completeness)
   - `top_artists(days, limit, user_id)` - Top artists by play count
   - `top_tracks(days, limit, user_id)` - Top tracks by play count
   - `listening_heatmap(days, user_id)` - Hour of day × day of week
   - `repeat_rate(days, user_id)` - Track repeat statistics
   - `coverage(days, user_id)` - Date range completeness check
4. Create response models in `services/api/src/app/history/models.py`:
   - `TasteSummary`, `ArtistCount`, `TrackCount`, `Heatmap`, `RepeatStats`, `CoverageStats`
   - Full type hints per spec.md Section 11
5. Implement Spotify live tools in `services/api/src/app/mcp/spotify_tools.py`:
   - `get_top(entity, time_range, limit, user_id)` - Call Spotify's top API
   - `search(q, type, limit, user_id)` - Search Spotify catalog
6. Implement ops tools in `services/api/src/app/mcp/ops_tools.py`:
   - `sync_status(user_id)` - Return sync_checkpoints data
   - `latest_job_runs(user_id, limit)` - Recent job history
   - `latest_import_jobs(user_id, limit)` - Recent imports
7. Add unit tests:
   - Tool catalog generation
   - Tool dispatcher routing
   - Each history query with test data
   - Response model validation

**Definition of Done:**
- ✅ `GET /mcp/tools` returns complete tool catalog with schemas
- ✅ `POST /mcp/call` dispatches to correct tool handler
- ✅ All 11 tools implemented and working
- ✅ History queries return accurate statistics
- ✅ Heatmap generates correct weekday/hour aggregations
- ✅ Coverage stats identify missing data gaps
- ✅ Spotify live tools call real API and return results
- ✅ All response models validate correctly
- ✅ All MCP unit tests pass
- ✅ `mypy` passes on all mcp modules

**Testing:**
```bash
# Get tool catalog
curl http://localhost:8000/mcp/tools | jq

# Test taste_summary
curl -X POST http://localhost:8000/mcp/call \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "history.taste_summary",
    "args": {"days": 90, "user_id": "..."}
  }' | jq

# Should return:
# - play count, unique tracks/artists
# - top 10 artists/tracks
# - repeat stats
# - heatmap data
# - coverage stats

# Test top_artists
curl -X POST http://localhost:8000/mcp/call \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "history.top_artists",
    "args": {"days": 30, "limit": 20, "user_id": "..."}
  }' | jq

# Test Spotify live tool
curl -X POST http://localhost:8000/mcp/call \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "spotify.get_top",
    "args": {"entity": "artists", "time_range": "short_term", "limit": 10, "user_id": "..."}
  }' | jq

# Test ops tool
curl -X POST http://localhost:8000/mcp/call \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "ops.sync_status",
    "args": {"user_id": "..."}
  }' | jq

# Run unit tests
docker-compose exec api pytest tests/test_mcp/
```

**Commit Message:**
```
feat: implement all MCP tool endpoints for history analysis

- Add tool catalog endpoint (GET /mcp/tools) with complete schemas
- Implement tool dispatcher (POST /mcp/call) with request validation
- Create 6 history analysis tools (taste_summary, top_artists, etc.)
- Implement listening heatmap with weekday/hour aggregations
- Add coverage stats to detect missing data gaps
- Implement 2 Spotify live tools (get_top, search)
- Add 3 ops tools for sync status monitoring
- Comprehensive unit tests for all tools

ChatGPT can now analyze 90+ days of listening history via MCP interface
```

---

### Phase 8: Admin API & Frontend

**Objective:** Build complete admin UI for managing users, monitoring sync status, and viewing logs.

**Tasks:**
1. Implement remaining admin API endpoints in `services/api/src/app/admin/`:
   - `GET /admin/users` - List all users with sync status
   - `GET /admin/users/{user_id}` - User detail with full sync state
   - `GET /admin/sync-status` - Global sync status overview
   - `GET /admin/job-runs?user_id=...` - Job history with pagination
   - `GET /admin/import-jobs?user_id=...` - Import history with pagination
   - `GET /admin/logs?service=...&level=...&q=...&since=...` - Log viewer with filtering
2. Add admin authentication middleware in `services/api/src/app/admin/auth.py`:
   - Support `ADMIN_AUTH_MODE`: `basic` or `token`
   - Token auth: validate `Authorization: Bearer {ADMIN_TOKEN}`
   - Basic auth: validate username/password against env vars
3. Create frontend service in `services/frontend/`:
   - FastAPI app serving Jinja2 templates
   - HTMX for dynamic updates (recommended approach from spec)
   - Pages:
     - **Dashboard** - System health, recent activity, user count
     - **Users** - List with token status, sync progress, actions
     - **User Detail** - Full sync state, recent jobs, trigger actions
     - **Imports** - Upload form, import job list with status
     - **Jobs** - Job runs list with filtering, detail view
     - **Logs** - Searchable log viewer with service/level filters
     - **Analytics** - Taste summary visualization, top charts, heatmap
4. Create templates in `services/frontend/src/frontend/templates/`:
   - `base.html` - Layout with navigation
   - `dashboard.html`, `users.html`, `user_detail.html`, `imports.html`, `jobs.html`, `logs.html`, `analytics.html`
5. Add static assets in `services/frontend/src/frontend/static/`:
   - CSS for styling (simple, clean design)
   - HTMX library
   - Basic JS for charts (Chart.js or similar)
6. Implement API client in `services/frontend/src/frontend/api_client.py`:
   - Typed methods for all admin endpoints
   - Error handling and retries

**Definition of Done:**
- ✅ All admin API endpoints implemented and documented
- ✅ Admin authentication works (token or basic)
- ✅ Frontend service runs and serves all pages
- ✅ Can view list of users with sync status
- ✅ Can pause/resume users from UI
- ✅ Can trigger initial sync from UI
- ✅ Can upload ZIP file from UI
- ✅ Can view job runs with filtering
- ✅ Can view and search logs
- ✅ Analytics page shows taste summary and heatmap visualization
- ✅ All admin API tests pass
- ✅ `mypy` passes on admin and frontend modules

**Testing:**
```bash
# Start all services
docker-compose up -d

# Visit frontend
open http://localhost:8001

# Should see dashboard with:
# - System status
# - User count
# - Recent activity

# Test user management:
# 1. Navigate to Users page
# 2. Click on a user
# 3. View sync status, job history
# 4. Pause user → verify status changes
# 5. Resume user → verify status changes
# 6. Trigger initial sync → verify job starts

# Test import flow:
# 1. Navigate to Imports page
# 2. Upload ZIP file
# 3. See import job created
# 4. Wait for collector to process
# 5. See import completed with stats

# Test log viewer:
# 1. Navigate to Logs page
# 2. Filter by service (api/collector/frontend)
# 3. Filter by level (info/warning/error)
# 4. Search for text
# 5. Verify logs displayed correctly

# Test analytics:
# 1. Navigate to Analytics page (select user)
# 2. See taste summary stats
# 3. See top artists/tracks charts
# 4. See listening heatmap visualization

# Run admin API tests
docker-compose exec api pytest tests/test_admin/
```

**Commit Message:**
```
feat: implement admin API and web-based management UI

- Add complete admin REST API (users, jobs, imports, logs)
- Implement admin authentication (token or basic auth)
- Build FastAPI frontend with Jinja2 templates and HTMX
- Create dashboard for system monitoring
- Add user management UI (list, detail, pause/resume, trigger sync)
- Implement ZIP upload interface with import tracking
- Add job runs viewer with filtering
- Create searchable log viewer with service/level filters
- Build analytics page with taste summary and heatmap visualization

Complete web UI for managing Spotify history collection system
```

---

### Phase 9: Testing, Documentation & Production Readiness

**Objective:** Comprehensive testing, documentation, and production hardening.

**Tasks:**
1. Add comprehensive integration tests in `tests/integration/`:
   - `test_full_flow.py` - Complete user journey:
     - OAuth authorization
     - Initial sync
     - ZIP import
     - Incremental polling
     - MCP tool queries
     - Admin operations
   - `test_error_scenarios.py`:
     - Network failures
     - Spotify API errors (429, 500, 503)
     - Invalid ZIP files
     - Database connection failures
     - Token revocation
   - `test_concurrent_operations.py`:
     - Multiple users syncing simultaneously
     - Concurrent polling and imports
2. Add performance tests in `tests/performance/`:
   - Large dataset queries (millions of plays)
   - Heatmap generation performance
   - Batch processing performance
   - ZIP import of large files (100MB+)
3. Implement log retention in `services/api/src/app/admin/maintenance.py`:
   - Scheduled cleanup of logs older than N days
   - Configurable via `LOG_RETENTION_DAYS` env var
4. Add OpenAPI documentation:
   - Complete docstrings for all endpoints
   - Example requests/responses
   - Authentication documentation
5. Create comprehensive README.md:
   - Project overview
   - Architecture diagram (text-based)
   - Quick start guide
   - Configuration reference
   - Development guide
   - Deployment guide
   - Troubleshooting section
6. Update docker-compose.yml for production:
   - Health checks for all services
   - Restart policies
   - Resource limits
   - Volume management for persistence
7. Add monitoring and observability:
   - Structured JSON logging in all services
   - Log correlation with request_id
   - Metrics endpoints (Prometheus format)
8. Create deployment documentation:
   - `docs/deployment.md` - Production deployment guide
   - `docs/chatgpt-integration.md` - How to set up as ChatGPT Custom GPT Action
   - `docs/troubleshooting.md` - Common issues and solutions
9. Security hardening:
   - Review all endpoints for authorization
   - Add rate limiting to public endpoints
   - Implement CSRF protection for frontend
   - Add security headers
   - Document security best practices

**Definition of Done:**
- ✅ All integration tests pass (full flow, error scenarios, concurrent ops)
- ✅ Performance tests pass (large datasets, ZIP imports)
- ✅ Log retention cleanup works correctly
- ✅ OpenAPI documentation complete and accurate
- ✅ README.md covers all aspects of the project
- ✅ Docker compose production-ready with health checks
- ✅ All services produce structured JSON logs
- ✅ Deployment documentation complete
- ✅ Security review completed
- ✅ 100% mypy compliance across all modules
- ✅ Test coverage > 80% for all services

**Testing:**
```bash
# Run all tests
docker-compose exec api pytest tests/ -v --cov=app --cov-report=html
docker-compose exec collector pytest tests/ -v --cov=collector --cov-report=html
docker-compose exec frontend pytest tests/ -v --cov=frontend --cov-report=html

# Run integration tests
pytest tests/integration/ -v

# Run performance tests
pytest tests/performance/ -v

# Check test coverage
open htmlcov/index.html

# Verify mypy passes everywhere
mypy services/api/src/
mypy services/collector/src/
mypy services/frontend/src/

# Test log retention
docker-compose exec api python -c "
from app.admin.maintenance import cleanup_old_logs
import asyncio
asyncio.run(cleanup_old_logs(days=30))
"

# Verify logs older than 30 days deleted
docker-compose exec postgres psql -U postgres -d spotify_mcp \
  -c "SELECT COUNT(*) FROM logs WHERE timestamp < NOW() - INTERVAL '30 days';"
# Should return 0

# Test OpenAPI docs
open http://localhost:8000/docs
# Verify all endpoints documented with examples

# Test complete user flow
pytest tests/integration/test_full_flow.py -v

# Test error scenarios
pytest tests/integration/test_error_scenarios.py -v

# Test concurrent operations
pytest tests/integration/test_concurrent_operations.py -v

# Verify health checks
docker-compose ps
# All services should show "healthy"

# Check logs are structured JSON
docker-compose logs api | tail -10
# Should see JSON formatted logs

# Load test
ab -n 1000 -c 10 http://localhost:8000/healthz
```

**Commit Message:**
```
feat: add comprehensive testing, documentation, and production hardening

- Add integration tests for full user flow and error scenarios
- Implement performance tests for large datasets and imports
- Add log retention cleanup with configurable retention period
- Complete OpenAPI documentation with examples
- Create comprehensive README with quick start and deployment guides
- Add production-ready docker-compose with health checks and resource limits
- Implement structured JSON logging with request correlation
- Add deployment and troubleshooting documentation
- Security hardening (rate limiting, CSRF, security headers)
- Achieve 80%+ test coverage across all services

System is now production-ready with full observability and documentation
```

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

- Phase 1: 1-2 days (foundation is critical)
- Phase 2: 1 day (OAuth is straightforward with good docs)
- Phase 3: 1 day (Spotify client + basic polling)
- Phase 4: 1-2 days (initial sync logic is complex)
- Phase 5: 2 days (ZIP import has many edge cases)
- Phase 6: 1 day (orchestration of existing pieces)
- Phase 7: 2-3 days (11 tools with comprehensive queries)
- Phase 8: 2-3 days (UI takes time for polish)
- Phase 9: 2-3 days (testing and documentation)

**Total: 13-19 days of focused development**

---

## Key Files to Create

### Phase 1
- `docker-compose.yml`
- `.env.example`
- `services/api/pyproject.toml`, `Dockerfile`, `alembic.ini`
- `services/collector/pyproject.toml`, `Dockerfile`
- `services/frontend/pyproject.toml`, `Dockerfile`
- `services/api/src/app/db/models.py` (all 11 tables)
- `services/api/alembic/versions/001_initial_schema.py`

### Phase 2
- `services/api/src/app/auth/crypto.py`
- `services/api/src/app/auth/spotify.py`
- `services/api/src/app/auth/tokens.py`
- `services/api/src/app/main.py`
- `services/api/src/app/settings.py`

### Phase 3
- `services/api/src/app/spotify/client.py`
- `services/api/src/app/spotify/models.py`
- `services/api/src/app/db/operations.py`
- `services/collector/src/collector/polling.py`
- `services/collector/src/collector/db.py`

### Phase 4
- `services/collector/src/collector/initial_sync.py`
- `services/collector/src/collector/job_tracking.py`
- `services/collector/src/collector/settings.py`

### Phase 5
- `services/api/src/app/admin/imports.py`
- `services/collector/src/collector/import_zip.py`

### Phase 6
- `services/collector/src/collector/runloop.py`
- `services/collector/src/collector/main.py`
- `services/api/src/app/admin/users.py`

### Phase 7
- `services/api/src/app/mcp/tools.py`
- `services/api/src/app/mcp/dispatcher.py`
- `services/api/src/app/history/queries.py`
- `services/api/src/app/history/models.py`
- `services/api/src/app/mcp/spotify_tools.py`
- `services/api/src/app/mcp/ops_tools.py`

### Phase 8
- `services/api/src/app/admin/auth.py`
- `services/api/src/app/admin/` (various endpoints)
- `services/frontend/src/frontend/main.py`
- `services/frontend/src/frontend/templates/*.html` (7 templates)
- `services/frontend/src/frontend/static/` (CSS, JS)
- `services/frontend/src/frontend/api_client.py`

### Phase 9
- `tests/integration/test_full_flow.py`
- `tests/integration/test_error_scenarios.py`
- `tests/integration/test_concurrent_operations.py`
- `tests/performance/` (performance tests)
- `services/api/src/app/admin/maintenance.py`
- `README.md`
- `docs/deployment.md`
- `docs/chatgpt-integration.md`
- `docs/troubleshooting.md`
