# Plan: Spotify Data Caching, RBAC Multi-User, & Data Exploration Frontend

## Context

The system currently works well for a single-admin scenario: ChatGPT calls MCP tools, which hit the Spotify API live on every request. Three gaps exist:

1. **No caching** — Every `spotify.get_playlist`, `spotify.get_track`, etc. calls the Spotify API even if we fetched the same data moments ago. This wastes API quota and adds latency.
2. **Single-user admin model** — Only one Spotify app's credentials, no user accounts, no permissions. The admin token gates everything. The user wants multi-user support with per-user Spotify app credentials and full RBAC.
3. **No data exploration UI** — Users can only interact via ChatGPT or curl. The user wants a separate public-facing frontend where logged-in users can explore their listening history, playlists, and ChatGPT-created playlists visually.

Additionally, there are **bugs to fix first**:
- The MCP router returns generic `"SpotifyRequestError: tool execution failed"` error messages, discarding the actual Spotify API error details. This makes debugging impossible.
- `spotify.add_tracks` and `spotify.get_playlist` are both returning this generic error — once we fix the error messages, we can diagnose the root cause (likely a Spotify API format change similar to the recent `items`/`track` rename).

---

## Implementation Status

| Phase | Description | Status |
|-------|-------------|--------|
| 0 | MCP Error Message Fix | **DONE** |
| 1 | Spotify Data Caching | **DONE** |
| 2 | RBAC Foundation | **DONE** |
| 3 | Per-User Spotify Credentials | **DONE** |
| 4 | JWT User Authentication | **DONE** |
| 5 | Admin UI for RBAC & User Management | **DONE** |
| 6 | Public Data Exploration Frontend | **DONE** |
| 7 | MCP Memory: Taste Profile + Preference Events | **DONE** |
| 8 | Explorer UI: Taste Profile Display + Management | **DONE** |
| 9 | MCP Memory: Playlist Ledger | **DONE** |
| 10 | MCP Memory: Search, Export/Delete & ChatGPT Integration | **DONE** |
| 11 | Explorer UI: Playlist Ledger Pages + ChatGPT OpenAPI Fix | **DONE** |
| 11.6 | Playlist Track Fidelity Fix (PR #39) | **DONE** |
| 12 | Admin-Configurable Settings | Pending |

---

## Phase 0 — ~~PR: MCP Error Message Fix (Quick Win)~~ ✅ DONE

**Problem:** The MCP router catches all exceptions and returns `f"{error_type}: tool execution failed"`, hiding the actual error. The SpotifyClient also doesn't extract error details from Spotify's response body.

### Files to modify

**`services/shared/src/shared/spotify/client.py`** — Extract Spotify error message from response body:
- In `_request()`, line 156-160: before raising `SpotifyRequestError`, try `response.json()["error"]["message"]` for the detail string
- Fallback to `response.text[:200]` if JSON parsing fails

**`services/api/src/app/mcp/router.py`** — Include actual exception message:
- Line 64: Change `f"{error_type}: tool execution failed"` → `f"{error_type}: {exc}"`
- This exposes Spotify's actual error (e.g., "Not found", "Forbidden") to the ChatGPT client

### Tests
- Update MCP router tests to verify error messages include exception details
- Add SpotifyClient test for 403/404 error message extraction

### Verification
- Deploy, trigger a bad playlist ID via ChatGPT → should see `"SpotifyRequestError: Spotify request error: HTTP 404 — Not found"` instead of `"SpotifyRequestError: tool execution failed"`
- Reproduce `spotify.add_tracks` failure → read the actual error message → fix root cause
- Reproduce `spotify.get_playlist` failure if still occurring → diagnose with real error

---

## Phase 1 — ~~PR: Spotify Data Caching (PostgreSQL)~~ ✅ DONE

**Goal:** Cache Spotify API responses in PostgreSQL so repeated requests for the same track/artist/playlist don't hit the API. Use `snapshot_id` for playlist invalidation (Spotify's built-in change detection).

### New DB tables (Alembic migration `003_spotify_cache_tables`)

**`cached_playlists`** — Playlist metadata cache:
- `id` (BigInt PK)
- `spotify_playlist_id` (String 255, unique, indexed)
- `user_id` (BigInt FK → users, indexed) — which user fetched this
- `name`, `description` (Text)
- `owner_id`, `owner_display_name` (String)
- `public`, `collaborative` (Boolean)
- `snapshot_id` (String 255) — Spotify's playlist version identifier
- `total_tracks` (Integer)
- `external_url` (String 500)
- `fetched_at` (TIMESTAMPTZ) — when we last fetched from Spotify
- `created_at`, `updated_at`

**`cached_playlist_tracks`** — Tracks within a cached playlist:
- `id` (BigInt PK)
- `cached_playlist_id` (BigInt FK → cached_playlists, CASCADE, indexed)
- `spotify_track_id` (String 255)
- `track_name` (String 500)
- `artists_json` (Text/JSON) — serialized `[{"id": ..., "name": ...}]`
- `added_at` (String) — ISO timestamp from Spotify
- `position` (Integer)

**`spotify_entity_cache`** — Generic cache for tracks, artists, albums:
- `id` (BigInt PK)
- `entity_type` (String 20: "track" | "artist" | "album")
- `spotify_id` (String 255, indexed)
- `data_json` (Text/JSON) — full cached response as JSON
- `fetched_at` (TIMESTAMPTZ)
- Unique constraint: `(entity_type, spotify_id)`

### Cache strategy

- **Playlists:** Compare `snapshot_id` from `list_playlists` response against cached value. If match → serve from cache. If different or missing → fetch from API, update cache.
- **Tracks/Artists/Albums:** TTL-based. If `fetched_at` is within `SPOTIFY_CACHE_TTL_HOURS` (default 24h, configurable) → serve from cache. Otherwise → fetch and update.
- **Write operations** (create/add/remove/update playlist): Always hit API, then invalidate cache for that playlist.

### Files to modify

**`services/shared/src/shared/db/models/cache.py`** (new) — SQLAlchemy models for cache tables

**`services/shared/src/shared/db/__init__.py`** — Import new models

**`services/api/src/app/mcp/tools/playlist_tools.py`** — Add cache layer:
- `list_playlists`: check cached_playlists table first, refresh if stale
- `get_playlist`: check snapshot_id, serve from cache or refresh
- Write tools: invalidate cache after mutation

**`services/api/src/app/mcp/tools/spotify_tools.py`** — Add cache layer:
- `get_track`, `get_artist`, `get_album`: check entity_cache, serve if within TTL

**`services/api/src/app/settings.py`** — Add `SPOTIFY_CACHE_TTL_HOURS` setting (default 24)

### Tests
- Cache hit/miss tests for each entity type
- Playlist snapshot_id invalidation test
- Write operation cache invalidation test
- TTL expiry test

### Verification
- Call `spotify.get_playlist` twice — second call should come from cache (check logs, no Spotify API call)
- Modify playlist via `spotify.add_tracks` → next `get_playlist` should refresh from API

---

## Phase 2 — ~~PR: RBAC Foundation (Roles, Permissions, DB Schema)~~ ✅ DONE

**Goal:** Add a full RBAC system with roles and granular permissions. This phase is DB schema + middleware only — no UI yet.

### Permission model

**Roles:** Named collections of permissions. Default roles:
- `admin` — Full system access (manage users, roles, all data)
- `user` — Can use own data, MCP tools, manage own playlists
- `viewer` — Read-only access to own data

**Permissions** (granular, string-based):
- `users.manage` — Create/edit/delete any user
- `users.view_all` — See all users
- `roles.manage` — Create/edit/delete roles
- `own_data.view` — View own listening history and playlists
- `own_data.export` — Export own data
- `mcp_tools.use` — Use MCP tools (ChatGPT integration)
- `playlists.write` — Create/modify playlists via MCP
- `system.sync_control` — Pause/resume/trigger sync
- `system.logs` — View and purge logs
- `system.imports` — Upload ZIP imports

### New DB tables (Alembic migration `004_rbac_tables`)

**`roles`**:
- `id` (BigInt PK)
- `name` (String 100, unique)
- `description` (Text, nullable)
- `is_system` (Boolean, default False) — protect built-in roles from deletion
- `created_at`, `updated_at`

**`permissions`**:
- `id` (BigInt PK)
- `codename` (String 100, unique) — e.g., `users.manage`
- `description` (Text)

**`role_permissions`** (junction):
- `role_id` (FK → roles)
- `permission_id` (FK → permissions)
- Composite PK

**`user_roles`** (junction):
- `user_id` (FK → users)
- `role_id` (FK → roles)
- Composite PK

Migration seeds default roles + permissions.

### Files to modify

**`services/shared/src/shared/db/models/rbac.py`** (new) — Role, Permission, RolePermission, UserRole models

**`services/shared/src/shared/db/__init__.py`** — Import RBAC models

**`services/api/src/app/auth/permissions.py`** (new) — Permission checking:
- `PermissionChecker` class with `has_permission(user_id, codename, session)` method
- FastAPI dependency `require_permission(codename)` → returns a Depends-compatible callable
- Caches user permissions per-request (avoid repeated DB queries)

**`services/api/src/app/admin/auth.py`** — Extend `require_admin`:
- Keep backward-compatible: token/basic auth still works for admin endpoints
- Add alternative: if request has a user session (JWT, see Phase 4), check RBAC permissions instead

**`services/api/src/app/mcp/router.py`** — Gate MCP tools by `mcp_tools.use` permission (after user auth is added in Phase 4)

### Tests
- Permission model tests (role has permissions, user has roles)
- `require_permission` dependency tests
- Default role seeding test

### Verification
- Migration runs cleanly on existing DB
- Existing admin token auth still works (backward compatible)
- `make lint && make typecheck && make test` all pass

---

## Phase 3 — ~~PR: Per-User Spotify App Credentials~~ ✅ DONE

**Goal:** Allow some users to use their own Spotify Developer App credentials instead of the system default. This provides rate limit isolation and lets users with their own apps connect.

### DB changes (Alembic migration `005_user_spotify_credentials`)

**Add columns to `users` table:**
- `custom_spotify_client_id` (String 255, nullable)
- `custom_spotify_client_secret_encrypted` (Text, nullable) — encrypted like refresh tokens

### Files to modify

**`services/shared/src/shared/db/models/user.py`** — Add new columns

**`services/api/src/app/auth/service.py`** — `OAuthService` changes:
- Accept optional `user_id` parameter to `get_authorization_url()` for re-auth flows
- When user has custom credentials, use those for OAuth instead of system defaults
- `handle_callback`: if custom credentials exist for user, use them for token exchange

**`services/api/src/app/auth/tokens.py`** — `TokenManager` changes:
- `refresh_access_token()`: load user's custom credentials if present, fall back to system defaults
- Pass correct `client_id`/`client_secret` to Spotify token endpoint

**`services/api/src/app/mcp/tools/playlist_tools.py`** + **`spotify_tools.py`** — `_get_client()`:
- Already creates per-user `TokenManager` + `SpotifyClient`
- Token refresh callback already handles the right user — no changes needed here (credentials are resolved in `TokenManager`)

**`services/api/src/app/admin/router.py`** — Add endpoint:
- `PUT /admin/users/{user_id}/spotify-credentials` — set custom client_id/secret (encrypted)
- `DELETE /admin/users/{user_id}/spotify-credentials` — remove custom credentials

### Tests
- Token refresh with custom vs system credentials
- OAuth flow with per-user credentials
- Admin endpoint tests for setting/removing credentials

### Verification
- User with custom credentials: OAuth + MCP tools use their credentials
- User without custom credentials: falls back to system defaults
- Credentials encrypted at rest

---

## Phase 4 — ~~PR: User Authentication (JWT + Spotify Login)~~ ✅ DONE

**Goal:** Allow end users to log in via Spotify OAuth and receive a JWT session token. This is needed for the public frontend (Phase 6) and for per-user MCP access.

### Auth flow

1. User visits `/auth/login` → redirected to Spotify
2. Callback creates/updates user + token, assigns `user` role to new users
3. Returns JWT (access token + refresh token) as HTTP-only cookies
4. Subsequent requests include JWT → middleware extracts user_id and checks permissions

### New dependencies

**`services/api/pyproject.toml`** — Add `pyjwt>=2.9.0`

### Files to modify

**`services/api/src/app/auth/jwt.py`** (new) — JWT utilities:
- `create_access_token(user_id, permissions)` → short-lived JWT (15m)
- `create_refresh_token(user_id)` → long-lived JWT (7d)
- `decode_token(token)` → payload dict
- Signing key: `TOKEN_ENCRYPTION_KEY` (reuse existing)

**`services/api/src/app/auth/middleware.py`** (new) — User auth middleware:
- Extracts JWT from `Authorization: Bearer` header or `access_token` cookie
- Sets `request.state.user_id` and `request.state.permissions`
- Does NOT enforce auth (just extracts if present)

**`services/api/src/app/auth/dependencies.py`** (new) — FastAPI dependencies:
- `get_current_user(request)` → returns user_id or raises 401
- `get_optional_user(request)` → returns user_id or None

**`services/api/src/app/auth/router.py`** — Extend callback:
- After creating user/token, generate JWT pair
- Set HTTP-only cookies
- Add `POST /auth/refresh` endpoint for JWT renewal
- Add `POST /auth/logout` endpoint (clear cookies)

**`services/api/src/app/settings.py`** — Add JWT settings:
- `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` (default 15)
- `JWT_REFRESH_TOKEN_EXPIRE_DAYS` (default 7)

### Tests
- JWT creation and validation
- Auth middleware extraction
- Login flow → JWT cookies set
- Refresh and logout endpoints
- Expired token handling

### Verification
- Login via browser → JWT cookies set
- Protected endpoint with valid JWT → success
- Protected endpoint without JWT → 401
- Existing admin token auth still works

---

## Phase 5 — PR: Admin UI for RBAC & User Management

**Goal:** Extend the existing admin frontend with pages for managing roles, permissions, and user credentials.

### API endpoints to add

**`services/api/src/app/admin/router.py`**:
- `GET /admin/roles` — List all roles with permissions
- `POST /admin/roles` — Create role
- `PUT /admin/roles/{role_id}` — Update role (name, description, permissions)
- `DELETE /admin/roles/{role_id}` — Delete non-system role
- `GET /admin/users/{user_id}/roles` — Get user's roles
- `PUT /admin/users/{user_id}/roles` — Assign roles to user
- `POST /admin/users/invite` — Create invitation link for new user (generates a one-time auth URL)

### Frontend pages

**`services/frontend/src/frontend/routes/roles.py`** (new) — Roles management page:
- List roles with their permissions (checkboxes)
- Create/edit/delete roles
- HTMX for inline editing

**`services/frontend/src/frontend/routes/users.py`** — Extend existing:
- Show user's assigned roles
- Role assignment dropdown
- Custom Spotify credentials section (set/remove)
- Invite user button

### Templates
- `roles.html` — Roles list + edit
- Update `user_detail.html` — Add roles + credentials sections

### Tests
- Role CRUD API tests
- User role assignment tests
- Frontend route tests

### Verification
- Create custom role with specific permissions
- Assign role to user
- Verify user can only access permitted resources

---

## Phase 6 — PR: Public Data Exploration Frontend (Foundation)

**Goal:** New separate service for end users to explore their listening data. Separate from admin frontend.

### New service structure

```text
services/explorer/
├── Dockerfile
├── pyproject.toml
├── requirements.txt
└── src/explorer/
    ├── main.py              # ExplorerApp (FastAPI + Jinja2)
    ├── settings.py          # ExplorerSettings
    ├── api_client.py        # Authenticated API client (uses JWT)
    ├── routes/
    │   ├── __init__.py
    │   ├── auth.py          # Login/logout (redirects to API OAuth)
    │   ├── dashboard.py     # User's listening dashboard
    │   ├── history.py       # Listening history browser
    │   ├── playlists.py     # Playlist explorer
    │   └── tracks.py        # Track/artist detail pages
    ├── templates/
    │   ├── base.html        # Layout with nav, Spotify-themed
    │   ├── login.html
    │   ├── dashboard.html
    │   ├── history.html
    │   ├── playlists.html
    │   ├── playlist_detail.html
    │   ├── track_detail.html
    │   └── partials/        # HTMX partials
    └── static/
        ├── css/style.css
        └── js/app.js
```

### Docker changes

**`docker-compose.yml`** — Add `explorer` service:
- Port 8002
- Depends on api
- Memory limit 256m

### API endpoints needed (add to api service)

**`services/api/src/app/explorer/router.py`** (new) — User-facing API:
- `GET /api/me/dashboard` — aggregated stats (total plays, top artist, hours listened)
- `GET /api/me/history` — paginated play history with track details (joins plays + tracks + artists)
- `GET /api/me/playlists` — user's cached playlists
- `GET /api/me/playlists/{id}` — playlist detail with tracks
- `GET /api/me/tracks/{id}` — track detail with play count
- All gated by JWT auth + `own_data.view` permission

### Tech stack
- FastAPI + Jinja2 + HTMX + Bootstrap 5 (same as admin frontend for consistency)
- Spotify-inspired dark theme (black/green color scheme)

### Tests
- Explorer route tests (mock API client)
- User-facing API endpoint tests
- Auth flow integration

### Verification
- Login via Spotify → redirected to dashboard
- Dashboard shows listening stats
- Can browse history, playlists, track details
- Non-authenticated users see login page

---

## Phase 7 — PR: MCP Memory: Taste Profile + Preference Events

**Goal:** Persist user taste profiles with versioned patch/merge updates, plus an append-only preference event log. Introduces the `memory.*` namespace and standard response envelope per the [MCP Memory PRD](mcp_memory_prd.md).

### New DB tables (Alembic migration `006_memory_taste`)

**`taste_profiles`** — One profile per user, versioned JSONB:
- `user_id` (BigInt FK → users, **PK** — one profile per user)
- `profile_json` (JSONB) — normalized taste data (genres, rules, preferences)
- `version` (Integer, starts at 1, incremented on each update)
- `created_at`, `updated_at` (TIMESTAMPTZ)

**`preference_events`** — Append-only event log:
- `event_id` (UUID PK, server-generated)
- `user_id` (BigInt FK → users, indexed)
- `timestamp` (TIMESTAMPTZ, defaults to now)
- `source` (VARCHAR — `user` | `assistant` | `inferred`)
- `type` (VARCHAR — `like` | `dislike` | `rule` | `feedback` | `note`)
- `payload_json` (JSONB)

### New enums (`shared/db/enums.py`)

- `PreferenceEventSource` — `user`, `assistant`, `inferred`
- `PreferenceEventType` — `like`, `dislike`, `rule`, `feedback`, `note`

### Standard response envelope (all `memory.*` tools)

```json
{"success": true, "result": {...}}
{"success": false, "error": {"code": "NOT_FOUND", "message": "..."}}
```

Error codes: `INVALID_ARGUMENT`, `NOT_FOUND`, `CONFLICT`, `INTERNAL`, `DB_ERROR`

### New MCP tools (3)

**`memory.get_profile(user_id)`** — Returns current taste profile:
- Returns `{user_id, profile, version, updated_at}` or empty profile `{}` if none exists yet

**`memory.update_profile(user_id, patch, reason?, source?, create_if_missing?)`** — Patch/merge update:
- JSON merge-patch: shallow merge of `patch` into existing `profile_json`
- Increments `version` on each update
- `create_if_missing` (default true): creates profile if it doesn't exist
- Also appends a preference event recording the `reason` for audit trail

**`memory.append_preference_event(user_id, type, payload, source?, timestamp?)`** — Append to event log:
- Records explicit user feedback, rules, likes/dislikes
- Returns `{event_id, user_id, timestamp}`

### Files to create/modify

**`services/shared/src/shared/db/models/memory.py`** (new) — TasteProfile, PreferenceEvent models
**`services/shared/src/shared/db/models/__init__.py`** — Import new models
**`services/shared/src/shared/db/enums.py`** — Add PreferenceEventSource, PreferenceEventType
**`services/api/alembic/versions/006_memory_taste.py`** — Migration
**`services/api/src/app/mcp/tools/memory_tools.py`** (new) — MemoryToolHandlers + envelope wrapper
**`services/api/src/app/mcp/tools/__init__.py`** — Import memory tools
**`docs/chatgpt-openapi.json`** — Add 3 new tools

### Example ChatGPT workflow
1. Session start: `memory.get_profile(user_id=1)` → recall previous profile
2. User says "I like upbeat symphonic metal with breathers":
   - `memory.append_preference_event(user_id=1, type="rule", payload={"raw_text": "upbeat symphonic metal with breathers"}, source="user")`
   - `memory.update_profile(user_id=1, patch={"core_genres": ["symphonic metal"], "energy_preferences": {"default": "upbeat", "contemplative_breaks": true}}, reason="User stated genre + energy preference")`

### Tests
- Profile create (first update), get, patch/merge, version increment
- Preference event append + chronological retrieval
- Response envelope format (success + error cases)
- User isolation (can't read another user's profile)
- `create_if_missing=false` returns NOT_FOUND

### Verification
- `POST /mcp/call {"tool": "memory.update_profile", ...}` creates profile
- `POST /mcp/call {"tool": "memory.get_profile", ...}` returns it
- Profile version increments on each update
- Preference events accumulate, ordered by timestamp

---

## Phase 8 — ~~PR: Explorer UI: Taste Profile Display + Management~~ ✅ DONE

**Goal:** Give users visibility and control over their AI-curated taste profile through the explorer UI. Also adds a `memory.clear_profile` MCP tool for ChatGPT to reset profiles on request.

Detailed plan: [`docs/phase8-taste-ui-plan.md`](phase8-taste-ui-plan.md)

### Summary of what was implemented

**New MCP tool:** `memory.clear_profile(user_id, clear_events?)` — deletes the TasteProfile row (resets to v0), optionally clears all PreferenceEvent rows.

**New API endpoints** (gated by JWT + `own_data.view`):

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/me/taste-profile` | Get taste profile + recent preference events |
| `PATCH` | `/api/me/taste-profile` | Update profile via merge-patch |
| `DELETE` | `/api/me/taste-profile` | Clear profile (reset to v0) |
| `GET` | `/api/me/preference-events` | Paginated preference event history |

**New explorer pages:**
- `/taste` — Full taste profile page with genre/avoid tag management, energy preferences, playlist rules, and "Other Preferences" catch-all
- `/taste/update` (POST) — Add/remove/set profile fields
- `/taste/clear` (POST) — Clear entire profile with modal confirmation
- `/taste/partials/events` — HTMX partial for paginated preference event history

**Dashboard integration:** Taste summary card on dashboard showing top genres (or "No taste profile yet") with link to `/taste`.

**ChatGPT updates:** `memory.clear_profile` added to OpenAPI schema and GPT instructions with usage guidance ("forget everything", "reset my profile", etc.).

### Files created/modified

See [`docs/phase8-taste-ui-plan.md`](phase8-taste-ui-plan.md) for the full file list. Key new files:
- `services/explorer/src/explorer/routes/taste.py`
- `services/explorer/src/explorer/templates/taste.html`
- `services/explorer/src/explorer/templates/partials/_taste_events.html`
- `services/api/tests/test_explorer/test_taste_endpoints.py`

---

## Phase 9 — ~~PR: MCP Memory: Playlist Ledger~~ ✅ DONE

**Goal:** Track all assistant-created/edited playlists with full event history and snapshot-based reconstruction. The ledger is the canonical record even when Spotify read-back is blocked.

Detailed plan: [`docs/phase9-playlist-ledger-plan.md`](phase9-playlist-ledger-plan.md)

### Summary of what was implemented

**New DB tables** (Alembic migration `007_playlist_ledger`): `memory_playlists`, `playlist_snapshots`, `playlist_events` with circular FK handling (`use_alter=True`) and composite index on `(playlist_id, timestamp)`.

**New enums:** `PlaylistSnapshotSource` (create/periodic/manual), `PlaylistEventType` (ADD_TRACKS/REMOVE_TRACKS/REORDER/UPDATE_META).

**New MCP tools (5):**

| Tool | Purpose |
|------|---------|
| `memory.log_playlist_create` | Log newly created playlist with initial track list. Idempotent via `idempotency_key`. |
| `memory.log_playlist_mutation` | Log add/remove/reorder/meta mutations. Auto-snapshot compaction every 10 events. Idempotent via `client_event_id`. |
| `memory.get_playlists` | List tracked playlists with cursor-based pagination. |
| `memory.get_playlist` | Full detail: metadata + latest snapshot + recent events. |
| `memory.reconstruct_playlist` | Rebuild track list from snapshot + event replay. Supports point-in-time `at_time`. |

**Reconstruction logic:** `ReconstructionResult` NamedTuple, event replay (ADD_TRACKS with insert-at-position, REMOVE_TRACKS via set filter, REORDER replaces list, UPDATE_META skipped).

**ChatGPT updates:** OpenAPI schema with 5 tools + 9 parameters, GPT setup guide with PLAYLIST MEMORY workflow section.

**Ruff `ARG` lint rule:** Added unused-arguments detection to pre-commit, with per-file-ignores for pytest fixtures.

### Files created/modified

See [`docs/phase9-playlist-ledger-plan.md`](phase9-playlist-ledger-plan.md) for the full file list. Key new files:
- `services/api/src/app/mcp/tools/playlist_ledger_tools.py`
- `services/api/alembic/versions/007_playlist_ledger.py`
- `services/api/tests/test_mcp/test_playlist_ledger_tools.py` (38 tests)

---

## Phase 10 — ~~PR: MCP Memory: Search, Export/Delete & ChatGPT Integration~~ ✅ DONE

**Goal:** Cross-memory search, data portability (export + delete), and full ChatGPT GPT integration with tool-calling playbook.

### Summary of what was implemented

**New MCP tools (3):**

| Tool | Purpose |
|------|---------|
| `memory.search` | Keyword search across playlists (name/description/tags), preference events (payload), and taste profile (JSON content). Returns ranked results with scores, snippets, and metadata. Deduplicates playlist matches. |
| `memory.export_user_data` | Full JSON export of all memory: profile, preference events, playlists, snapshots, playlist events. |
| `memory.delete_user_data` | Hard delete all memory data. Requires `confirm=true` safety guard. Handles circular FK constraints. |

**Search scoring:** Playlist name match (1.0), description (0.8), tags (0.7), preference event (0.5), profile (0.3).

**ChatGPT updates:** OpenAPI schema with 3 tools + 2 parameters (`query`, `confirm`). GPT instructions updated with search/export/delete guidance, conversation starter added.

### Files created/modified

- `services/api/src/app/mcp/tools/memory_data_tools.py` (new) — Tool handlers
- `services/api/tests/test_mcp/test_memory_data_tools.py` (new) — 23 tests
- `services/api/src/app/mcp/tools/__init__.py` — Import new module
- `docs/chatgpt-openapi.json` — 3 tools + 2 params
- `docs/chatgpt-gpt-setup.md` — Search/export/delete guidance + changelog

---

## Phase 11 — ~~PR: Explorer UI: Playlist Ledger Pages + ChatGPT OpenAPI Fix~~ ✅ DONE

Explorer UI for browsing assistant-tracked playlists from the memory ledger, plus a ChatGPT OpenAPI schema fix for JSON parameter typing.

**API:** 3 new endpoints — `GET /api/me/memory-playlists` (list), `GET /api/me/memory-playlists/{id}` (detail with tracks + events), `GET /api/me/memory-playlists/{id}/events` (paginated events). Service layer queries `MemoryPlaylist`, `PlaylistSnapshot`, `PlaylistEvent` with user ownership checks.

**Explorer:** New `MemoryPlaylistsRouter` at `/playlists/memory` with list, detail, and HTMX events partial. 3 new templates + 3 new API client methods. Dashboard card shows up to 5 recent AI playlists. Cross-link button between Spotify playlists and AI playlists pages.

**ChatGPT fix:** Updated `chatgpt-openapi.json` — changed `patch`, `payload`, `intent_tags`, `seed_context` from `"type": "string"` to `oneOf` (object/array + string) so ChatGPT can send native JSON objects instead of only serialized strings.

**Tests:** 13 API endpoint tests (list/detail/events with pagination, auth, user isolation) + 8 explorer route tests (pages, partials, auth, dashboard integration).

---

## Phase 11.5 — PR: Playlist Track Access (Embed Fallback + Backfill Tool)

**Goal:** Solve the Spotify Development Mode 403 restriction on `GET /playlists/{id}/tracks` by using Spotify's embed endpoint as a fallback for track data. Add a `memory.backfill_playlist` tool so ChatGPT can import existing playlists into the memory ledger in a single call. Add admin cache management endpoints.

**Background:** Spotify Development Mode blocks `GET /playlists/{id}` and `/tracks` endpoints (requires Extended Quota Mode, impractical to obtain). However, Spotify's embed page (`/embed/playlist/{id}`) returns complete track listings in its `__NEXT_DATA__` JSON — no auth required. Tested and confirmed working. PR #37 added graceful 403 degradation; this phase adds the embed fallback to actually retrieve tracks.

### Embed-based playlist track fetcher (new module)

**`services/shared/src/shared/spotify/embed.py`**:
- `SpotifyEmbedClient` with `async fetch_playlist_tracks(playlist_id) -> list[EmbedTrackItem]`
- Fetches `https://open.spotify.com/embed/playlist/{id}` via httpx
- Parses `__NEXT_DATA__` JSON blob, extracts `trackList` array
- Returns: `track_id`, `name`, `artists` (list[str]), `duration_ms` per track
- Rate limiting: minimum 2s between requests
- New exception: `SpotifyEmbedError` in `exceptions.py`

### Wire embed fallback into `spotify.get_playlist`

**`services/api/src/app/mcp/tools/playlist_tools.py`** (modify):
- When `get_playlist_all_tracks()` returns 403, fall back to embed fetcher
- Convert embed results to same dict format as API tracks
- Add `tracks_source` field in response: `"api"` or `"embed"`
- Cache results normally

### New MCP tool: `memory.backfill_playlist`

**`services/api/src/app/mcp/tools/playlist_ledger_tools.py`** (modify):
- **Inputs:** `user_id`, `playlist_id`, `intent_tags` (optional), `seed_context` (optional), `idempotency_key` (optional)
- **Flow:**
  1. Check if playlist already exists in memory (idempotent — return existing)
  2. Fetch playlist via `spotify.get_playlist` tool handler internally (API or embed)
  3. Create MemoryPlaylist + initial PlaylistSnapshot (source: `BACKFILL`)
  4. Return: `playlist_id`, `name`, `snapshot_id`, `stored_track_count`, `tracks_source`
- New enum value: `PlaylistSnapshotSource.BACKFILL = "backfill"`

### Admin cache invalidation endpoints

**`services/api/src/app/admin/router.py`** (modify):
- `POST /admin/cache/playlists/invalidate` — body: `{user_id, playlist_id?}` — invalidate single or all playlist caches
- `POST /admin/cache/all/invalidate` — body: `{user_id}` — clear all caches for user

### Files to create

- `services/shared/src/shared/spotify/embed.py` — Embed track fetcher
- `services/api/tests/test_spotify/test_embed.py` — Embed fetcher unit tests
- `services/api/tests/test_mcp/test_backfill_tool.py` — Backfill tool tests
- `services/api/tests/test_admin/test_cache_invalidation.py` — Cache admin tests

### Files to modify

- `services/shared/src/shared/spotify/__init__.py` — Export embed module
- `services/shared/src/shared/spotify/exceptions.py` — Add `SpotifyEmbedError`
- `services/shared/src/shared/db/enums.py` — Add `BACKFILL` to `PlaylistSnapshotSource`
- `services/api/src/app/mcp/tools/playlist_tools.py` — Embed fallback in `get_playlist`
- `services/api/src/app/mcp/tools/playlist_ledger_tools.py` — Add `backfill_playlist` tool
- `services/api/src/app/admin/router.py` — Cache invalidation endpoints
- `services/api/tests/test_mcp/test_playlist_tools.py` — Update tests for embed fallback
- `docs/chatgpt-openapi.json` — Add `memory.backfill_playlist` tool
- `docs/chatgpt-tool-catalog.md` — Add tool entry
- `docs/chatgpt-gpt-setup.md` — Update changelog

### Tests

- Embed fetcher: successful parse, HTTP errors, malformed HTML, missing trackList
- `spotify.get_playlist`: API success (no embed), API 403 with embed fallback, both fail
- `memory.backfill_playlist`: success, already-exists (idempotent), empty playlist, Spotify error
- Admin cache invalidation: single playlist, all playlists, all caches, invalid user

### Verification

- `pytest services/api/tests/` — all pass
- `ruff check` + `mypy` — clean
- Deploy to production, verify `spotify.get_playlist` returns tracks via embed

---

## Phase 12 — DONE: Admin-Configurable Settings + Private Playlist Fix

**Goal:** Replace hardcoded constants (magic numbers) across the codebase with a DB-backed settings system, manageable through the admin UI. This includes search parameters, limits, scoring weights, and other operational tunables that are currently embedded as constants.

### New DB table (Alembic migration `008_app_settings`)

**`app_settings`** — Key-value settings store:
- `key` (String 100, **PK**) — setting identifier, e.g. `search.max_query_length`
- `value_json` (JSONB) — the setting value (supports int, float, string, list, dict)
- `description` (Text, nullable) — human-readable explanation
- `category` (String 50) — grouping for admin UI (e.g. `search`, `limits`, `scoring`)
- `updated_at` (TIMESTAMPTZ) — last modification time

Migration seeds default values for all existing constants.

### Settings to migrate

**Memory search (`memory_data_tools.py`):**
- `search.max_query_length` (default 500)
- `search.default_limit` (default 25)
- `search.max_limit` (default 200)
- `search.snippet_max_length` (default 100)
- `search.score_playlist_name` (default 1.0)
- `search.score_playlist_description` (default 0.8)
- `search.score_playlist_tags` (default 0.7)
- `search.score_preference_event` (default 0.5)
- `search.score_profile` (default 0.3)

**Playlist ledger (`playlist_ledger_tools.py`):**
- `playlist.snapshot_compaction_threshold` (default 10)
- `playlist.default_page_size` (default 20)
- `playlist.max_page_size` (default 100)
- `playlist.recent_events_limit` (default 20)

**Other candidates:** Cache TTLs, rate limits, JWT expiry times — evaluate during implementation.

### API endpoints (admin)

- `GET /admin/settings` — List all settings, grouped by category
- `GET /admin/settings/{key}` — Get single setting
- `PUT /admin/settings/{key}` — Update setting value (validates type matches default)
- `POST /admin/settings/reset` — Reset all to defaults (or specific key)

### Settings service

**`services/api/src/app/admin/settings_service.py`** (new):
- `SettingsService` class with async methods
- In-memory cache with TTL (avoids DB query on every tool call)
- `get(key, default)` → returns typed value
- `set(key, value)` → validates, updates, invalidates cache
- `get_all(category?)` → for admin listing

### Admin UI page

**`/admin/settings`** — Settings management page:
- Grouped by category (accordion/tabs)
- Inline editing with type-appropriate inputs (number, text, JSON)
- Reset-to-default button per setting
- HTMX for save without full-page reload

### Files to create/modify

**New files:**
- `services/shared/src/shared/db/models/settings.py` — AppSetting model
- `services/api/src/app/admin/settings_service.py` — Settings service with caching
- `services/api/src/app/admin/settings_router.py` — Admin API endpoints
- `services/frontend/src/frontend/routes/settings.py` — Admin UI route
- `services/frontend/src/frontend/templates/settings.html` — Template
- `services/api/alembic/versions/008_app_settings.py` — Migration
- `services/api/tests/test_admin/test_settings.py` — Tests

**Modified files:**
- `services/api/src/app/mcp/tools/memory_data_tools.py` — Use settings service
- `services/api/src/app/mcp/tools/playlist_ledger_tools.py` — Use settings service
- `services/shared/src/shared/db/__init__.py` — Export new model
- `services/api/src/app/admin/router.py` — Include settings router

### Tests
- Settings CRUD API tests
- Cache invalidation on update
- Default value seeding
- Tool handlers respect runtime settings changes
- Admin UI route tests

### Verification
- Change `search.default_limit` via admin UI → verify `memory.search` uses new value
- Reset to defaults → values restored
- Settings survive app restart (persisted in DB)

---

## Implementation Order & Dependencies

```text
Phase 0  (error fix)                        ✅ DONE
Phase 1  (caching)                          ✅ DONE
Phase 2  (RBAC schema)                      ✅ DONE
Phase 3  (per-user creds)                   ✅ DONE
Phase 4  (JWT auth)                         ✅ DONE
Phase 5  (admin RBAC UI)                    ✅ DONE
Phase 6  (explorer foundation)              ✅ DONE
Phase 7  (taste profile + events)           ✅ DONE
Phase 8  (explorer taste UI)                ✅ DONE
Phase 9  (playlist ledger)                  ✅ DONE
Phase 10 (search, export/delete, ChatGPT)   ✅ DONE
Phase 11 (explorer UI: playlist ledger)     ✅ DONE
Phase 12 (admin-configurable settings)      ✅ DONE
```

All planned phases complete.

---

## Key Design Decisions

1. **PostgreSQL for caching** — No Redis needed. Cache tables are simple, queries are fast at this scale, and it avoids infrastructure complexity.
2. **Playlist snapshot_id for invalidation** — Spotify provides `snapshot_id` that changes on any playlist modification. This is more reliable than TTL for playlists.
3. **TTL for tracks/artists/albums** — These change rarely. 24h default TTL is reasonable. Configurable via `SPOTIFY_CACHE_TTL_HOURS`.
4. **Full RBAC over simple roles** — More complex but future-proof. String-based permission codenames are easy to check and extend.
5. **JWT for user sessions** — Stateless auth that works across services. HTTP-only cookies for browser security.
6. **Per-user Spotify credentials** — Optional override at user level. System defaults used when not set. Credentials encrypted at rest (same pattern as refresh tokens).
7. **Separate explorer service** — Clean separation: admin frontend for ops, explorer for end users. Different auth models, different audiences.
8. **`memory.*` namespace** — All memory tools under one namespace per the MCP Memory PRD. Standard response envelope (`{success, result?, error?}`) for consistency.
9. **Versioned taste profile** — Single JSONB profile per user with version counter. JSON merge-patch for updates. Append-only preference events capture raw feedback; profile captures normalized rules.
10. **Playlist ledger with snapshots** — Snapshot + event sourcing pattern. Snapshots at create + every N mutations for fast reconstruction. Ledger is canonical record even when Spotify read-back fails.
11. **Idempotency** — `idempotency_key` for playlist create, `client_event_id` for mutations. Prevents duplicates from retries.
12. **DB-backed settings over env vars** — Operational tunables (search limits, scoring weights, compaction thresholds) belong in a DB settings table with admin UI, not env vars that require redeployment. In-memory cache with TTL avoids per-request DB queries.
