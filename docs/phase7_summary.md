# Phase 7: Admin API, Authentication & DB Logging — Summary

## What Was Built

Phase 7 adds administrative controls and observability to the API: authentication middleware for both admin and MCP endpoints, a full admin API for user/sync/job/log management, and a structured DB logging pipeline that writes application logs to the `logs` table in real time.

### New Components

| Component | Files | Purpose |
|-----------|-------|---------|
| **Auth dependency** | `api/admin/auth.py` | `require_admin` FastAPI dependency — validates `Authorization` header in token, basic, or disabled mode |
| **Admin service** | `api/admin/service.py` | `AdminService` class with 11 methods: user CRUD, sync control, job/log queries, log purge |
| **Admin schemas** | `api/admin/schemas.py` | 9 Pydantic response models including `PaginatedResponse[T]` generic, `UserSummary`, `UserDetail`, `GlobalSyncStatus`, `JobRunResponse`, `LogEntry`, `ActionResponse` |
| **DB log handler** | `api/logging/handler.py` | `DBLogHandler(logging.Handler)` — thread-safe buffered handler that flushes log records to the `logs` table periodically or at threshold |
| **Auth tests** | `tests/test_admin/test_auth.py` | 11 tests: token/basic/disabled modes, MCP auth behavior |
| **User tests** | `tests/test_admin/test_users.py` | 10 tests: list, detail, pause, resume, trigger-sync, delete |
| **Operations tests** | `tests/test_admin/test_operations.py` | 10 tests: sync status, job runs, import jobs with filters |
| **Log tests** | `tests/test_admin/test_logs.py` | 7 tests: query filters, text search, purge by age |

### Modified Components

| File | Change |
|------|--------|
| `api/settings.py` | Added `ADMIN_AUTH_MODE`, `ADMIN_TOKEN`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `LOG_RETENTION_DAYS` |
| `api/admin/router.py` | Expanded from 2 import endpoints to 13 endpoints with router-level auth dependency |
| `api/mcp/router.py` | Added `require_admin` dependency to `POST /mcp/call` (catalog remains public) |
| `api/main.py` | Wired `DBLogHandler` into application lifespan (start on boot, flush+stop on shutdown) |
| `api/logging/__init__.py` | Re-exports `DBLogHandler` |

---

## Architecture Decisions

### Authentication — Environment-Driven Shared Secret

Rather than a full user/session auth system (which would be over-engineered for an internal admin API), authentication uses a shared secret configured via environment variables:

```
ADMIN_AUTH_MODE=token   →  Authorization: Bearer <ADMIN_TOKEN>
ADMIN_AUTH_MODE=basic   →  Authorization: Basic <base64(user:pass)>
ADMIN_AUTH_MODE=         →  Auth disabled (dev mode)
```

All comparisons use `secrets.compare_digest()` to prevent timing attacks. The dependency is applied at the router level (`APIRouter(dependencies=[Depends(require_admin)])`) so all admin endpoints inherit auth without per-endpoint decoration.

**MCP selective auth**: `GET /mcp/tools` (catalog) remains public so clients can discover available tools. Only `POST /mcp/call` (tool invocation) requires auth, matching the expectation that ChatGPT Actions store the token as a GPT secret.

### DB Log Handler — Buffered Async Pipeline

The logging handler bridges Python's synchronous `logging.Handler.emit()` with async DB writes:

```
logging.info("...") → emit() → buffer (thread-safe) → periodic flush → DB session → logs table
```

Key design choices:
- **Thread-safe buffer**: `emit()` is called from any thread; a `threading.Lock` protects the buffer list
- **Dual flush triggers**: Flush when buffer reaches `buffer_size` (default 50) OR every `flush_interval` seconds (default 5.0)
- **Background task**: `asyncio.create_task(_periodic_flush)` runs for the app lifetime
- **Graceful shutdown**: `stop()` cancels the periodic task, then does a final flush to ensure no records are lost
- **Failure isolation**: If a flush fails, the error is printed to stderr but the handler does not crash the application

### Admin Service — Explicit Cascade Deletes

The `delete_user()` method explicitly deletes all dependent records (logs, import jobs, job runs, sync checkpoints, tokens, plays) before deleting the user row. This was necessary because SQLite (used in tests) does not honor `ON DELETE CASCADE` foreign key constraints, even when `PRAGMA foreign_keys = ON` is set.

```python
# Order matters — delete in dependency order
for model in [Log, ImportJob, JobRun, SyncCheckpoint, SpotifyToken, Play]:
    await session.execute(delete(model).where(model.user_id == user_id))
await session.execute(delete(User).where(User.id == user_id))
```

### Pagination — Generic Type Parameter

`PaginatedResponse[T]` uses Python 3.14's native type parameter syntax (PEP 695):

```python
class PaginatedResponse[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int
```

This replaces the older `TypeVar` + `Generic[T]` pattern and is enforced by ruff's UP046 rule.

---

## API Endpoints

### Admin Endpoints (all require auth)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/admin/users` | List users with sync status (paginated) |
| GET | `/admin/users/{user_id}` | Full user detail with token + sync state |
| POST | `/admin/users/{user_id}/pause` | Pause user sync |
| POST | `/admin/users/{user_id}/resume` | Resume user sync |
| POST | `/admin/users/{user_id}/trigger-sync` | Reset initial sync for re-run |
| DELETE | `/admin/users/{user_id}` | Delete user and all related data |
| POST | `/admin/users/{user_id}/import` | Upload ZIP for import (existing) |
| GET | `/admin/import-jobs/{job_id}` | Import job status (existing) |
| GET | `/admin/sync-status` | Global sync overview |
| GET | `/admin/job-runs` | Job run history with filters |
| GET | `/admin/import-jobs` | Import job history (paginated) |
| GET | `/admin/logs` | Query structured logs |
| POST | `/admin/maintenance/purge-logs` | Purge logs older than N days |

### MCP Auth

| Method | Path | Auth Required |
|--------|------|---------------|
| GET | `/mcp/tools` | No |
| POST | `/mcp/call` | Yes |

---

## Bugs Found & Fixed

### 1. SQLite CASCADE Delete Failure

**Symptom**: `IntegrityError: NOT NULL constraint failed: sync_checkpoints.user_id` when deleting a user in tests.

**Cause**: SQLite does not enforce `ON DELETE CASCADE` on foreign keys, even with `PRAGMA foreign_keys = ON`. The DB schema defines cascading deletes, but SQLite ignores them.

**Fix**: Added explicit cascade deletes in `AdminService.delete_user()` that delete dependent rows in the correct order before deleting the user.

### 2. Mypy `Result[Any]` Has No `rowcount`

**Symptom**: `mypy error: "Result[Any]" has no attribute "rowcount" [attr-defined]`

**Cause**: SQLAlchemy's `session.execute()` returns `Result[Any]`, which does not expose `rowcount` in its type stubs. The actual runtime type is `CursorResult` (subclass), which does have `rowcount`.

**Fix**: Added `# type: ignore[attr-defined]` with a typed local variable: `deleted: int = cursor.rowcount`.

### 3. Ruff UP046 — Generic Type Parameter Syntax

**Symptom**: `UP046: Use of TypeVar + Generic[T] instead of type parameter syntax`

**Cause**: Python 3.14 supports native type parameters (`class Foo[T]: ...`). Ruff enforces this when `target-version = "py314"`.

**Fix**: Changed `class PaginatedResponse(BaseModel, Generic[T])` to `class PaginatedResponse[T](BaseModel)`.

---

## Test Results

| Suite | Tests | Status |
|-------|-------|--------|
| API (existing) | 133 | Passed |
| API (new — admin) | 38 | Passed |
| Collector | 28 | Passed |
| **Total** | **199** | **All passing** |

Ruff lint, ruff format, and mypy strict — all clean.

## Production Verification

All endpoints verified against live Docker deployment with real data (user ID 5, 18,952 plays):

| Endpoint | Result |
|----------|--------|
| `GET /admin/users` | Lists 1 user with sync status |
| `GET /admin/users/5` | Full detail: email, country, product, sync timestamps, token expiry |
| `GET /admin/sync-status` | 1 total user, 0 active syncs, 0 errors |
| `GET /admin/job-runs` | 19 job runs (1 import, 1 initial_sync, 17 polls) |
| `POST /mcp/call` with auth | Works with token |
| `POST /mcp/call` without auth | Returns 401 |
| `GET /mcp/tools` without auth | Returns 11 tools (public catalog) |

---

## Insights & Lessons Learned

### 1. Router-Level Dependencies Beat Per-Endpoint Decoration

Using `APIRouter(dependencies=[Depends(require_admin)])` applies auth to all endpoints in the router at once. This is cleaner than decorating each endpoint individually and eliminates the risk of forgetting auth on a new endpoint. For the MCP router, where only one endpoint needs auth, per-endpoint decoration with `dependencies=[Depends(require_admin)]` on the `@router.post` decorator is the right approach.

### 2. SQLite FK Behavior Is a Silent Footgun

SQLite's foreign key support is off by default (`PRAGMA foreign_keys = OFF`) and even when enabled, `ON DELETE CASCADE` can be unreliable. For test fixtures that need cascade deletes, always add explicit delete logic in the application layer. This ensures tests match production behavior regardless of the database dialect.

### 3. Buffered Logging Requires Careful Lifecycle Management

The DB log handler needs explicit `start()` and `stop()` calls wired into the FastAPI lifespan context manager. Without `stop()`, the final flush never happens and recent log records are lost on shutdown. The lifespan approach (`yield` with `finally`) guarantees cleanup even on exceptions.

### 4. Python 3.14 Type Parameters Simplify Generics

The new `class Foo[T](Base)` syntax (PEP 695/649) is significantly cleaner than `TypeVar + Generic[T]`. Combined with ruff's UP046 rule, it ensures the codebase stays consistent. Pydantic v2 fully supports this syntax for generic models like `PaginatedResponse[T]`.

### 5. `secrets.compare_digest` Is Non-Negotiable for Auth

Even for internal admin tokens, always use timing-safe comparison. Regular string comparison (`==`) leaks information about the token value through timing side-channels. `secrets.compare_digest()` runs in constant time regardless of how many characters match.

---

## Pointers for Next Phases

### Phase 8: Admin Frontend

The frontend service (`services/frontend/`) has a FastAPI skeleton but no templates. It should:
- Call admin API endpoints (all now implemented) using `API_BASE_URL`
- Display user list, detail, sync status, job runs, import jobs, logs
- Support CRUD actions: pause/resume sync, trigger sync, delete user, upload ZIP
- Use Jinja2 + HTMX for server-rendered interactivity (no JS build step)
- Mirror `ADMIN_AUTH_MODE` — frontend passes auth token/credentials to API calls

**Key insight**: The admin API is now complete. The frontend is purely a rendering layer — it should never touch the database directly.

### Phase 9: Audio Features Enrichment

The `audio_features` table exists but is empty. `SpotifyClient.get_audio_features()` is already implemented:
- Add `enrich` job type to collector run loop
- Batch-fetch for tracks missing audio features
- New MCP tools: "average danceability", "most energetic tracks", mood clustering

### Phase 10: Local Track Resolution

ZIP imports without Spotify URIs have `local:<sha1>` IDs. Use `SpotifyClient.search()` to resolve them:
- Match by track name + artist name
- Update `tracks.spotify_id`, handle conflicts
- Run as low-priority background job

### Cross-Cutting Concerns

- **Test count**: 199 tests total (171 API + 28 collector). Each phase should maintain or increase coverage
- **Test isolation**: API and collector tests must still be run separately due to conftest BigInteger-SQLite compilation conflicts
- **Pre-commit hooks**: ruff v0.15.0 + mypy strict on every commit; never use `--no-verify`
- **Docker compose defaults**: `ADMIN_AUTH_MODE=token` — always set `ADMIN_TOKEN` in `.env` for Docker deployments
