# Phase 8 — Explorer UI: Taste Profile Display + Management

## Context

Phase 7 added MCP memory tools (`memory.get_profile`, `memory.update_profile`, `memory.append_preference_event`) for ChatGPT to persist and recall user taste preferences. However, this data is only accessible via the MCP endpoint (`/mcp/call` with admin Bearer token). Users have no way to:

1. **See** what their AI assistant "knows" about their taste
2. **Edit** their taste profile manually (add/remove genres, rules, etc.)
3. **Clear** the profile and start fresh (neither via UI nor via ChatGPT)

This phase adds a Taste Profile page to the explorer UI and a `memory.clear_profile` MCP tool, giving both humans and AI assistants full control over the taste profile.

## Plan Update (Phases 8-11)

The overall plan is restructured — the old Phase 8 (Playlist Ledger) moves to Phase 9:

| Phase | Description | Status |
|-------|-------------|--------|
| 7 | MCP Memory: Taste Profile + Preference Events | **DONE** |
| **8** | **Explorer UI: Taste Profile Display + Management** | **NEXT** |
| 9 | MCP Memory: Playlist Ledger | Pending |
| 10 | MCP Memory: Search, Export/Delete & ChatGPT Integration | Pending |
| 11 | Explorer UI: Playlist Ledger Pages | Pending |

---

## Implementation Plan

### 1. New MCP Tool: `memory.clear_profile`

**File:** `services/api/src/app/mcp/tools/memory_tools.py`

Add `memory.clear_profile(user_id, clear_events?)` to `MemoryToolHandlers._register()`:
- Deletes the `TasteProfile` row for the user (resets to version 0)
- Optional `clear_events` boolean (default `false`) — if true, also deletes all `PreferenceEvent` rows
- Returns `{user_id, cleared: true, events_cleared: bool}`
- Raises `ValueError` for invalid `user_id`

**File:** `docs/chatgpt-openapi.json` — Add `memory.clear_profile` to the tool enum + `clear_events` param.

**File:** `docs/chatgpt-gpt-setup.md` — Add tool to AVAILABLE TOOLS list + instructions for when to use it.

### 2. API Endpoints for Explorer

**File:** `services/api/src/app/explorer/router.py` — Add 4 new routes:

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/me/taste-profile` | Get taste profile + recent preference events |
| `PATCH` | `/api/me/taste-profile` | Update profile via merge-patch |
| `DELETE` | `/api/me/taste-profile` | Clear profile (reset to v0) |
| `GET` | `/api/me/preference-events` | Paginated preference event history |

All gated by `RequireOwnDataView` (JWT + `own_data.view` permission).

**File:** `services/api/src/app/explorer/schemas.py` — Add response models:

```python
class TasteProfileResponse(BaseModel):
    user_id: int
    profile: dict[str, Any]
    version: int
    updated_at: str | None

class PreferenceEventItem(BaseModel):
    event_id: str
    timestamp: str
    source: str
    type: str
    payload: dict[str, Any]

class TasteProfileWithEvents(BaseModel):
    profile: TasteProfileResponse
    recent_events: list[PreferenceEventItem]

class PaginatedPreferenceEvents(BaseModel):
    items: list[PreferenceEventItem]
    total: int
    limit: int
    offset: int

class TasteProfilePatch(BaseModel):
    patch: dict[str, Any]
    reason: str | None = None
```

**File:** `services/api/src/app/explorer/service.py` — Add methods:
- `get_taste_profile(user_id, session)` → profile + 10 most recent events
- `update_taste_profile(user_id, patch, reason, session)` → updated profile
- `clear_taste_profile(user_id, session)` → deletes TasteProfile row
- `get_preference_events(user_id, session, limit, offset)` → paginated events

These methods query `TasteProfile` and `PreferenceEvent` models directly (reusing the same DB models as MCP tools, but through the explorer's own service layer).

### 3. Explorer API Client Methods

**File:** `services/explorer/src/explorer/api_client.py` — Add:

```python
async def get_taste_profile(self, access_token: str) -> dict[str, Any]
async def update_taste_profile(self, access_token: str, patch: dict, reason: str | None = None) -> dict[str, Any]
async def clear_taste_profile(self, access_token: str) -> None
async def get_preference_events(self, access_token: str, limit: int = 20, offset: int = 0) -> dict[str, Any]
```

### 4. Explorer Taste Route

**File:** `services/explorer/src/explorer/routes/taste.py` (new) — `TasteRouter` class:

| Route | Method | Purpose |
|-------|--------|---------|
| `/taste` | GET | Render taste profile page |
| `/taste/update` | POST | Handle profile edit form submission (HTMX) |
| `/taste/clear` | POST | Handle clear profile button (HTMX) |
| `/taste/partials/events` | GET | HTMX partial for paginated events |

**File:** `services/explorer/src/explorer/routes/__init__.py` — Import and export `taste_router`.

**File:** `services/explorer/src/explorer/main.py` — Register the taste router.

### 5. Explorer Templates

**File:** `services/explorer/src/explorer/templates/taste.html` (new):

Layout:
- **Header:** "Your Taste Profile" with version badge + last updated timestamp
- **Profile Section** (left column):
  - Core genres as tags/badges (with × remove buttons)
  - Avoid list as tags/badges (with × remove buttons)
  - Energy preferences as key-value display
  - Playlist rules as key-value display
  - Any other profile keys rendered as raw JSON
  - "Add" buttons for adding new genres/avoid items
  - Input fields appear via HTMX on click
- **Actions** (right column top):
  - "Clear Profile" button (red, with Bootstrap modal confirmation)
- **Preference Events** (bottom, full width):
  - Table: timestamp, type (colored badge), source (badge), payload summary
  - HTMX pagination (reuse `_pagination.html` partial)

**File:** `services/explorer/src/explorer/templates/partials/_taste_events.html` (new):
- Events table body + pagination for HTMX swapping

**File:** `services/explorer/src/explorer/templates/base.html` — Add "Taste" nav link between "Playlists" and "Profile".

### 6. Dashboard Integration

**File:** `services/explorer/src/explorer/routes/dashboard.py` — Fetch taste profile data alongside dashboard stats.

**File:** `services/explorer/src/explorer/templates/dashboard.html` — Add a "Taste Profile" summary card below the existing stats:
- Shows top genres as badges (or "No taste profile yet")
- Link to `/taste` for full details

**File:** `services/explorer/src/explorer/api_client.py` — Dashboard route will call `get_taste_profile()` (handle gracefully if no profile exists).

### 7. CSS Additions

**File:** `services/explorer/src/explorer/static/css/style.css` — Add:
- `.taste-tag` — green outline badges for genres/items with hover effects
- `.taste-tag-remove` — × button inside tags
- `.event-badge` — colored badges for event types (like=green, dislike=red, rule=blue, feedback=yellow, note=gray)

### 8. Tests

**API tests** (`services/api/tests/`):
- `test_explorer/test_taste_endpoints.py` (new) — Tests for all 4 new explorer endpoints (GET/PATCH/DELETE taste-profile, GET preference-events)
- `test_mcp/test_memory_tools.py` — Add tests for `memory.clear_profile`

**Explorer tests** (`services/explorer/tests/`):
- `test_routes.py` — Add tests for taste page, update, clear, events partial
- `conftest.py` — Add mock return values for `get_taste_profile`, `update_taste_profile`, `clear_taste_profile`, `get_preference_events`

---

## Files to Create/Modify

### New Files
| File | Purpose |
|------|---------|
| `services/explorer/src/explorer/routes/taste.py` | Taste profile route handler |
| `services/explorer/src/explorer/templates/taste.html` | Taste profile page template |
| `services/explorer/src/explorer/templates/partials/_taste_events.html` | Events table HTMX partial |
| `services/api/tests/test_explorer/test_taste_endpoints.py` | API endpoint tests |

### Modified Files
| File | Change |
|------|--------|
| `services/api/src/app/mcp/tools/memory_tools.py` | Add `memory.clear_profile` tool |
| `services/api/src/app/explorer/router.py` | Add taste profile endpoints |
| `services/api/src/app/explorer/service.py` | Add taste profile service methods |
| `services/api/src/app/explorer/schemas.py` | Add taste-related response models |
| `services/explorer/src/explorer/api_client.py` | Add taste API client methods |
| `services/explorer/src/explorer/routes/__init__.py` | Export taste router |
| `services/explorer/src/explorer/main.py` | Register taste router |
| `services/explorer/src/explorer/templates/base.html` | Add "Taste" nav link |
| `services/explorer/src/explorer/templates/dashboard.html` | Add taste summary card |
| `services/explorer/src/explorer/routes/dashboard.py` | Fetch taste data |
| `services/explorer/src/explorer/static/css/style.css` | Taste-specific styles |
| `services/explorer/tests/conftest.py` | Add mock taste API responses |
| `services/explorer/tests/test_routes.py` | Add taste route tests |
| `services/api/tests/test_mcp/test_memory_tools.py` | Add clear_profile tests |
| `docs/chatgpt-openapi.json` | Add clear_profile tool |
| `docs/chatgpt-gpt-setup.md` | Add clear_profile instructions |
| `docs/plan-v2.md` | Update implementation status + restructure phases |

---

## Verification

1. **Local Docker test** (`docker-compose up --build`):
   - Navigate to `/taste` — see empty profile or seeded profile
   - Add genres via the form → profile updates
   - Remove a genre → profile updates
   - Clear profile → profile resets to version 0
   - Check dashboard → taste summary card shows (or shows "no profile")
   - Navigate to `/taste` → preference events table shows history

2. **MCP tool test**:
   - `curl -X POST /mcp/call -d '{"tool": "memory.clear_profile", "user_id": 1}'` → clears profile
   - `curl -X POST /mcp/call -d '{"tool": "memory.get_profile", "user_id": 1}'` → version 0

3. **Test suites**:
   - `pytest services/api/tests/` — all pass
   - `pytest services/explorer/tests/` — all pass
   - `make lint && make typecheck` — clean
