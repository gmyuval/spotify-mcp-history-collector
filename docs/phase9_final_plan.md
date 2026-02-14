# Phase 9: Final Phase — OOP Refactor, Production Readiness, Documentation & Integration

## Overview

This is the final phase. It covers everything needed to go from "all features working in Docker" to "a user can deploy this, connect ChatGPT, and start analyzing their Spotify history."

The work is organized into 6 sub-tasks, in priority order. Sub-task 1 (OOP refactor) comes first because it restructures the code that all later sub-tasks touch.

---

## Current State (Post Phase 8)

- **239 tests** passing (171 API + 28 Collector + 40 Frontend)
- **11 MCP tools** implemented and verified
- **13 admin API endpoints** with auth
- **6 frontend pages** (Dashboard, Users, User Detail, Jobs, Imports, Logs)
- **All 4 Docker services** running and healthy
- Ruff + mypy strict clean across all services

### What's Missing

| Category | Gap | Priority |
|----------|-----|----------|
| Code quality | Routers and several modules use module-level functions instead of classes | High |
| Documentation | No deployment guide | Critical |
| Documentation | No ChatGPT integration guide | Critical |
| Documentation | README is outdated (missing Phase 7-8 info) | Critical |
| Security | CORS is `allow_origins=["*"]` | High |
| Security | No rate limiting on public endpoints | Medium |
| Security | No security headers middleware | Medium |
| Observability | No structured JSON logging | Medium |
| Observability | Collector doesn't write to `logs` table | Medium |
| Spec gap | Analytics frontend page (deferred) | Low |
| Spec gap | Audio features enrichment job | Low |
| Spec gap | Local track resolution job | Low |
| Spec gap | Taste clusters in taste_summary | Low |

---

## Sub-task 1: OOP Refactor (High — do first)

### Motivation

The codebase uses OOP consistently for business logic (services, clients, repositories) and data (Pydantic models, ORM models), but **all FastAPI route handlers are module-level functions** with module-level singleton service instances and private helper functions scattered across files. This sub-task refactors routers and remaining module-level logic into class-based patterns for consistency, testability, and maintainability.

### Current OOP audit

**Already class-based (no changes needed):**
- All ORM models, Pydantic schemas, StrEnums
- All service classes: `OAuthService`, `AdminService`, `HistoryService`, `MCPToolRegistry`
- All collector services: `CollectorRunLoop`, `InitialSyncService`, `PollingService`, `ZipImportService`, `JobTracker`, `CollectorTokenManager`
- All infrastructure: `DatabaseManager`, `TokenEncryptor`, `SpotifyClient`, `AdminApiClient`, `DBLogHandler`
- Application containers: `SpotifyMCPApp`, `FrontendApp`
- Config: `AppSettings`, `CollectorSettings`, `FrontendSettings`, `DatabaseSettings`
- Parser: `ZipImportParser`

**Needs refactoring (module-level functions → classes):**

#### 1A. API Routers → class-based view pattern

Refactor all 4 API router modules from module-level `@router.get`/`@router.post` functions to **class-based routers**. Each class encapsulates its service dependency, route registration, and helpers.

| File | Current | Target Class | Routes | Notes |
|------|---------|-------------|--------|-------|
| `api/src/app/auth/router.py` | 2 module-level route fns + `get_oauth_service()` | `AuthRouter` | 2 | Encapsulate `OAuthService` construction |
| `api/src/app/admin/router.py` | 13 module-level route fns + `_svc` singleton + `_ensure_user_exists()` | `AdminRouter` | 13 | Heaviest router; `_ensure_user_exists()` and upload logic become methods |
| `api/src/app/history/router.py` | 6 module-level route fns + `_service` singleton + `_validate_user()` | `HistoryRouter` | 6 | `_validate_user()` becomes a method |
| `api/src/app/mcp/router.py` | 2 module-level route fns | `MCPRouter` | 2 | Thin; encapsulate `registry` access |

**Pattern:**
```python
class AdminRouter:
    """Admin API routes."""

    def __init__(self) -> None:
        self.router = APIRouter(prefix="/admin", ...)
        self._svc = AdminService()
        self._register_routes()

    def _register_routes(self) -> None:
        self.router.add_api_route("/users", self.list_users, methods=["GET"], ...)
        ...

    async def list_users(self, ...) -> PaginatedResponse[UserSummary]:
        ...

    async def _ensure_user_exists(self, user_id: int, session: AsyncSession) -> None:
        ...
```

The `SpotifyMCPApp.__init__` already calls `_setup_routers()` — it will instantiate these classes and include their `.router`.

#### 1B. Admin auth → `AdminAuthProvider` class

| File | Current | Target Class |
|------|---------|-------------|
| `api/src/app/admin/auth.py` | 3 module-level fns: `require_admin()`, `_validate_token()`, `_validate_basic()` | `AdminAuthProvider` |

The class takes `AppSettings` and exposes a `require_admin` property/method usable as a FastAPI dependency.

#### 1C. History queries → `HistoryQueries` class

| File | Current | Target Class |
|------|---------|-------------|
| `api/src/app/history/queries.py` | 6 module-level async fns: `_cutoff()`, `query_top_artists()`, `query_top_tracks()`, etc. | `HistoryQueries` |

Group the stateless query functions as `@staticmethod` methods on a class. The private `_cutoff()` helper becomes a private `@staticmethod`.

#### 1D. MCP tool handlers → tool handler classes

| File | Current | Target Classes |
|------|---------|---------------|
| `api/src/app/mcp/tools/history_tools.py` | 6 module-level fns + `_svc` singleton | `HistoryToolHandlers` |
| `api/src/app/mcp/tools/ops_tools.py` | 3 module-level fns with inline DB queries | `OpsToolHandlers` |
| `api/src/app/mcp/tools/spotify_tools.py` | 2 module-level fns with inline client creation | `SpotifyToolHandlers` |

Each class groups related tool handlers. The `@registry.register()` decorator still works — just applied to methods. Self-registration happens when the class is defined (class body executes at import time). If the decorator doesn't work on bound methods, the `__init_subclass__` or a class-level registration method can be used instead.

**Alternative if decorators don't work on methods:** Keep module-level registration functions but have them delegate to a class instance:
```python
class HistoryToolHandlers:
    _svc = HistoryService()

    @staticmethod
    async def taste_summary(args: dict[str, object], session: AsyncSession) -> dict[str, object]:
        ...

# Registration at module level (required by registry pattern)
registry.register(...)(HistoryToolHandlers.taste_summary)
```

#### 1E. Frontend routers → class-based view pattern

| File | Current | Target Class | Routes |
|------|---------|-------------|--------|
| `frontend/src/frontend/routes/dashboard.py` | 2 module-level fns | `DashboardRouter` | 2 |
| `frontend/src/frontend/routes/users.py` | 7 module-level fns + `_user_action()` | `UsersRouter` | 7 |
| `frontend/src/frontend/routes/jobs.py` | 2 module-level fns + `_extract_filters()` | `JobsRouter` | 2 |
| `frontend/src/frontend/routes/imports.py` | 3 module-level fns + `_extract_filters()` | `ImportsRouter` | 3 |
| `frontend/src/frontend/routes/logs.py` | 3 module-level fns + `_extract_filters()` | `LogsRouter` | 3 |

Private helpers like `_user_action()` and `_extract_filters()` become private methods on the class.

#### 1F. Remaining module-level helpers → static methods or utility classes

| File | Function | Refactoring |
|------|----------|-------------|
| `api/src/app/api_client.py` | `build_auth_headers()` | → `@staticmethod` on `AdminApiClient` |
| `collector/src/collector/initial_sync.py` | `_datetime_to_unix_ms()` | → `@staticmethod` on `InitialSyncService` |
| `shared/src/shared/db/base.py` | `enum_values()`, `utc_now()` | Keep as module-level — used as SQLAlchemy column defaults, must be callable references |
| `shared/src/shared/zip_import/normalizers.py` | `normalize_extended_record()`, `normalize_account_data_record()` | → `RecordNormalizer` class with `@staticmethod` methods |
| `shared/src/shared/spotify/constants.py` | URL constants | Keep as module-level — pure constants |
| `shared/src/shared/config/constants.py` | `DEFAULT_DATABASE_URL` | Keep as module-level — pure constant |
| `frontend/src/frontend/routes/_helpers.py` | `safe_int()` | Keep as module-level utility OR move to a `RouteHelpers` class |
| `services/*/settings.py` | `get_settings()` | Keep as module-level — cached factory function for FastAPI dependency injection |

#### 1G. Update `routes/__init__.py` files and test files

After refactoring routers to classes, update:
- `api/src/app/main.py` (`SpotifyMCPApp._setup_routers()`) — instantiate router classes
- `frontend/src/frontend/main.py` (`FrontendApp._setup_routers()`) — instantiate router classes
- `frontend/src/frontend/routes/__init__.py` — re-export router instances from classes
- All affected test files — update imports, mock targets

#### Tests for Sub-task 1

All existing 239 tests must continue to pass. No new tests needed — this is a refactor. Run the full suite after each router conversion:
```
pytest services/api/tests/ -x -q
cd services/collector && pytest tests/ -x -q
pytest services/frontend/tests/ -x -q
mypy services/api/src services/collector/src services/frontend/src services/shared/src
ruff check .
```

---

## Sub-task 2: Security Hardening (High)

### 2A. Lock down CORS

Replace `allow_origins=["*"]` with configurable origins via env var `CORS_ALLOWED_ORIGINS`. Default to `http://localhost:8001` (frontend) for development. In production, users set this to their domain.

**Files:** `services/api/src/app/main.py`, `services/api/src/app/settings.py`

### 2B. Add security headers middleware

Add a FastAPI middleware that sets on every response:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `X-XSS-Protection: 0` (modern approach — rely on CSP instead)

These are lightweight and don't require any external dependencies.

**Files:** `services/api/src/app/middleware.py` (new)

### 2C. Add rate limiting on auth endpoints

Add basic in-memory rate limiting on `/auth/login` and `/auth/callback` to prevent abuse. Use a simple sliding window counter (no Redis dependency needed for single-instance deployment).

Limits:
- `/auth/login`: 10 requests per minute per IP
- `/auth/callback`: 10 requests per minute per IP
- `/mcp/call`: 60 requests per minute per token

**Files:** `services/api/src/app/middleware.py`

### 2D. Review tokens/PII in error responses

Audit all error handlers and log statements to ensure no refresh tokens, access tokens, or PII leak in API responses or log output. This is a review task — fix any issues found.

---

## Sub-task 3: Observability Improvements (Medium)

### 3A. Structured JSON logging for API

Replace `logging.basicConfig()` in the API with structured JSON output. Use Python's `logging` with a JSON formatter. This makes logs parseable by log aggregation tools (CloudWatch, Loki, ELK).

Format: `{"timestamp": "...", "level": "INFO", "service": "api", "message": "...", "request_id": "...", "extra": {...}}`

**Files:** `services/api/src/app/main.py`

### 3B. Request-ID middleware

Generate a UUID request ID for each incoming request. Pass it through via `request.state.request_id`. Include it in all log messages and in the `X-Request-ID` response header. This enables tracing a request across log entries.

**Files:** `services/api/src/app/middleware.py`

### 3C. Add DBLogHandler to collector

The collector currently logs to stdout only. Wire up the same `DBLogHandler` pattern from the API so collector logs appear in the admin log viewer.

**Files:** `services/collector/src/collector/main.py`

---

## Sub-task 4: Documentation (Critical)

### 4A. Rewrite README.md

The current README is a basic dev quickstart from Phase 1. Rewrite it to be comprehensive:

- Project overview with architecture diagram (ASCII)
- Quick start guide (5-minute version)
- Full configuration reference (all env vars with descriptions and defaults)
- Service descriptions and ports
- Updated project structure (reflect routes/, templates/, all packages)
- Link to deployment guide, ChatGPT integration guide, and troubleshooting
- Test counts and quality info
- Remove the outdated TODO comment

### 4B. Create docs/deployment.md

Production deployment guide:

1. **Prerequisites** — Docker, Docker Compose, a domain name (for HTTPS), Spotify Developer app
2. **Spotify Developer Setup** — Step-by-step: create app, get client ID/secret, set redirect URI
3. **Environment Configuration** — Walk through every `.env` variable with examples
4. **Deploy with Docker Compose**
   - Clone repo, copy `.env.example`, fill in values
   - `docker-compose up -d`
   - Run migrations: `docker-compose exec api alembic upgrade head`
   - Verify health endpoints
5. **HTTPS Setup** — Options:
   - Caddy reverse proxy (simplest, auto-TLS)
   - nginx + Let's Encrypt
   - Cloud load balancer (AWS ALB, GCP LB)
6. **First User Setup** — Navigate to `/auth/login`, complete Spotify OAuth
7. **Import Historical Data** — Upload ZIP via frontend or API
8. **Verify Everything Works** — Check dashboard, trigger sync, query MCP tools
9. **Maintenance** — Log purge, database backups, updating

### 4C. Create docs/chatgpt-integration.md

Step-by-step guide for connecting ChatGPT as a Custom GPT:

1. **Overview** — How it works: ChatGPT calls `/mcp/call` with tool name + args, gets JSON response
2. **Prerequisites** — System deployed and accessible via HTTPS, at least one user authorized
3. **Create Custom GPT** — Navigate to ChatGPT > Explore GPTs > Create
4. **Configure GPT Action**
   - Import OpenAPI schema (provide the schema inline or link to `/openapi.json`)
   - Set authentication: API Key, Bearer token, use `ADMIN_TOKEN` value
   - Set server URL to your deployment
5. **Provide the OpenAPI schema** — A complete, minimal OpenAPI 3.1 schema for `/mcp/tools` and `/mcp/call` endpoints with request/response examples
6. **Write GPT Instructions** — System prompt for the GPT explaining available tools, how to format tool calls, what user_id to use
7. **Test Prompts** — Example conversations:
   - "What are my top artists from the last 30 days?"
   - "Show me my listening heatmap"
   - "Give me a complete taste analysis"
   - "What's my repeat rate?"
8. **Troubleshooting** — Common issues (auth errors, empty responses, CORS)

### 4D. Create docs/troubleshooting.md

Common issues and solutions:

- OAuth callback fails (redirect URI mismatch)
- Collector not polling (check logs, verify tokens)
- Empty MCP tool responses (no plays collected yet)
- ZIP import errors (format not detected, file too large)
- Frontend shows "API Error" (check API health, auth config)
- Docker health checks failing
- Database migration issues

---

## Sub-task 5: Final Polish & Spec Compliance (Medium)

### 5A. Update implementation_plan.md

Mark Phase 8 as DONE with PR number. Mark Phase 9 as IN PROGRESS.

### 5B. Update CLAUDE.md

Update implementation status to reflect Phase 9 work. Update test counts.

### 5C. Update docker-compose.yml

- Add resource limits (memory: 512m for api/frontend, 256m for collector, 1g for postgres)
- Remove `--reload` from production commands (keep for dev via override)

### 5D. Document deferred items

Create a clear list of items intentionally deferred beyond Phase 9:
- Analytics frontend page (needs Chart.js integration)
- Audio features enrichment job
- Local track resolution job
- Taste clusters in taste_summary
- Watched directory imports (`IMPORT_WATCH_DIR`)
- `POST /auth/logout`
- PostgreSQL integration tests (vs SQLite)

---

## Sub-task 6: End-to-End Verification & Manual Test Guide

### 6A. Run full test suite

```
pytest services/api/tests/ -x -q
cd services/collector && pytest tests/ -x -q
pytest services/frontend/tests/ -x -q
mypy services/api/src services/collector/src services/frontend/src services/shared/src
ruff check .
```

### 6B. Docker integration test

```
docker-compose up --build -d
# Wait for healthy
# Verify all health endpoints
# Verify frontend pages return 200
# Check container logs for errors
docker-compose down
```

### 6C. Write manual test instructions

Provide step-by-step instructions for the user to manually verify the complete system:

1. **Start services**: `docker-compose up --build -d`
2. **Run migrations**: `docker-compose exec api alembic upgrade head`
3. **Check health**: `curl http://localhost:8000/healthz` and `curl http://localhost:8001/healthz`
4. **Authorize Spotify**: Open `http://localhost:8000/auth/login` in browser
5. **Check dashboard**: Open `http://localhost:8001` — should show 1 user, sync status
6. **Trigger sync**: Click "Trigger Sync" on user detail page, or wait for collector
7. **Browse data**: Check Jobs page for completed poll job, check Users page for updated sync time
8. **Test MCP tools**: `curl -X POST http://localhost:8000/mcp/call -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" -d '{"tool": "ops.sync_status", "args": {"user_id": 1}}'`
9. **Upload ZIP** (optional): Use Imports page to upload a Spotify data export
10. **Test history tools** (after plays exist): Call `history.top_artists`, `history.taste_summary`, etc.
11. **Check logs**: Browse Logs page, verify entries from API and collector
12. **Admin frontend**: Walk through all 6 pages, verify filters/pagination/actions work

---

## Implementation Order

| Order | Sub-task | Files Changed | Estimated Scope |
|-------|----------|---------------|-----------------|
| 1 | 1A. API routers → class-based | 4 router files + main.py | Large |
| 2 | 1B. Admin auth → class | 1 file | Small |
| 3 | 1C. History queries → class | 1 file | Small |
| 4 | 1D. MCP tool handlers → classes | 3 files | Medium |
| 5 | 1E. Frontend routers → class-based | 5 router files + __init__.py + main.py | Large |
| 6 | 1F. Remaining helpers → static methods | 3 files | Small |
| 7 | 1G. Update tests | ~6 test files | Medium |
| 8 | 2A. Lock down CORS | 2 files | Small |
| 9 | 2B. Security headers | 1 new file | Small |
| 10 | 2C. Rate limiting | 1 file | Medium |
| 11 | 3A. JSON logging | 1 file | Small |
| 12 | 3B. Request-ID middleware | 1 file | Small |
| 13 | 3C. Collector DB logging | 1 file | Medium |
| 14 | 4A. Rewrite README | 1 file | Medium |
| 15 | 4B. Deployment guide | 1 new file | Large |
| 16 | 4C. ChatGPT integration guide | 1 new file | Large |
| 17 | 4D. Troubleshooting guide | 1 new file | Medium |
| 18 | 5A-D. Final polish | 3 files | Small |
| 19 | 6A-C. Verification + test guide | Run + write | Medium |

**Total: ~30 files changed/created**

---

## Explicitly Deferred (Post Phase 9)

These items from the spec are intentionally deferred. They are enhancements beyond the core system:

1. **Analytics page** (`/analytics/{user_id}`) — Requires Chart.js integration for visualizations
2. **Audio features enrichment** — Populate `audio_features` table, add `audio_profile` to taste_summary
3. **Local track resolution** — Match `local:<sha1>` IDs to real Spotify IDs via search
4. **Taste clusters** — k-means or rule-based clustering in taste_summary response
5. **Watched directory imports** — `IMPORT_WATCH_DIR` auto-ingest
6. **`POST /auth/logout`** — Token revocation endpoint
7. **PostgreSQL integration tests** — testcontainers for dialect-specific behavior
8. **Metrics endpoint** — Prometheus `/metrics` for monitoring
9. **CSRF protection** — For frontend form submissions (low risk since frontend is admin-only)

---

## Success Criteria

After Phase 9 is complete:

- [ ] All routers and modules use class-based patterns (except pure constants and SQLAlchemy defaults)
- [ ] All tests pass (target: 250+ total)
- [ ] Ruff + mypy clean
- [ ] Docker services start, are healthy, and function correctly
- [ ] README is comprehensive and accurate
- [ ] A new user can follow `docs/deployment.md` to deploy the system
- [ ] A new user can follow `docs/chatgpt-integration.md` to connect ChatGPT
- [ ] `docs/troubleshooting.md` covers common failure modes
- [ ] CORS locked down (not `*`)
- [ ] Security headers present on all responses
- [ ] Rate limiting active on auth endpoints
- [ ] Structured JSON logs in API service
- [ ] Request-ID in all API log entries and response headers
- [ ] Collector logs visible in admin log viewer
- [ ] Manual end-to-end verification passes
