# Phase 6: Public Data Exploration Frontend — Implementation Plan

## Context

Phases 0-5 are complete. Phase 6 creates a Spotify-themed **explorer** frontend where end users log in via Spotify and explore their listening data. The explorer becomes the **root app** at `/`, while the existing admin frontend moves to `/admin/*`. Cross-links connect both.

---

## Routing Layout (Production)

```
/healthz                → api:8000           (open)
/oauth2/*               → oauth2-proxy:4180  (Google OAuth infra)
/mcp/*                  → api:8000           (Bearer token only)
/auth/*                 → api:8000           (open — Spotify OAuth)
/api/*                  → api:8000           (open — JWT auth)
/admin/*                → frontend:8001      (behind Google OAuth)
/*  (everything else)   → explorer:8002      (open — JWT auth)
```

---

## Part A: API-Side Changes (`services/api/`)

### A1: Auth Redirect Support

**Problem:** OAuth callback hardcodes redirect to `/users`. Explorer needs to redirect back to itself after login.

**Files:**
- `services/api/src/app/auth/router.py` — Accept `next` query param on `/login`, carry through OAuth state, use in callback redirect
- `services/api/src/app/auth/service.py` — Carry `next` URL through the OAuth state parameter (add to `state_data` dict)
- `services/api/src/app/settings.py` — Add `AUTH_ALLOWED_REDIRECT_ORIGINS` (comma-separated whitelist, default `http://localhost:8001,http://localhost:8002`)

**Flow:**
1. Explorer links to `{API_BASE_URL}/auth/login?next={EXPLORER_URL}/`
2. API stores `next` in OAuth state dict
3. After Spotify callback, API validates `next` origin against whitelist
4. Sets JWT cookies, redirects to `next` (or `/admin` fallback if not provided)

**Security:** Validate `next` URL's origin against `AUTH_ALLOWED_REDIRECT_ORIGINS`. Reject anything not in the list.

### A2: User-Facing API Endpoints (`/api/me/`)

**New module:** `services/api/src/app/explorer/` with `__init__.py`, `router.py`, `schemas.py`, `service.py`

**Endpoints** (all require JWT + `own_data.view` permission; user_id from `request.state.user_id`):

| Endpoint | Description | Reuses |
|----------|-------------|--------|
| `GET /api/me/dashboard` | Stats + top 5 artists/tracks (30 days) | `HistoryQueries.play_stats()`, `.top_artists()`, `.top_tracks()` |
| `GET /api/me/history?limit=50&offset=0&q=` | Paginated play history | New query (A3) |
| `GET /api/me/top-artists?days=90&limit=20` | Top artists | `HistoryQueries.top_artists()` |
| `GET /api/me/top-tracks?days=90&limit=20` | Top tracks | `HistoryQueries.top_tracks()` |
| `GET /api/me/playlists` | Cached playlists | Query `CachedPlaylist` table |
| `GET /api/me/playlists/{spotify_playlist_id}` | Playlist detail with tracks | Query `CachedPlaylist` + `CachedPlaylistTrack` |

**Registration:** Add to `services/api/src/app/main.py` at prefix `/api/me`.

### A3: New Query — Paginated Recent Plays

**File:** `services/api/src/app/history/queries.py` — Add `HistoryQueries.recent_plays()`

- Joins `Play → Track → TrackArtist → Artist`
- Returns: `played_at`, `track_name`, `artist_name`, `track_id`, `ms_played`
- Supports: `limit`, `offset`, optional text search `q` (ILIKE on track name or artist name)
- Also returns total count for pagination metadata
- Ordered by `played_at DESC`

---

## Part B: Admin Frontend Prefix Migration (`services/frontend/`)

Move all admin routes from `/` to `/admin/*` so the explorer can take the root.

### B1: Settings

**File:** `services/frontend/src/frontend/settings.py` — Add `BASE_PATH` setting (default `/admin`)

### B2: Router Mount Changes

**File:** `services/frontend/src/frontend/main.py`:
- Mount all routers under `BASE_PATH`: `app.include_router(dashboard_router, prefix="/admin")`
- Mount static files at `/admin/static`
- Healthcheck stays at `/healthz` (no prefix)
- Add `base_path` as a Jinja2 global: `templates.env.globals["base_path"] = "/admin"`

### B3: Template Link Updates

**File:** `services/frontend/src/frontend/templates/base.html`:
- All sidebar `href` from `/users` → `{{ base_path }}/users`, etc.
- Static CSS from `/static/css/style.css` → `{{ base_path }}/static/css/style.css`
- Add "Explorer" link at bottom of sidebar pointing to `/`

**Other templates** (17 files): Update hardcoded internal links and HTMX `hx-get`/`hx-post` URLs to use `{{ base_path }}` prefix. Grep for `href="/` and `hx-get="/` and `hx-post="/` patterns.

### B4: Admin Frontend Tests

Update test assertions for new URL paths (redirects go to `/admin/...`).

---

## Part C: Explorer Frontend Service (`services/explorer/`)

### C1: Service Skeleton

| File | Based on | Notes |
|------|----------|-------|
| `pyproject.toml` | `services/frontend/pyproject.toml` | Deps: fastapi, uvicorn, jinja2, httpx |
| `requirements.txt` | Compiled from pyproject.toml | |
| `Dockerfile` | `services/frontend/Dockerfile` | Port 8002 |
| `src/explorer/main.py` | `frontend/main.py` | `ExplorerApp` class, injects `ExplorerApiClient` + settings |
| `src/explorer/settings.py` | `frontend/settings.py` | `API_BASE_URL`, `EXPLORER_BASE_URL` |

### C2: API Client (`ExplorerApiClient`)

**File:** `src/explorer/api_client.py`

Forwards user's JWT cookie to API as `Authorization: Bearer` header (instead of admin token). Each route handler extracts `access_token` from `request.cookies` and passes it.

Methods: `get_dashboard()`, `get_history()`, `get_top_artists()`, `get_top_tracks()`, `get_playlists()`, `get_playlist()`

### C3: Routes

| File | Routes | Description |
|------|--------|-------------|
| `routes/auth.py` | `GET /login`, `GET /logout` | Login redirects to `{API_BASE_URL}/auth/login?next={EXPLORER_URL}/`. Logout clears cookies. |
| `routes/dashboard.py` | `GET /` | Stats cards + top 5 artists/tracks |
| `routes/history.py` | `GET /history` | Paginated play history table with search |
| `routes/playlists.py` | `GET /playlists`, `GET /playlists/{id}` | Playlist grid + detail |

**Auth pattern:** Check `access_token` cookie → if missing, redirect to `/login`. Catch 401 from API → redirect to `/login`.

### C4: Templates (Spotify Dark Theme)

| Template | Content |
|----------|---------|
| `base.html` | Dark (#121212 bg, #1DB954 accents), Bootstrap 5, HTMX, top navbar with branding + logout + Admin link |
| `login.html` | Centered card with green "Login with Spotify" button |
| `dashboard.html` | 4 stat cards + top 5 artists + top 5 tracks lists |
| `history.html` | Search bar + paginated table (date, track, artist, duration) |
| `playlists.html` | Card grid (name, track count) |
| `playlist_detail.html` | Header + numbered track table |
| `partials/_history_table.html` | HTMX partial for pagination |
| `partials/_alert.html` | Error/info alerts |

### C5: Static

- `static/css/style.css` — Dark theme: `#121212` bg, `#1e1e1e` cards, `#1DB954` green, `#b3b3b3` secondary, white primary

---

## Part D: Infrastructure

### D1: Docker Compose

Add `explorer` service: port 8002, depends on api, 256m memory, hot-reload volume.
Add `http://localhost:8002` to API's `CORS_ALLOWED_ORIGINS`.

### D2: Caddyfile

Move `/auth/*` outside Google OAuth block. Add `/api/*` route. Add explorer as default handler. Admin under `/admin/*` stays behind Google OAuth.

### D3: Deploy env

- `EXPLORER_BASE_URL=https://music.praxiscode.dev`
- `AUTH_ALLOWED_REDIRECT_ORIGINS=https://music.praxiscode.dev,http://localhost:8001,http://localhost:8002`

---

## Part E: Tests

### E1: API Explorer Endpoints (`services/api/tests/test_explorer_endpoints.py`)
- Dashboard stats, history pagination, search, top artists/tracks, playlists
- 401 without JWT, 403 without permission, users see only own data

### E2: Auth Redirect (`services/api/tests/test_auth_redirect.py`)
- `next` param flows through OAuth state → callback redirect
- Invalid origins rejected, missing `next` falls back to `/admin`

### E3: Explorer Frontend (`services/explorer/tests/`)
- Mock API client, test each route renders, auth redirects

### E4: Admin Frontend Prefix
- Update existing tests for `/admin/*` paths

---

## Implementation Order

0. **Setup** — Create feature branch `feature/phase6-explorer`, save plan to `docs/phase6-plan.md`
1. **A3** — `recent_plays` query
2. **A1** — Auth redirect (`next` param)
3. **A2** — `/api/me/*` endpoints + schemas + service
4. **E1+E2** — API tests
5. **B1-B4** — Admin frontend prefix migration + test updates
6. **C1** — Explorer skeleton (main, settings, Dockerfile)
7. **C2** — ExplorerApiClient
8. **C3** — Routes
9. **C4+C5** — Templates + CSS
10. **D1+D2+D3** — Docker + Caddy
11. **E3** — Explorer tests
12. Final lint/typecheck pass

---

## Post-Deploy Verification Checklist

### Explorer
- [ ] `https://music.praxiscode.dev/` → login page
- [ ] Login with Spotify → dashboard with stats
- [ ] History page: pagination + search work
- [ ] Playlists page: grid loads, detail shows tracks
- [ ] Logout → back to login page
- [ ] Incognito → login page (not dashboard)

### Admin
- [ ] `https://music.praxiscode.dev/admin/` → Google OAuth → admin dashboard
- [ ] All admin pages work under `/admin/*`
- [ ] Sidebar links use `/admin/*` paths

### Cross-Links
- [ ] Explorer navbar has "Admin" link → `/admin/`
- [ ] Admin sidebar has "Explorer" link → `/`

### Unchanged Functionality
- [ ] MCP tools work (Bearer token)
- [ ] ChatGPT integration works
- [ ] Collector polling continues
- [ ] JWT cookie expiry (15 min) → redirect to login
