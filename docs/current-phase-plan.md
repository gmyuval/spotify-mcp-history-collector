# Phase 2 — Explorer Navigation & Browsable Collections

**Branch:** `feat/phase-2-explorer-navigation`
**Version:** 0.2.0 → 0.3.0
**PRD reference:** `docs/prd-dev-step2.md` § Phase 2

---

## Overview

Two deliverables:
1. **2.1 Clickable Dashboard Stats + `/tracks` & `/artists` pages** — all 4 stat cards become links; new paginated browse pages for tracks and artists.
2. **2.2 Customizable Time Window** — 7d/30d/90d/1y/All selector on dashboard top artists/tracks, HTMX-swapped; default increased to 10 items.

---

## File Checklist

### API layer (`services/api/`)

- [ ] `src/app/history/queries.py` — add `tracks_list(session, user_id, limit, offset, sort, q, days)` and `artists_list(...)` returning `(list[dict], int)`
- [ ] `src/app/explorer/schemas.py` — add `TrackBrowserItem`, `PaginatedTracks`, `ArtistBrowserItem`, `PaginatedArtists`
- [ ] `src/app/explorer/router.py` — add `GET /api/me/tracks` and `GET /api/me/artists`; add `days` param to dashboard endpoint
- [ ] `src/app/explorer/service.py` — parameterize `get_dashboard()` with `days`, increase top lists to 10 items

### Explorer frontend (`services/explorer/`)

- [ ] `src/explorer/api_client.py` — add `get_tracks()` and `get_artists()` methods
- [ ] **NEW** `src/explorer/routes/tracks.py` — `TracksRouter` with full page + HTMX partial
- [ ] **NEW** `src/explorer/routes/artists.py` — `ArtistsRouter` with full page + HTMX partial
- [ ] `src/explorer/routes/dashboard.py` — add `GET /dashboard/partials/top` HTMX partial route; pass `days` param
- [ ] `src/explorer/routes/__init__.py` — export `tracks_router`, `artists_router`
- [ ] `src/explorer/main.py` — register new routers, version bump `0.2.0` → `0.3.0`

### Templates (`services/explorer/src/explorer/templates/`)

- [ ] `dashboard.html` — clickable stat cards; time-window pills (7d/30d/90d/1y/All) with HTMX; `id="top-content"` swap target
- [ ] **NEW** `partials/_top_content.html` — top artists + top tracks tables (HTMX partial for time-window swap)
- [ ] **NEW** `tracks.html` — full tracks browser page
- [ ] **NEW** `artists.html` — full artists browser page
- [ ] **NEW** `partials/_tracks_table.html` — tracks table rows + pagination (HTMX partial)
- [ ] **NEW** `partials/_artists_table.html` — artists table rows + pagination (HTMX partial)
- [ ] `base.html` — add Tracks and Artists nav links

### Version bump

- [ ] `services/shared/src/shared/version.py` — `0.2.0` → `0.3.0`

---

## API Contracts

### `GET /api/me/tracks`

Query params: `limit` (default 50), `offset` (default 0), `sort` (`play_count`|`name`|`last_played`, default `play_count`), `q` (search), `days` (optional)

Response:
```json
{
  "items": [
    {
      "track_id": 123,
      "name": "string",
      "artist_name": "string",
      "play_count": 42,
      "last_played": "2026-01-01T00:00:00Z"
    }
  ],
  "total": 100,
  "limit": 50,
  "offset": 0
}
```

### `GET /api/me/artists`

Query params: `limit` (default 50), `offset` (default 0), `sort` (`play_count`|`name`, default `play_count`), `q` (search), `days` (optional)

Response:
```json
{
  "items": [
    {
      "artist_id": 456,
      "name": "string",
      "play_count": 42,
      "track_count": 8
    }
  ],
  "total": 50,
  "limit": 50,
  "offset": 0
}
```

### `GET /api/me/dashboard` changes

- Add `days` query param (default 30)
- Return top 10 artists and top 10 tracks (up from 5)

---

## UI Behavior

### Dashboard stat cards
- "Total Plays" → `<a href="/history">` wrapper
- "Unique Tracks" → `<a href="/tracks">` wrapper
- "Unique Artists" → `<a href="/artists">` wrapper
- "Hours Listened" → `<a href="/history">` wrapper

### Dashboard time-window selector
```
[7d] [30d] [90d] [1y] [All]   ← Bootstrap nav-pills
```
- Default active: 30d
- On click: `hx-get="/dashboard/partials/top?days=N" hx-target="#top-content" hx-swap="innerHTML"`
- Partial returns `_top_content.html` with top 10 artists + top 10 tracks tables + "See all" links

### `/tracks` page
- Search input: `hx-get="/tracks/partials/tracks-table" hx-trigger="keyup changed delay:500ms"`
- Sort dropdown: play_count / name / last_played
- Paginated table: Track | Artist(s) | Play Count | Last Played
- Rows link to `/tracks/{track_id}` (Phase 4 detail, so just plain `<a>` for now)

### `/artists` page
- Search input: `hx-get="/artists/partials/artists-table" hx-trigger="keyup changed delay:500ms"`
- Sort dropdown: play_count / name
- Paginated table: Artist | Play Count | Track Count
- Rows link to `/artists/{artist_id}` (Phase 4 detail, so just plain `<a>` for now)

---

## Tests

### API tests (`services/api/tests/`)
- `test_explorer_tracks.py` — list endpoint: pagination, search, sort, days filter, auth
- `test_explorer_artists.py` — list endpoint: pagination, search, sort, days filter, auth

### Explorer tests (`services/explorer/tests/`)
- `test_tracks_route.py` — full page + HTMX partial render
- `test_artists_route.py` — full page + HTMX partial render
- `test_dashboard_partial.py` — time-window partial with days param

---

## Workflow

1. Implement API layer (queries → schemas → router → service)
2. Implement explorer frontend (api_client → routes → templates)
3. Run unit tests locally
4. `docker-compose up --build` — verify all services healthy, test new pages
5. `docker-compose down`
6. Present summarized file list for approval
7. Bump version to 0.3.0, commit, push, create PR via GitHub MCP
