# Phase 12 — Admin-Configurable Settings + Private Playlist Fix

## Overview

Two concerns addressed in this phase:

1. **Private Playlist Workaround (Part A):** Spotify Development Mode 403 + private playlist
   embed failure means tracks are unretrievable for private playlists. Fix: add `track_ids`
   override to `memory.backfill_playlist` so ChatGPT can provide IDs directly.

2. **Admin-Configurable Settings (Part B):** Replace hardcoded constants (search limits, scoring
   weights, compaction thresholds) with a DB-backed settings table, manageable via admin UI.

---

## Part A — Private Playlist Workaround

### Root Cause

- Spotify Development Mode 403 blocks `GET /playlists/{id}/tracks` for all callers.
- `playlist-read-private` IS in our OAuth scopes — the 403 is not a scope issue.
- Embed fallback (`open.spotify.com/embed/playlist/{id}`) only works for **public** playlists.
  Private playlists require Spotify auth on the embed page — unauthenticated scrape fails.
- Result: `tracks_restricted: true`, `stored_track_count: 0` in backfill.

### Fix 1 — `track_ids` + `name` overrides in `memory.backfill_playlist`

Add optional parameters:
- `track_ids: list[str]` — if provided, skip Spotify fetch entirely; use these IDs directly.
  Tracks source becomes `"manual"`.
- `name: str` — optional name override if metadata also fails.

When `track_ids` is provided:
1. Skip `playlist_handlers.get_playlist()` call.
2. Attempt metadata fetch only (for name/description) — tolerate failure if `name` override given.
3. Create MemoryPlaylist + PlaylistSnapshot with the provided track IDs.

### Fix 2 — Better `tracks_restricted_reason` for private playlists

In `playlist_tools.py`, when both API and embed fail, detect private playlist:
- Check `pl.public is False` (from API metadata) or cached metadata `public == False`.
- If private: include in error message — "Private playlist: embed requires auth. If track IDs
  are known, use `memory.backfill_playlist` with explicit `track_ids` to log the playlist."

### Fix 3 — Docs

- `docs/chatgpt-openapi.json` — add `track_ids` and `name` params to `memory.backfill_playlist`.
- `docs/chatgpt-gpt-setup.md` — guidance: for private playlists where tracks are restricted,
  use `memory.backfill_playlist` with explicit `track_ids`.

---

## Part B — Admin-Configurable Settings

### B1. DB Model

**New file: `services/shared/src/shared/db/models/settings.py`**

```python
class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str]          # PK — e.g. "search.default_limit"
    value_json: Mapped[Any]   # JSONB (int, float, str, list, dict)
    description: Mapped[str | None]
    category: Mapped[str]     # "search" | "playlist"
    updated_at: Mapped[datetime]
```

Export from:
- `services/shared/src/shared/db/models/__init__.py`
- `services/shared/src/shared/db/__init__.py`

### B2. Alembic Migration `009_app_settings`

Creates `app_settings` table and seeds defaults:

| Key | Default | Category | Description |
|-----|---------|----------|-------------|
| `search.max_query_length` | 500 | search | Max search query length |
| `search.default_limit` | 25 | search | Default results per search |
| `search.max_limit` | 200 | search | Max results per search |
| `search.snippet_max_length` | 100 | search | Max chars per snippet |
| `search.score_playlist_name` | 1.0 | search | Score weight — name match |
| `search.score_playlist_description` | 0.8 | search | Score weight — description match |
| `search.score_playlist_tags` | 0.7 | search | Score weight — tags match |
| `search.score_preference_event` | 0.5 | search | Score weight — preference event match |
| `search.score_profile` | 0.3 | search | Score weight — profile match |
| `playlist.snapshot_compaction_threshold` | 10 | playlist | Auto-snapshot every N mutations |
| `playlist.default_page_size` | 50 | playlist | Default `get_playlists` page size |
| `playlist.max_page_size` | 200 | playlist | Max `get_playlists` page size |
| `playlist.recent_events_limit` | 50 | playlist | Default events in `get_playlist` |

### B3. SettingsService

**New file: `services/api/src/app/admin/settings_service.py`**

Singleton with in-process TTL cache (5 min default):

```python
class SettingsService:
    DEFAULTS: dict[str, tuple[Any, str, str]]  # key → (default, description, category)
    _CACHE_TTL = 300  # seconds

    async def get(self, key: str, default: Any, session: AsyncSession) -> Any
    async def set(self, key: str, value: Any, session: AsyncSession) -> AppSetting
    async def get_all(self, session: AsyncSession, category: str | None = None) -> list[AppSetting]
    async def reset_to_default(self, key: str | None, session: AsyncSession) -> int
    def invalidate_cache(self, key: str | None = None) -> None

_settings_service = SettingsService()  # module-level singleton
```

Cache: `dict[str, tuple[Any, float]]` (value, expiry timestamp). Falls back to DEFAULTS if
DB unreachable — ensures resilience during startup or migrations.

### B4. Admin API

**New file: `services/api/src/app/admin/settings_router.py`**

Class-based `SettingsRouter`, mounted under `/admin`:

```text
GET  /admin/settings          → list all, grouped by category
GET  /admin/settings/{key}    → single setting with default_value included
PUT  /admin/settings/{key}    → body: {value_json} → update + invalidate cache
POST /admin/settings/reset    → body: {key?: str} → reset one or all to defaults
```

**Modified: `services/api/src/app/admin/router.py`** — include settings router.

**Modified: `services/api/src/app/admin/schemas.py`** — add Pydantic models:
- `SettingDetail` — key, value_json, description, category, updated_at, default_value
- `SettingsListResponse` — `{by_category: {search: [...], playlist: [...]}}`
- `UpdateSettingRequest` — `{value_json: Any}`
- `ResetSettingsRequest` — `{key: str | None}`

### B5. Wire into Tool Handlers

**`services/api/src/app/mcp/tools/memory_data_tools.py`:**
- Import `_settings_service`
- In `search()`: replace all hardcoded limits and score constants with settings lookups
- `_snippet()` stays as a static helper; max_len now passed from settings

**`services/api/src/app/mcp/tools/playlist_ledger_tools.py`:**
- Import `_settings_service`
- Replace `_COMPACTION_THRESHOLD = 10` → read from settings per call in `_maybe_compact()`
- Replace hardcoded page sizes in `get_playlists()` and `get_playlist()`

### B6. Admin Frontend Page

**New file: `services/frontend/src/frontend/routes/settings.py`** — `SettingsRouter`:
- `GET /admin/settings` → settings page
- `POST /admin/settings/{key}` → HTMX update (returns updated row partial)
- `POST /admin/settings/{key}/reset` → HTMX reset to default

**New file: `services/frontend/src/frontend/templates/settings.html`:**
- Bootstrap accordion, one card per category
- Per row: label, description, type-aware input (number for int/float, text for str, JSON for
  object/array), HTMX inline save, "Reset" button
- Success/error flash via HTMX OOB swap

**Modified: `services/frontend/src/frontend/templates/base.html`** — add "Settings" nav link.

**Modified: `services/frontend/src/frontend/main.py`** — mount settings route.

### B7. Tests

**New file: `services/api/tests/test_admin/test_settings.py`:**
- Default value returned when key not in DB (DEFAULTS fallback)
- Update setting → cache invalidated → next get returns new value
- List all → grouped by category, all 13 keys present
- Reset single key → value back to default
- Reset all → all keys at default
- Invalid key → 404 on GET/PUT

**New file: `services/frontend/tests/test_settings.py`:**
- Settings page loads, shows all categories
- Auth required (redirect if not admin)

**Updated: `services/api/tests/test_mcp/test_backfill_tool.py`:**
- Test `track_ids` override: provides IDs directly → stored without Spotify fetch
- Test `name` override: used when metadata unavailable

---

## Files Added / Modified

### New files

| File | Purpose |
|------|---------|
| `services/shared/src/shared/db/models/settings.py` | AppSetting ORM model |
| `services/api/alembic/versions/009_app_settings.py` | Migration + seed |
| `services/api/src/app/admin/settings_service.py` | SettingsService + singleton |
| `services/api/src/app/admin/settings_router.py` | Admin settings API |
| `services/frontend/src/frontend/routes/settings.py` | Admin UI route |
| `services/frontend/src/frontend/templates/settings.html` | Settings page template |
| `services/api/tests/test_admin/test_settings.py` | API tests |
| `services/frontend/tests/test_settings.py` | Frontend tests |
| `docs/phase12-settings-plan.md` | This document |

### Modified files

| File | Change |
|------|--------|
| `services/shared/src/shared/db/models/__init__.py` | Export AppSetting |
| `services/shared/src/shared/db/__init__.py` | Import AppSetting model |
| `services/api/src/app/admin/router.py` | Include settings router |
| `services/api/src/app/admin/schemas.py` | Add settings Pydantic models |
| `services/api/src/app/mcp/tools/memory_data_tools.py` | Use SettingsService |
| `services/api/src/app/mcp/tools/playlist_ledger_tools.py` | Use SettingsService + `track_ids` override |
| `services/api/src/app/mcp/tools/playlist_tools.py` | Private playlist error message |
| `services/frontend/src/frontend/main.py` | Mount settings route |
| `services/frontend/src/frontend/templates/base.html` | Add Settings nav link |
| `docs/chatgpt-openapi.json` | Add `track_ids`/`name` to backfill_playlist |
| `docs/chatgpt-gpt-setup.md` | Private playlist guidance + Phase 12 changelog |
| `docs/plan-v2.md` | Mark Phase 12 DONE |

---

## Implementation Order

1. DB model + shared exports
2. Migration 009
3. SettingsService
4. Admin API (schemas + router)
5. Wire tool handlers + private playlist fixes
6. Frontend settings page
7. Tests
8. Docs

---

## Verification

- Change `search.default_limit` to 5 via admin UI → `memory.search` returns at most 5 results.
- Reset to defaults → value restored, survives app restart (DB-persisted).
- `memory.backfill_playlist` with `track_ids=["id1","id2",...]` for private playlist
  → creates ledger entry with those IDs, `tracks_source: "manual"`.
- Private playlist `spotify.get_playlist` → improved error message includes backfill hint.
