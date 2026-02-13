# Phase 7: Admin API & Authentication — Implementation Plan

## Context

Phases 1–6 built the complete data pipeline and MCP tool layer. The system can collect, import, store, and query Spotify listening data. However:

- **No authentication** on admin or MCP endpoints — anyone can call them
- **Only 2 admin endpoints** exist (ZIP upload + import job status)
- **No user management** — no way to list users, pause/resume sync, or delete accounts
- **No operational visibility** — no paginated job/import history, no log viewer
- **The `logs` table exists** but nothing writes to it

Phase 7 completes the admin REST API and adds authentication across admin + MCP endpoints.

---

## Current State

### What exists

| Component | State |
|-----------|-------|
| `admin/router.py` | 2 endpoints: `POST /admin/users/{id}/import`, `GET /admin/import-jobs/{id}` |
| `admin/schemas.py` | `ImportJobResponse`, `ImportJobStatusResponse` |
| `settings.py` | Spotify + upload config only — no admin auth settings |
| `logging/__init__.py` | Empty stub |
| `Log` model | Full schema with `service`, `level`, `message`, `user_id`, `job_run_id`, `import_job_id`, `log_metadata`, indexed |
| `SyncCheckpoint` model | `status` field (SyncStatus enum: IDLE, PAUSED, SYNCING, ERROR) |
| `JobRun` model | `job_type`, `status`, `records_fetched/inserted/skipped`, timestamps |
| `ImportJob` model | `status`, `file_path`, `records_ingested`, `format_detected`, timestamps |
| MCP router | `GET /mcp/tools` + `POST /mcp/call` — no auth |

### What's missing

- Authentication middleware (token + basic auth modes)
- Admin auth settings (`ADMIN_AUTH_MODE`, `ADMIN_TOKEN`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`)
- User management endpoints (list, detail, pause, resume, trigger-sync, delete)
- Operational endpoints (global sync status, paginated job runs, paginated import jobs)
- Log infrastructure (DB handler, log viewer endpoint, retention/purge)
- Tests for all of the above

---

## Architecture Decisions

### 1. Auth Strategy — Environment-Based Shared Secret

The admin is a single-operator system (the Spotify account owner). There are no multiple admin roles, no user-scoped permissions. Authentication uses a shared secret configured via environment variables.

Two modes, selected by `ADMIN_AUTH_MODE`:

- **`token`** (default): `Authorization: Bearer <ADMIN_TOKEN>` header. Used by ChatGPT Custom GPT Actions and programmatic callers.
- **`basic`**: HTTP Basic Auth with `ADMIN_USERNAME` / `ADMIN_PASSWORD`. Used by the admin frontend (browser-friendly).

When `ADMIN_AUTH_MODE` is unset or empty, auth is **disabled** (development mode). This avoids breaking the existing Docker setup and tests.

### 2. Auth Scope — Admin + MCP

Both admin and MCP routers get the same auth dependency. The MCP `/mcp/tools` catalog endpoint remains public (it's a read-only schema). Only `/mcp/call` (which executes tools and accesses user data) requires auth.

### 3. Endpoint Design — Extend Existing Router

All new endpoints go in the existing `admin/router.py` (extended). No need for a separate router since they all share the `/admin` prefix and auth dependency.

### 4. Pagination — Offset-Based

For job runs, import jobs, and logs: use `limit` + `offset` query parameters with a `PaginatedResponse[T]` generic wrapper containing `items`, `total`, `limit`, `offset`. This is simple, matches the DB query pattern, and is sufficient for the expected data volumes.

### 5. DB Logging — Async Buffer

The DB log handler accumulates log records in a memory buffer and flushes them in batches (every N records or M seconds). This avoids creating a DB session per log line. The handler runs in a background task and tolerates failures gracefully (falls back to stderr).

### 6. Delete User — Cascade

`DELETE /admin/users/{user_id}` deletes the user and all associated data (plays, tokens, sync checkpoints, job runs, import jobs). The DB schema already has `CASCADE` / `SET NULL` foreign keys, so this is a simple `session.delete(user)` after loading with relationships.

---

## New Files

| # | File | Purpose |
|---|------|---------|
| 1 | `services/api/src/app/admin/auth.py` | `require_admin` FastAPI dependency — validates auth header based on settings |
| 2 | `services/api/src/app/admin/service.py` | `AdminService` — business logic for user management, sync operations |
| 3 | `services/api/src/app/logging/handler.py` | `DBLogHandler` — async Python logging handler writing to `logs` table |
| 4 | `services/api/src/app/logging/service.py` | `LogService` — query logs, purge old logs |
| 5 | `services/api/tests/test_admin/test_auth.py` | Auth middleware tests (token, basic, disabled, invalid) |
| 6 | `services/api/tests/test_admin/test_users.py` | User management endpoint tests |
| 7 | `services/api/tests/test_admin/test_operations.py` | Job runs, import jobs, sync status endpoint tests |
| 8 | `services/api/tests/test_admin/test_logs.py` | Log viewer + purge endpoint tests |

## Modified Files

| File | Change |
|------|--------|
| `services/api/src/app/settings.py` | Add `ADMIN_AUTH_MODE`, `ADMIN_TOKEN`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `LOG_RETENTION_DAYS` |
| `services/api/src/app/admin/router.py` | Add auth dependency, 10 new endpoints |
| `services/api/src/app/admin/schemas.py` | Add ~12 new Pydantic response/query models |
| `services/api/src/app/admin/__init__.py` | Re-export new components |
| `services/api/src/app/mcp/router.py` | Add auth dependency to `POST /mcp/call` |
| `services/api/src/app/logging/__init__.py` | Export handler and service |
| `services/api/src/app/main.py` | Initialize DB log handler in lifespan |
| `services/api/tests/test_admin/test_import_upload.py` | Update to work with auth (disabled mode for existing tests) |

---

## Detailed Design

### 1. Authentication (`admin/auth.py`)

```python
async def require_admin(
    request: Request,
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> None:
    """FastAPI dependency that validates admin authentication.

    Raises HTTPException(401) if auth fails.
    When ADMIN_AUTH_MODE is empty/unset, auth is disabled (dev mode).
    """
```

Modes:
- **`token`**: Extract `Authorization: Bearer <token>`, compare with `settings.ADMIN_TOKEN` using `secrets.compare_digest`
- **`basic`**: Decode Base64 `Authorization: Basic <encoded>`, compare username/password with `settings.ADMIN_USERNAME` / `settings.ADMIN_PASSWORD`
- **Disabled** (empty `ADMIN_AUTH_MODE`): Pass through — no validation

The dependency is applied at the router level:
```python
router = APIRouter(dependencies=[Depends(require_admin)])
```

For the MCP router, apply selectively to `/mcp/call` only (not `/mcp/tools`).

### 2. Settings Additions

```python
# Admin authentication
ADMIN_AUTH_MODE: str = ""           # "token", "basic", or "" (disabled)
ADMIN_TOKEN: str = ""               # For token auth mode
ADMIN_USERNAME: str = ""            # For basic auth mode
ADMIN_PASSWORD: str = ""            # For basic auth mode

# Logging
LOG_RETENTION_DAYS: int = 30        # Default retention for purge endpoint
```

### 3. Admin Schemas (`admin/schemas.py`)

New models to add:

```python
# Pagination wrapper
class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int

# User management
class UserSummary(BaseModel):
    id: int
    spotify_user_id: str
    display_name: str | None
    sync_status: str | None          # From SyncCheckpoint.status
    last_poll_completed_at: datetime | None
    initial_sync_completed_at: datetime | None
    created_at: datetime

class UserDetail(BaseModel):
    id: int
    spotify_user_id: str
    display_name: str | None
    email: str | None
    country: str | None
    product: str | None
    sync_status: str | None
    initial_sync_started_at: datetime | None
    initial_sync_completed_at: datetime | None
    initial_sync_earliest_played_at: datetime | None
    last_poll_started_at: datetime | None
    last_poll_completed_at: datetime | None
    last_poll_latest_played_at: datetime | None
    token_expires_at: datetime | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime

# Global sync status
class GlobalSyncStatus(BaseModel):
    total_users: int
    active_syncs: int                # SyncStatus.SYNCING count
    paused_users: int                # SyncStatus.PAUSED count
    error_users: int                 # SyncStatus.ERROR count
    recent_errors: list[dict]        # Last 5 error job runs

# Job run
class JobRunResponse(BaseModel):
    id: int
    user_id: int
    job_type: str
    status: str
    records_fetched: int
    records_inserted: int
    records_skipped: int
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None

# Log entry
class LogEntry(BaseModel):
    id: int
    timestamp: datetime
    service: str
    level: str
    message: str
    user_id: int | None
    job_run_id: int | None
    import_job_id: int | None
    log_metadata: str | None

# Action responses
class ActionResponse(BaseModel):
    success: bool
    message: str
```

### 4. Admin Endpoints (`admin/router.py`)

New endpoints (all require `require_admin`):

```text
# User management
GET    /admin/users                              → PaginatedResponse[UserSummary]
GET    /admin/users/{user_id}                    → UserDetail
POST   /admin/users/{user_id}/pause              → ActionResponse
POST   /admin/users/{user_id}/resume             → ActionResponse
POST   /admin/users/{user_id}/trigger-sync       → ActionResponse
DELETE /admin/users/{user_id}                    → ActionResponse

# Operational
GET    /admin/sync-status                        → GlobalSyncStatus
GET    /admin/job-runs                           → PaginatedResponse[JobRunResponse]
GET    /admin/import-jobs                        → PaginatedResponse[ImportJobStatusResponse]

# Logs
GET    /admin/logs                               → PaginatedResponse[LogEntry]
POST   /admin/maintenance/purge-logs             → ActionResponse
```

Query parameters for paginated endpoints:
- `limit` (default 50, max 200)
- `offset` (default 0)
- `/job-runs`: `user_id`, `job_type`, `status`
- `/import-jobs`: `user_id`, `status`
- `/logs`: `service`, `level`, `user_id`, `q` (text search in message), `since` (ISO datetime)

### 5. Admin Service (`admin/service.py`)

Stateless class with methods:

```python
class AdminService:
    async def list_users(session, limit, offset) -> tuple[list[UserSummary], int]
    async def get_user_detail(user_id, session) -> UserDetail
    async def pause_user(user_id, session) -> None
    async def resume_user(user_id, session) -> None
    async def trigger_sync(user_id, session) -> None
    async def delete_user(user_id, session) -> None
    async def get_global_sync_status(session) -> GlobalSyncStatus
    async def list_job_runs(session, filters, limit, offset) -> tuple[list[JobRunResponse], int]
    async def list_import_jobs(session, filters, limit, offset) -> tuple[list[ImportJobStatusResponse], int]
```

### 6. MCP Auth (`mcp/router.py`)

Add `require_admin` dependency to the `/call` endpoint only:

```python
@router.post("/call", response_model=MCPCallResponse)
async def call_tool(
    request: MCPCallRequest,
    _auth: Annotated[None, Depends(require_admin)],   # NEW
    session: Annotated[AsyncSession, Depends(db_manager.dependency)],
) -> MCPCallResponse:
```

The `/mcp/tools` catalog remains public — it only returns tool definitions (no data access).

### 7. DB Log Handler (`logging/handler.py`)

```python
class DBLogHandler(logging.Handler):
    """Async-safe logging handler that writes to the logs table.

    Accumulates records in a buffer and flushes periodically or when
    the buffer reaches a threshold. Runs flush in a background task.
    """

    def __init__(self, db_manager: DatabaseManager, service: str,
                 buffer_size: int = 50, flush_interval: float = 5.0):
        ...

    def emit(self, record: logging.LogRecord) -> None:
        # Thread-safe append to buffer; schedule flush if threshold reached

    async def flush_buffer(self) -> None:
        # Create session, bulk insert Log records, commit

    async def start(self) -> None:
        # Start periodic flush background task

    async def stop(self) -> None:
        # Final flush, cancel background task
```

Integration in `main.py` lifespan:

```python
async with contextlib.accontextmanager():
    handler = DBLogHandler(db_manager, service="api")
    await handler.start()
    logging.getLogger().addHandler(handler)
    yield
    await handler.stop()
```

### 8. Log Service (`logging/service.py`)

```python
class LogService:
    async def query_logs(session, service, level, user_id, q, since, limit, offset)
        -> tuple[list[LogEntry], int]
    async def purge_logs(session, older_than_days) -> int  # returns count deleted
```

---

## Implementation Order

1. **Settings** — Add admin auth + logging config to `AppSettings`
2. **Auth dependency** — `admin/auth.py` with token/basic/disabled modes
3. **Auth tests** — `test_auth.py` (test all 3 modes + invalid credentials)
4. **Admin schemas** — Add all new Pydantic models to `admin/schemas.py`
5. **Admin service** — `admin/service.py` with user management + operational queries
6. **Admin endpoints** — Extend `admin/router.py` with all new endpoints + auth dependency
7. **User management tests** — `test_users.py` (list, detail, pause, resume, trigger, delete)
8. **Operational tests** — `test_operations.py` (sync status, job runs, import jobs)
9. **Update existing tests** — Adjust `test_import_upload.py` for auth compatibility
10. **MCP auth** — Add `require_admin` to `POST /mcp/call`
11. **Log handler** — `logging/handler.py` with buffered async writes
12. **Log service** — `logging/service.py` with query + purge
13. **Log endpoints** — Add `GET /admin/logs` + `POST /admin/maintenance/purge-logs`
14. **Log tests** — `test_logs.py` (query with filters, purge, handler integration)
15. **Main.py integration** — Wire up log handler in lifespan
16. **Full test suite** — Run all API tests, lint, typecheck

---

## Verification

1. `ruff check` + `ruff format --check` across all packages
2. `mypy` across all packages
3. `pytest services/api/tests/` — all API tests pass (existing + new)
4. Manual curl verification:
   - `GET /admin/users` with valid token → 200 with user list
   - `GET /admin/users` without token → 401
   - `GET /admin/users` with wrong token → 401
   - `POST /admin/users/{id}/pause` → sync status changes to PAUSED
   - `POST /admin/users/{id}/resume` → sync status changes to IDLE
   - `GET /admin/sync-status` → global overview
   - `GET /admin/job-runs?job_type=poll&limit=5` → paginated job list
   - `GET /admin/logs?level=error&limit=10` → filtered log entries
   - `POST /mcp/call` with valid token → tool executes
   - `POST /mcp/call` without token → 401
   - `GET /mcp/tools` without token → 200 (public)
5. Docker build and verify all services start healthy

---

## Test Plan

| Test File | Cases | What's Tested |
|-----------|-------|---------------|
| `test_auth.py` | ~8 | Token mode valid/invalid, basic mode valid/invalid, disabled mode, missing header, wrong scheme |
| `test_users.py` | ~10 | List users, user detail, 404 on missing user, pause/resume toggle, trigger-sync resets checkpoint, delete cascades, pagination |
| `test_operations.py` | ~8 | Global sync status counts, job runs with filters, import jobs with filters, pagination, empty results |
| `test_logs.py` | ~6 | Query with service/level/text filters, purge by age, handler buffer flush, handler tolerates DB errors |
| `test_import_upload.py` | 5 (existing) | Updated to pass with auth disabled |

**Estimated new tests: ~32**
**Total test count after phase 7: ~193** (161 existing + 32 new)
