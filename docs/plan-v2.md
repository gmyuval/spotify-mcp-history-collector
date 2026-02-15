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

## Phase 0 — PR: MCP Error Message Fix (Quick Win)

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

## Phase 1 — PR: Spotify Data Caching (PostgreSQL)

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

## Phase 2 — PR: RBAC Foundation (Roles, Permissions, DB Schema)

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

## Phase 3 — PR: Per-User Spotify App Credentials

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

## Phase 4 — PR: User Authentication (JWT + Spotify Login)

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

```
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

## Phase 7 — PR: ChatGPT Taste Inference Storage

**Goal:** Allow ChatGPT to store and retrieve its analysis/inferences about a user's music taste. ChatGPT can call an MCP tool to save a structured taste profile (genres, moods, descriptions, notable patterns), and retrieve it later to provide continuity across conversations.

### New DB table (Alembic migration `006_taste_profiles`)

**`taste_profiles`**:
- `id` (BigInt PK)
- `user_id` (BigInt FK → users, indexed)
- `profile_type` (String 50) — "summary" | "genre_breakdown" | "mood_profile" | "custom"
- `title` (String 255) — e.g., "Overall Taste Summary", "January 2026 Mood"
- `content` (Text) — free-form text or structured JSON written by ChatGPT
- `metadata_json` (Text/JSON, nullable) — optional structured data (top genres list, scores, etc.)
- `created_by` (String 50, default "chatgpt") — who created this entry
- `created_at`, `updated_at`
- Index: `(user_id, profile_type)`

### New MCP tools (3)

**`taste.save_profile(user_id, profile_type, title, content, metadata?)`** — Store a taste inference:
- ChatGPT calls this after analyzing listening data to persist its insights
- Upserts by `(user_id, profile_type, title)` — updating replaces previous content

**`taste.get_profiles(user_id, profile_type?)`** — Retrieve stored taste profiles:
- Returns all profiles for user, optionally filtered by type
- ChatGPT calls this at conversation start to recall previous analysis

**`taste.delete_profile(user_id, profile_id)`** — Remove a stored profile

### Files to modify

**`services/shared/src/shared/db/models/taste.py`** (new) — TasteProfile model

**`services/api/src/app/mcp/tools/taste_tools.py`** (new) — `TasteToolHandlers`:
- `taste.save_profile` — validate + upsert
- `taste.get_profiles` — query + return
- `taste.delete_profile` — delete by id

**`services/api/src/app/mcp/tools/__init__.py`** — Import taste tools

**`docs/chatgpt-openapi.json`** — Add 3 new tools + params

**`docs/chatgpt-gpt-setup.md`** — Update GPT instructions:
- "At the start of a conversation, call taste.get_profiles to recall your previous analysis"
- "After providing a taste analysis, call taste.save_profile to persist it for future conversations"

### Example ChatGPT workflow
1. User: "What kind of music do I listen to?"
2. ChatGPT: calls `taste.get_profiles(user_id=1)` → finds previous summary from last week
3. ChatGPT: calls `history.taste_summary(user_id=1, days=30)` → gets fresh data
4. ChatGPT: compares, synthesizes, presents updated analysis
5. ChatGPT: calls `taste.save_profile(user_id=1, profile_type="summary", title="Overall Taste Summary", content="...")` → persists updated analysis

### Tests
- Save/retrieve/update/delete profile tests
- MCP tool integration tests
- Upsert behavior test (same type+title replaces content)

### Verification
- Ask ChatGPT to analyze taste → it saves a profile
- Start new conversation → ChatGPT retrieves previous profile
- Verify profiles visible in explorer frontend (Phase 8)

---

## Phase 8 — PR: Data Exploration Features & Taste Profile UI

**Goal:** Rich exploration features in the public frontend: listening history timeline, playlist management, ChatGPT-created playlist tracking.

### Pages & features

**Dashboard:**
- Total plays, hours listened, unique tracks/artists
- Top 5 artists/tracks (last 30 days)
- Listening activity chart (plays per day, last 90 days)
- Active playlists summary

**History Browser:**
- Paginated table with search/filter (date range, artist, track name)
- Sortable columns (date, track, artist, duration)
- HTMX infinite scroll or pagination
- Click track/artist → detail page

**Playlist Explorer:**
- Grid/list of user's playlists (cached from Phase 1)
- Filter: all / created by user / created by ChatGPT
- Playlist detail: track listing, total duration, creation source
- Track ChatGPT-created playlists via `created_via` field on `cached_playlists`

**Track Detail Page:**
- Track metadata (album, artists, duration, popularity)
- User's play count + last played
- Audio features visualization (if enriched) — radar chart for danceability/energy/etc.

**Artist Detail Page:**
- Artist metadata (genres, popularity)
- User's top tracks by this artist
- Play count over time

### DB changes (Alembic migration `007_playlist_source_tracking`)

**Add to `cached_playlists`:**
- `created_via` (String 50, nullable) — "chatgpt" | "user" | "external" | null
- Set by `create_playlist` MCP tool handler when ChatGPT creates a playlist

### Files to modify

- Explorer templates (all pages above)
- Explorer routes (data fetching + rendering)
- API user-facing endpoints (history, playlist, track detail queries)
- `playlist_tools.py` — `create_playlist` handler: set `created_via="chatgpt"` in cache
- **Taste profile page** in explorer — show ChatGPT's stored analysis of user's taste
- API endpoint `GET /api/me/taste-profiles` — returns stored taste profiles for display

### Tests
- API endpoint tests for each data exploration query
- Frontend route tests
- ChatGPT playlist tracking test

### Verification
- Browse full listening history with filters
- View ChatGPT-created playlists separately
- Track detail shows play count + audio features chart
- Responsive on mobile

---

## Implementation Order & Dependencies

```
Phase 0 (error fix)           ← standalone, do first
Phase 1 (caching)             ← standalone
Phase 2 (RBAC schema)         ← standalone
Phase 3 (per-user creds)      ← depends on Phase 2 (roles exist)
Phase 4 (JWT auth)            ← depends on Phase 2 (permissions exist)
Phase 5 (admin RBAC UI)       ← depends on Phases 2, 3, 4
Phase 6 (explorer foundation) ← depends on Phases 1, 4
Phase 7 (taste storage)       ← depends on Phase 1 (cache tables pattern)
Phase 8 (explorer features)   ← depends on Phases 6, 7
```

Recommended order: **0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8**

Phases 1 and 2 can be done in parallel since they're independent.
Phases 6 and 7 can be done in parallel since they're independent.

---

## Key Design Decisions

1. **PostgreSQL for caching** — No Redis needed. Cache tables are simple, queries are fast at this scale, and it avoids infrastructure complexity.
2. **Playlist snapshot_id for invalidation** — Spotify provides `snapshot_id` that changes on any playlist modification. This is more reliable than TTL for playlists.
3. **TTL for tracks/artists/albums** — These change rarely. 24h default TTL is reasonable. Configurable via `SPOTIFY_CACHE_TTL_HOURS`.
4. **Full RBAC over simple roles** — More complex but future-proof. String-based permission codenames are easy to check and extend.
5. **JWT for user sessions** — Stateless auth that works across services. HTTP-only cookies for browser security.
6. **Per-user Spotify credentials** — Optional override at user level. System defaults used when not set. Credentials encrypted at rest (same pattern as refresh tokens).
7. **Separate explorer service** — Clean separation: admin frontend for ops, explorer for end users. Different auth models, different audiences.
8. **ChatGPT playlist tracking** — Tag playlists with `created_via` at creation time. Simple, queryable, enables the "show me what ChatGPT created" feature.
9. **Taste profile storage** — Free-form text + optional structured JSON. ChatGPT decides what to store (summaries, genre breakdowns, mood profiles). Upsert by `(user_id, profile_type, title)` keeps profiles fresh without duplicating. Profiles visible in the explorer frontend so users can see what ChatGPT thinks of their taste.
