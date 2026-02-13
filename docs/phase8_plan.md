# Phase 8: Admin Frontend — Implementation Plan

## Context

The admin API (13 endpoints, 39 tests) is complete. The frontend service is a blank skeleton — just a FastAPI app with health and root endpoints. Phase 8 turns it into a server-rendered admin dashboard that calls the API via httpx, uses Jinja2 + HTMX + Bootstrap 5 for interactive UI, and forwards auth credentials to the API.

**Scope**: 6 pages (Dashboard, Users List, User Detail, Jobs, Imports, Logs). Analytics page deferred to post-Phase 9.

---

## Architecture

```text
Browser → Frontend (port 8001, Jinja2 + HTMX) → API (port 8000, REST JSON)
```

- Frontend never touches the database — all data flows through the admin API
- HTMX handles partial page updates (filtering, pagination, inline actions) without a JS build step
- Bootstrap 5 via CDN for styling; HTMX via CDN for interactivity
- `AdminApiClient` (httpx.AsyncClient wrapper) makes typed calls to the API
- Auth: frontend reads `ADMIN_TOKEN` from env, forwards as `Authorization: Bearer <token>` on every API call

---

## Files to Create

### 1. Foundation

| File | Purpose |
|------|---------|
| `services/frontend/src/frontend/settings.py` | `FrontendSettings(BaseSettings)` — `API_BASE_URL`, `FRONTEND_AUTH_MODE`, `ADMIN_TOKEN`, `ADMIN_USERNAME`, `ADMIN_PASSWORD` |
| `services/frontend/src/frontend/api_client.py` | `AdminApiClient` class wrapping httpx.AsyncClient with methods for all 13 admin API endpoints + `ApiError` exception |
| `services/frontend/src/frontend/routes/__init__.py` | Re-exports all route routers |
| `services/frontend/src/frontend/static/css/style.css` | Custom CSS overrides: sidebar layout, status badge colors, log level colors, toast animations |

### 2. Route Modules (one per page area)

| File | Routes | API Calls |
|------|--------|-----------|
| `routes/dashboard.py` | `GET /` (full page), `GET /partials/sync-status` (HTMX polling) | `get_sync_status()`, `list_job_runs(limit=5)`, `list_import_jobs(limit=5)` |
| `routes/users.py` | `GET /users` (list), `GET /users/{id}` (detail), `GET /partials/users-table` (HTMX), `POST /users/{id}/pause\|resume\|trigger-sync`, `DELETE /users/{id}` | `list_users()`, `get_user()`, `pause_user()`, `resume_user()`, `trigger_sync()`, `delete_user()` |
| `routes/jobs.py` | `GET /jobs` (full page), `GET /partials/jobs-table` (HTMX with filters) | `list_job_runs(**filters)` |
| `routes/imports.py` | `GET /imports` (list + upload form), `GET /partials/imports-table` (HTMX), `POST /imports/upload` | `list_import_jobs()`, `list_users()` (for dropdown), `upload_import()` |
| `routes/logs.py` | `GET /logs` (full page), `GET /partials/logs-table` (HTMX), `POST /logs/purge` | `list_logs(**filters)`, `purge_logs()` |

### 3. Templates (Jinja2)

| Template | Content |
|----------|---------|
| `templates/base.html` | Bootstrap 5 + HTMX CDN, sidebar nav (Dashboard, Users, Jobs, Imports, Logs), main content block, toast area |
| `templates/dashboard.html` | 4 stat cards (total users, active syncs, paused, errors), recent errors table, recent jobs, recent imports |
| `templates/users.html` | Users table: ID, Spotify ID, Display Name, Sync Status (badge), Last Poll, Actions |
| `templates/user_detail.html` | Profile card, sync state card, token status, action buttons (pause/resume/trigger/delete), recent jobs & imports |
| `templates/jobs.html` | Filter bar (job_type, status, user_id dropdowns), jobs table with pagination |
| `templates/imports.html` | Upload form (user dropdown + file input), filter bar, imports table |
| `templates/logs.html` | Filter bar (service, level, user_id, text search), auto-refresh toggle, logs table, purge section |

**Partials** (for HTMX swaps):

| Partial | Used By |
|---------|---------|
| `partials/_sync_status.html` | Dashboard auto-refresh (every 30s) |
| `partials/_users_table.html` | Users list pagination |
| `partials/_user_actions.html` | User detail action feedback |
| `partials/_jobs_table.html` | Jobs table filter/pagination |
| `partials/_imports_table.html` | Imports table filter/pagination |
| `partials/_logs_table.html` | Logs table filter/pagination |
| `partials/_pagination.html` | Reusable pagination controls (shared) |
| `partials/_alert.html` | Toast/notification messages |

### 4. Tests

| File | Tests (~count) | What's Tested |
|------|----------------|---------------|
| `tests/conftest.py` | — | Fixtures: mock settings, mock API client, TestClient |
| `tests/test_api_client.py` | ~12 | All client methods, auth headers, error handling, via `respx` |
| `tests/test_routes.py` | ~15 | All pages render (200), actions proxy correctly, partials return fragments |

### 5. Modified Files

| File | Change |
|------|--------|
| `services/frontend/src/frontend/main.py` | Rewrite: add Jinja2Templates, StaticFiles, lifespan (create/destroy ApiClient), register route routers, keep `/healthz` |

---

## Key HTMX Patterns

**Paginated table**: Partial endpoint returns `<tbody>` rows + out-of-band `<div id="pagination" hx-swap-oob="innerHTML">` for pagination controls.

**Filter form**: `<form hx-get="/partials/jobs-table" hx-target="#jobs-tbody" hx-trigger="change from:select, keyup changed delay:500ms from:input">` — instant filtering on dropdown change and debounced text search.

**Inline action**: `<button hx-post="/users/5/pause" hx-target="#action-result">Pause</button>` — returns success message + OOB swap to update status badge.

**Auto-refresh**: `<tbody hx-get="/partials/sync-status" hx-trigger="every 30s">` on dashboard; toggle checkbox for logs.

**Delete with confirm**: `<button hx-delete="/users/5" hx-confirm="Delete user and all data?">Delete</button>`

**File upload**: `<form hx-post="/imports/upload" hx-encoding="multipart/form-data" hx-target="#upload-result">`

---

## AdminApiClient Design

```python
class ApiError(Exception):
    status_code: int
    detail: str

class AdminApiClient:
    def __init__(self, base_url: str, auth_headers: dict[str, str]) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, headers=auth_headers, timeout=30.0)

    async def list_users(self, limit=50, offset=0) -> dict: ...
    async def get_user(self, user_id: int) -> dict: ...
    async def pause_user(self, user_id: int) -> dict: ...
    async def resume_user(self, user_id: int) -> dict: ...
    async def trigger_sync(self, user_id: int) -> dict: ...
    async def delete_user(self, user_id: int) -> dict: ...
    async def upload_import(self, user_id: int, file_content: bytes, filename: str) -> dict: ...
    async def get_import_job(self, job_id: int) -> dict: ...
    async def list_import_jobs(self, **filters) -> dict: ...
    async def get_sync_status(self) -> dict: ...
    async def list_job_runs(self, **filters) -> dict: ...
    async def list_logs(self, **filters) -> dict: ...
    async def purge_logs(self, older_than_days: int | None = None) -> dict: ...
    async def close(self) -> None: ...
```

Each method: calls the corresponding `/admin/...` endpoint, checks `response.raise_for_status()`, returns `response.json()`. Non-2xx raises `ApiError`.

---

## Implementation Order

### Sub-task 1: Foundation
Create `settings.py`, `api_client.py`, `base.html`, `style.css`, rewrite `main.py` with Jinja2/static/lifespan/routers. Add empty `routes/__init__.py`.
**Verify**: Frontend starts, `/healthz` returns 200, base template renders at `/`.

### Sub-task 2: Dashboard
Create `routes/dashboard.py`, `templates/dashboard.html`, `partials/_sync_status.html`.
**Verify**: Dashboard renders sync status cards, recent jobs/errors. HTMX polling refreshes status.

### Sub-task 3: Users (List + Detail + Actions)
Create `routes/users.py`, `templates/users.html`, `templates/user_detail.html`, partials for table/actions/pagination.
**Verify**: User list paginates, detail shows all info, pause/resume/trigger work with HTMX feedback, delete with confirmation.

### Sub-task 4: Operations (Jobs + Imports + Upload)
Create `routes/jobs.py`, `routes/imports.py`, `templates/jobs.html`, `templates/imports.html`, partials.
**Verify**: Jobs filter by type/status/user. Imports table with upload form. ZIP upload creates import job.

### Sub-task 5: Logs
Create `routes/logs.py`, `templates/logs.html`, `partials/_logs_table.html`, `partials/_alert.html`.
**Verify**: Logs filter by service/level/user/text. Auto-refresh toggle. Purge with confirmation.

### Sub-task 6: Tests
Create `tests/conftest.py`, `tests/test_api_client.py`, `tests/test_routes.py`.
**Verify**: All ~27 tests pass, ruff clean, mypy clean.

### Sub-task 7: Integration & Cleanup
Docker compose up all services. Verify all pages against real API. Update `docs/implementation_plan.md` Phase 8 status. Update `CLAUDE.md` implementation status.
**Verify**: Full test suite (199 + ~27 = ~226 tests), all linting/typing clean.

---

## Status Badge Colors (Bootstrap classes)

| Status | Badge Class | Used In |
|--------|-------------|---------|
| idle | `bg-success` (green) | Sync status |
| paused | `bg-warning text-dark` (yellow) | Sync status |
| syncing / running / processing | `bg-primary` (blue) | Sync/job/import status |
| error | `bg-danger` (red) | All error states |
| success | `bg-success` (green) | Job/import completion |
| pending | `bg-secondary` (gray) | Import pending |

## Log Level Colors

| Level | Badge Class |
|-------|-------------|
| debug | `bg-secondary` |
| info | `bg-info` |
| warning | `bg-warning text-dark` |
| error | `bg-danger` |

---

## Future Extensions (Post-Phase 9)

- **Analytics page** (`/analytics/{user_id}`) — Taste summary, top artists/tracks charts (Chart.js), listening heatmap. Calls `/mcp/call` with history tools.
- **Dark mode toggle** — Bootstrap 5 supports `data-bs-theme="dark"`.
- **Real-time log streaming** — WebSocket or SSE for live log tailing.

---

## Verification Plan

1. **Unit tests**: `pytest services/frontend/tests/ -x -q` — all pass
2. **Linting**: `ruff check services/frontend/` — clean
3. **Type checking**: `mypy services/frontend/src` — clean
4. **Docker integration**: `docker-compose up --build`, navigate to http://localhost:8001, verify all 6 pages render and interact correctly with real API data
5. **Full test suite**: API (171) + Collector (28) + Frontend (~27) = ~226 tests all passing
