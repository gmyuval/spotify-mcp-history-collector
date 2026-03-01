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
| 8 | Explorer UI: Taste Profile Display + Management | **NEXT** |
| 9 | MCP Memory: Playlist Ledger | Pending |
| 10 | MCP Memory: Search, Export/Delete & ChatGPT Integration | Pending |
| 11 | Explorer UI: Playlist Ledger Pages | Pending |

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

## Phase 8 — PR: MCP Memory: Playlist Ledger

**Goal:** Track all assistant-created/edited playlists with full event history and snapshot-based reconstruction. The ledger is the canonical record even when Spotify read-back is blocked.

### New DB tables (Alembic migration `007_playlist_ledger`)

**`memory_playlists`** — Playlist metadata:
- `playlist_id` (VARCHAR PK — Spotify playlist ID)
- `user_id` (BigInt FK → users, indexed)
- `name`, `description` (Text)
- `intent_tags` (JSONB, default `[]`) — e.g., `["upbeat", "symphonic metal"]`
- `seed_context` (JSONB, default `{}`) — what inspired the playlist
- `latest_snapshot_id` (UUID FK → playlist_snapshots, nullable)
- `created_at`, `updated_at` (TIMESTAMPTZ)

**`playlist_snapshots`** — Point-in-time track lists:
- `snapshot_id` (UUID PK)
- `playlist_id` (VARCHAR FK → memory_playlists, indexed)
- `created_at` (TIMESTAMPTZ)
- `track_ids` (JSONB) — ordered array of Spotify track IDs
- `source` (VARCHAR — `create` | `periodic` | `manual`)

**`playlist_events`** — Append-only mutation ledger:
- `event_id` (UUID PK)
- `playlist_id` (VARCHAR FK → memory_playlists, indexed)
- `user_id` (BigInt FK → users)
- `timestamp` (TIMESTAMPTZ)
- `type` (VARCHAR — `ADD_TRACKS` | `REMOVE_TRACKS` | `REORDER` | `UPDATE_META`)
- `payload_json` (JSONB) — type-specific payload
- `client_event_id` (UUID, nullable) — for idempotency

### New enums

- `PlaylistSnapshotSource` — `create`, `periodic`, `manual`
- `PlaylistEventType` — `ADD_TRACKS`, `REMOVE_TRACKS`, `REORDER`, `UPDATE_META`

### New MCP tools (5)

**`memory.log_playlist_create(user_id, playlist_id, name, track_ids, description?, intent_tags?, seed_context?, idempotency_key?)`**
- Creates playlist record + initial snapshot
- Idempotent via `idempotency_key` (returns existing record if already logged)

**`memory.log_playlist_mutation(user_id, playlist_id, type, payload, client_event_id?)`**
- Appends event to ledger
- Auto-creates snapshot every N=10 mutations for fast reconstruction
- Returns `{event_id, playlist_id, timestamp, new_snapshot_id?}`

**`memory.get_playlists(user_id, limit?, cursor?)`**
- List tracked playlists with pagination
- Returns summary: name, created_at, updated_at, intent_tags, track_count

**`memory.get_playlist(user_id, playlist_id, include_events_limit?)`**
- Full playlist detail: metadata + latest snapshot + recent events

**`memory.reconstruct_playlist(user_id, playlist_id, at_time?)`**
- Reconstructs track list from nearest snapshot + applying subsequent events
- Used when Spotify read-back fails (403, missing scopes)
- Returns `{playlist_id, as_of, track_ids, reconstruction: {used_snapshot_id, applied_event_count}}`

### Snapshot compaction policy
- Snapshot at create time
- Auto-snapshot every 10 mutations
- `log_playlist_mutation` returns `new_snapshot_id` when compaction triggers

### Tests
- Playlist create + get + list
- Mutation logging (ADD_TRACKS, REMOVE_TRACKS, REORDER, UPDATE_META)
- Reconstruction from snapshot + events
- Snapshot compaction after N mutations
- Idempotency (duplicate create/mutation)
- User isolation

### Verification
- Create playlist via `spotify.create_playlist` → log with `memory.log_playlist_create`
- Add/remove tracks → log mutations → reconstruct matches expected state
- After 10 mutations, auto-snapshot created

---

## Phase 9 — PR: MCP Memory: Search, Export/Delete & ChatGPT Integration

**Goal:** Cross-memory search, data portability (export + delete), and full ChatGPT GPT integration with tool-calling playbook.

### New MCP tools (3)

**`memory.search(user_id, query, limit?)`** — Keyword search across memory:
- Searches playlist names/descriptions/tags, preference events, profile notes
- Returns ranked results: `[{kind, id, score, snippet, metadata}]`
- Kind: `playlist` | `preference_event` | `profile`
- Uses PostgreSQL `ILIKE`/`ts_vector` for text matching

**`memory.export_user_data(user_id)`** — Export all memory:
- Returns `{user_id, exported_at, data: {profile, preference_events, playlists, snapshots, events}}`
- Full JSON dump of all stored memory for the user

**`memory.delete_user_data(user_id, confirm=true)`** — Hard delete:
- Deletes all taste profile, preference events, playlists, snapshots, events
- Requires `confirm=true` (safety guard)
- Returns `{user_id, deleted_at, deleted: true}`

### ChatGPT integration updates

**`docs/chatgpt-openapi.json`** — Add all 11 `memory.*` tools with flat param schemas

**`docs/chatgpt-gpt-setup.md`** — Update with full tool-calling playbook (from PRD §10):
- Session bootstrap: `memory.get_profile` + `memory.get_playlists`
- Preference handling: append event + update profile
- Playlist creation: always log with `memory.log_playlist_create` after `spotify.create_playlist`
- Playlist editing: log mutations alongside Spotify API calls
- Guardrails: artist over-weighting rules from profile
- Spotify read-back failure: use `memory.reconstruct_playlist`

### Tests
- Search across profiles, events, playlists
- Export returns complete data
- Delete removes all data, subsequent get returns empty
- ChatGPT OpenAPI schema validates

### Verification
- `memory.search("symphonic metal")` finds relevant playlists and events
- `memory.export_user_data` returns complete JSON
- `memory.delete_user_data` removes everything; profile/playlists are gone

---

## Phase 10 — PR: Explorer UI: Taste Profile & Playlist Ledger Pages

**Goal:** Show MCP memory data in the explorer frontend so users can see their taste profile, preference history, and assistant-tracked playlists.

### API endpoints (add to api service)

- `GET /api/me/taste-profile` — Returns current profile + recent preference events
- `GET /api/me/memory-playlists` — List playlists from memory ledger (not Spotify cache)
- `GET /api/me/memory-playlists/{id}` — Playlist detail with events + current track list

### Explorer pages

**Taste Profile page** (`/profile/taste`):
- Display normalized taste profile (genres, rules, energy preferences)
- Preference event timeline (chronological, filterable by type)
- "What ChatGPT knows about your taste" framing

**Memory Playlists page** (`/playlists/memory`):
- List of assistant-tracked playlists with intent tags
- Click → detail with track list, mutation history, seed context
- "Playlists created by your assistant" framing

**Dashboard integration:**
- Card showing taste profile summary (top genres, key rules)
- Card showing recent assistant playlists

### Tests
- Explorer route tests (mock API client)
- API endpoint tests for memory data

### Verification
- Profile page shows taste data + event history
- Memory playlists page shows tracked playlists
- Dashboard cards link to detail pages
- Responsive on mobile

---

## Implementation Order & Dependencies

```text
Phase 0  (error fix)                       ✅ DONE
Phase 1  (caching)                         ✅ DONE
Phase 2  (RBAC schema)                     ✅ DONE
Phase 3  (per-user creds)                  ✅ DONE
Phase 4  (JWT auth)                        ✅ DONE
Phase 5  (admin RBAC UI)                   ✅ DONE
Phase 6  (explorer foundation)             ✅ DONE
Phase 7  (taste profile + events)          ← NEXT
Phase 8  (playlist ledger)                 ← depends on Phase 7 (shared envelope + patterns)
Phase 9  (search, export/delete, ChatGPT)  ← depends on Phases 7, 8
Phase 10 (explorer UI for memory)          ← depends on Phases 7, 8, 9
```

Remaining order: **7 → 8 → 9 → 10**

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
