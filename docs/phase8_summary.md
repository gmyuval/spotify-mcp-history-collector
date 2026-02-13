# Phase 8: Admin Frontend — Summary

## Overview

Phase 8 transforms the blank frontend skeleton into a fully functional server-rendered admin dashboard. The frontend calls the admin API (Phase 7) via httpx, renders pages with Jinja2 + Bootstrap 5, and uses HTMX for interactive filtering, pagination, and inline actions — all without a JavaScript build step.

## Architecture

```text
Browser → Frontend (port 8001, Jinja2 + HTMX) → API (port 8000, REST JSON)
```

- Frontend never touches the database — all data flows through the admin API
- `AdminApiClient` (httpx.AsyncClient wrapper) makes typed calls to all 13 API endpoints
- Auth: frontend reads `ADMIN_TOKEN` / `ADMIN_USERNAME` + `ADMIN_PASSWORD` from env, forwards as `Authorization` header on every API call
- Bootstrap 5 via CDN for styling; HTMX via CDN for interactivity

## Pages Implemented

| Page | URL | Features |
|------|-----|----------|
| Dashboard | `/` | 4 stat cards (users, active syncs, paused, errors), recent jobs, recent imports, auto-refresh every 30s |
| Users | `/users/` | Paginated table with status badges, click-through to detail |
| User Detail | `/users/{id}` | Profile card, sync state, action buttons (pause/resume/trigger-sync/delete), recent jobs & imports |
| Job Runs | `/jobs/` | Filter by job_type, status, user_id with instant HTMX filtering |
| Imports | `/imports/` | Filter bar, ZIP upload form (multipart proxy to API), imports table |
| Logs | `/logs/` | Filter by service, level, user_id, text search; auto-refresh toggle; purge with confirmation |

## Files Created (27 new)

### Foundation
- `settings.py` — `FrontendSettings(BaseSettings)` with API_BASE_URL, auth config
- `api_client.py` — `AdminApiClient` with 13 methods + `ApiError` + `build_auth_headers()`
- `static/css/style.css` — Sidebar layout, badge colors, responsive breakpoints

### Routes (5 modules)
- `routes/__init__.py` — Re-exports all routers
- `routes/dashboard.py` — Dashboard + sync status partial
- `routes/users.py` — List, detail, table partial, pause/resume/trigger-sync/delete
- `routes/jobs.py` — List + table partial with filtering
- `routes/imports.py` — List + table partial + upload proxy
- `routes/logs.py` — List + table partial + purge

### Templates (7 pages + 8 partials)
- `base.html` — Bootstrap 5 + HTMX CDN, sidebar nav, toast area
- `dashboard.html`, `users.html`, `user_detail.html`, `jobs.html`, `imports.html`, `logs.html`
- Partials: `_sync_status`, `_users_table`, `_user_actions`, `_jobs_table`, `_imports_table`, `_logs_table`, `_pagination`, `_alert`

### Tests (3 files, 40 tests)
- `conftest.py` — `mock_api` and `client` fixtures with lifespan override
- `test_api_client.py` — 19 tests: auth headers, all client methods, error handling, header forwarding
- `test_routes.py` — 21 tests: all pages, partials, actions, upload, purge, error handling

## Files Modified (3)
- `main.py` — Rewritten from skeleton to `FrontendApp` class with Jinja2, static files, lifespan, router registration
- `CLAUDE.md` — Added Phase 7 + Phase 8 status, updated test count
- `docs/implementation_plan.md` — Phase 7 marked DONE, Phase 8 marked IN PROGRESS

## HTMX Patterns Used

- **Paginated tables**: Partials return `<tbody>` rows; out-of-band `<div hx-swap-oob>` updates pagination controls
- **Filter forms**: `hx-get` with `hx-trigger="change from:select, keyup changed delay:500ms from:input"` for instant filtering
- **Inline actions**: `hx-post="/users/{id}/pause"` with `hx-target="#action-result"` for feedback
- **Auto-refresh**: `hx-trigger="every 30s"` on dashboard sync status; toggle checkbox on logs
- **Delete with confirm**: `hx-delete` with `hx-confirm` dialog
- **File upload**: `hx-post` with `hx-encoding="multipart/form-data"`

## Test Results

```text
Frontend:  40 passed (19 api_client + 21 routes)
API:      171 passed
Collector: 28 passed
Total:    239 passed
```

All linting (ruff) and type checking (mypy strict) clean.

## Docker Integration

All 4 services verified running together:
- postgres:16-alpine (healthy)
- api on port 8000 (healthy)
- frontend on port 8001 (healthy)
- collector (running)

All 6 frontend pages return 200 OK against the real API with no errors in container logs.

## What's Deferred

- **Analytics page** — Deferred to post-Phase 9 (after external system integration)
- **Dark mode toggle** — Bootstrap 5 `data-bs-theme` attribute is in base template but no toggle UI yet
