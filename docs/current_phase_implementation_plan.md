# Phase 1 — Implementation Plan
**Branch:** `fix/phase-1-bugfixes`
**Version bump:** `0.1.0 → 0.2.0`
**Delete this file** after phase is merged.

---

## Sub-task 1.1 — App Versioning Infrastructure

### New files
- `services/shared/src/shared/version.py`
  - `__version__ = "0.2.0"` — single source of truth for all services
- `.github/workflows/release.yml`
  - Trigger: push to `main`
  - Read version from `services/shared/src/shared/version.py` via regex
  - Skip if tag `v{version}` already exists
  - Create annotated git tag + `gh release create` with changelog from `git log --oneline <prev_tag>..HEAD`
  - Pre-release flag if version starts with `0.`

### Modified files
- `services/api/src/app/constants.py`
  - Replace `APP_VERSION = "0.1.0"` with `from shared.version import __version__ as APP_VERSION`
- `services/api/src/app/main.py`
  - Add `"version": APP_VERSION` to `/healthz` JSON response
- `services/collector/src/collector/main.py`
  - Import `__version__` from `shared.version`; log on startup
- `services/explorer/src/explorer/main.py`
  - Import `__version__`; add `templates.env.globals["version"] = __version__`
- `services/frontend/src/frontend/main.py`
  - Same pattern — pass `version` into Jinja2 globals
- `services/explorer/src/explorer/templates/base.html`
  - Add `v{{ version }}` in footer
- `services/frontend/src/frontend/templates/base.html`
  - Add `v{{ version }}` in sidebar footer
- All 4 `Dockerfile`s (`api`, `collector`, `frontend`, `explorer`)
  - Add `ARG APP_VERSION=dev` and `LABEL org.opencontainers.image.version="$APP_VERSION"`
- `pyproject.toml` for all 5 packages — kept static; version.py is the authoritative runtime source

---

## Sub-task 1.2 — Playlists Page Empty Bug

### Root cause
`ExplorerService.get_playlists()` only queries `cached_playlists` table.
Table only populated when user clicks "Fetch Tracks" on individual playlist → always empty on first visit.

### Fix
- After DB query, if result is empty OR max `updated_at` < 1 hour ago → call `_fetch_playlists_from_spotify()`
- `_fetch_playlists_from_spotify()` calls `SpotifyClient` list_playlists (paged), upserts into `cached_playlists`
- New `POST /api/me/playlists/refresh` endpoint — force refresh regardless of TTL
- Explorer "Refresh" button (HTMX POST, shows spinner)

### Modified files
- `services/api/src/app/explorer/service.py`
  - `get_playlists()`: add stale/empty check + call `_fetch_playlists_from_spotify()`
  - New `_fetch_playlists_from_spotify(user_id, session)` private method
  - New `refresh_playlists(user_id, session)` public method (called by refresh endpoint)
- `services/api/src/app/explorer/router.py`
  - Add `POST /playlists/refresh` route → `service.refresh_playlists()`
- `services/explorer/src/explorer/routes/playlists.py`
  - Add `POST /refresh` handler → calls API refresh endpoint, then redirects to `/playlists`
- `services/explorer/src/explorer/templates/playlists.html`
  - Add "Refresh" button with HTMX spinner indicator

---

## Sub-task 1.3 — Admin Logs: user_id / job_run_id Never Populated

### Root cause
`DBLogHandler.emit()` does `getattr(record, 'user_id', None)` but no caller ever sets
`extra={'user_id': ..., 'job_run_id': ...}` — so these columns are always NULL in the logs table.

### Fix — `contextvars`-based ambient logging context
- `LogContext` module-level `ContextVar`s for `user_id`, `job_run_id`, `import_job_id`
- Set once at the start of each request/job; all log calls within that async task auto-inherit
- `DBLogHandler.emit()` falls back: `getattr(record, 'user_id', None) or LogContext.get_user_id()`

### New files
- `services/shared/src/shared/logging/context.py`
  - `LogContext` class: `set_user_id()`, `get_user_id()`, `set_job_run_id()`, `get_job_run_id()`,
    `set_import_job_id()`, `get_import_job_id()`
  - Also exports `@asynccontextmanager log_context(user_id, job_run_id)` for scoped use

### Modified files
- `services/shared/src/shared/logging/handler.py`
  - Update `emit()` to fall back to `LogContext.get_user_id()` etc.
- `services/collector/src/collector/job_tracking.py`
  - `start_job()`: call `LogContext.set_user_id(user_id)` + `LogContext.set_job_run_id(job_run.id)`
- `services/api/src/app/auth/middleware.py`
  - After setting `request.state.user_id`, call `LogContext.set_user_id(request.state.user_id)`

---

## Sub-task 1.4 — Admin UI: Manual Job Trigger & Cancel

### DB change
Add `cancelled_at TIMESTAMPTZ NULL` to `job_runs` table.

### Migration
- `services/api/alembic/versions/010_job_cancellation.py`
  - `op.add_column('job_runs', sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True))`
  - Downgrade: `op.drop_column('job_runs', 'cancelled_at')`

### Cancel flow
1. Admin clicks "Cancel" on running job in jobs.html
2. `POST /admin/jobs/{job_run_id}/cancel` → sets `cancelled_at = now()` (400 if not RUNNING, 404 if not found)
3. Collector: `job_tracker.is_cancelled(job_run_id, session)` called between batches in `polling.py` and `initial_sync.py`
4. If cancelled → `job_tracker.mark_cancelled(job_run, session)` → status transitions to `CANCELLED`

### Trigger flow
- "Trigger Initial Sync" → calls existing `POST /admin/users/{user_id}/trigger-sync`
- "Trigger Poll" → new `POST /admin/users/{user_id}/trigger-poll` → resets `last_poll_completed_at = None`
  on `SyncCheckpoint`; collector picks up on next cycle

### Modified files
- `services/shared/src/shared/db/models/operations.py`
  - Add `cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)`
- `services/collector/src/collector/job_tracking.py`
  - Add `async is_cancelled(job_run_id, session) -> bool`
- `services/collector/src/collector/polling.py`
  - After each Spotify fetch page: `if await self._tracker.is_cancelled(job_run_id, session): raise JobCancelled`
- `services/collector/src/collector/initial_sync.py`
  - Between sync pages: same cancellation check
- `services/api/src/app/admin/service.py`
  - Add `cancel_job(job_run_id, session)` method
  - Add `trigger_poll(user_id, session)` method
- `services/api/src/app/admin/router.py`
  - Add `POST /jobs/{job_run_id}/cancel`
  - Add `POST /users/{user_id}/trigger-poll`
- `services/frontend/src/frontend/routes/jobs.py`
  - Add cancel + trigger-poll handlers (call AdminApiClient, redirect)
- `services/frontend/src/frontend/templates/jobs.html`
  - "Cancel" button on RUNNING rows (HTMX POST, confirms with js confirm())
  - "Trigger Poll" / "Trigger Sync" buttons in per-user dropdown or action area

---

## Files Summary

| File | Action |
|------|--------|
| `services/shared/src/shared/version.py` | CREATE |
| `.github/workflows/release.yml` | CREATE |
| `services/shared/src/shared/logging/context.py` | CREATE |
| `services/api/alembic/versions/010_job_cancellation.py` | CREATE |
| `services/api/src/app/constants.py` | MODIFY |
| `services/api/src/app/main.py` | MODIFY |
| `services/collector/src/collector/main.py` | MODIFY |
| `services/explorer/src/explorer/main.py` | MODIFY |
| `services/frontend/src/frontend/main.py` | MODIFY |
| `services/explorer/src/explorer/templates/base.html` | MODIFY |
| `services/frontend/src/frontend/templates/base.html` | MODIFY |
| `services/api/Dockerfile` | MODIFY |
| `services/collector/Dockerfile` | MODIFY |
| `services/frontend/Dockerfile` | MODIFY |
| `services/explorer/Dockerfile` | MODIFY |
| `services/api/src/app/explorer/service.py` | MODIFY |
| `services/api/src/app/explorer/router.py` | MODIFY |
| `services/explorer/src/explorer/routes/playlists.py` | MODIFY |
| `services/explorer/src/explorer/templates/playlists.html` | MODIFY |
| `services/shared/src/shared/logging/handler.py` | MODIFY |
| `services/collector/src/collector/job_tracking.py` | MODIFY |
| `services/api/src/app/auth/middleware.py` | MODIFY |
| `services/shared/src/shared/db/models/operations.py` | MODIFY |
| `services/collector/src/collector/polling.py` | MODIFY |
| `services/collector/src/collector/initial_sync.py` | MODIFY |
| `services/api/src/app/admin/service.py` | MODIFY |
| `services/api/src/app/admin/router.py` | MODIFY |
| `services/frontend/src/frontend/routes/jobs.py` | MODIFY |
| `services/frontend/src/frontend/templates/jobs.html` | MODIFY |

---

## Testing Checklist

- [ ] `docker-compose up --build` — all 5 services healthy
- [ ] `/healthz` returns `{"version": "0.2.0", ...}`
- [ ] Explorer footer shows `v0.2.0`; Admin sidebar shows `v0.2.0`
- [ ] Explorer `/playlists` loads playlists without prior "Fetch Tracks"
- [ ] "Refresh" button on playlists page re-fetches from Spotify
- [ ] Admin logs: trigger a poll job, verify `user_id` + `job_run_id` populated in Logs page
- [ ] Cancel: trigger initial sync, immediately cancel → job shows `cancelled_at`, status `CANCELLED`
- [ ] Trigger Poll: click button, verify `last_poll_completed_at` reset, collector picks up on next cycle
- [ ] `docker-compose down` after tests
