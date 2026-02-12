# Project Progress

> Last updated: 2026-02-12 (after Phase 6 merge)

## Overview

| Metric | Value |
|--------|-------|
| Phases completed | 6 of 9 |
| Test count | 159 (131 API + 28 collector) |
| Backend feature completion | ~85% |
| Frontend feature completion | 0% |
| PRs merged | #1 – #5 (Phase 6 PR #6 open) |

---

## Phase-by-Phase Status

### Phase 1: Project Bootstrap & Database Foundation — DONE
- Docker Compose (postgres, api, collector, frontend) with health checks
- 11 database tables, 6 enums, Alembic migration `001_initial_schema`
- Shared DB package with `DatabaseManager`, split models, config
- Dev tooling: Makefile, pre-commit (ruff + mypy), pip-tools

### Phase 2: Spotify OAuth & Token Management — DONE
- Full OAuth flow: `/auth/login` → Spotify → `/auth/callback`
- HMAC-SHA256 signed CSRF state validation
- Fernet token encryption at rest (shared between api + collector)
- TokenManager with auto-refresh on expired access tokens
- 21 tests

### Phase 3: Spotify API Client & Data Models — DONE
- `SpotifyClient` with 429/5xx exponential backoff, 401 token-refresh callback, semaphore concurrency
- 20+ Pydantic models for all Spotify API responses
- `MusicRepository`: upsert tracks/artists, insert plays, batch processing with deduplication
- `CollectorTokenManager` and `PollingService`
- 49 tests

### Phase 4: Initial Sync & Collector Run Loop — DONE
- Backward-paging initial sync with 5 stop conditions (empty batch, no progress, max days, max requests, excessive 429s)
- Priority-based run loop: ZIP imports → initial sync → incremental polling
- `JobTracker` for recording job execution with stats
- Graceful shutdown (SIGTERM/SIGINT on Unix, Ctrl+C on Windows)
- 15 tests

### Phase 5: ZIP Import Pipeline — DONE
- Streaming JSON parsing via `ijson` (no full-file memory load)
- Support for `endsong_*.json`, `Streaming_History_Audio_*.json`, `StreamingHistory*.json`
- Deterministic local IDs: `local:<sha1(artist|track|album)>` for records without Spotify URIs
- Batch transactions (5k records/commit), safety caps (500MB, 5M records)
- Admin upload endpoint `POST /admin/users/{id}/import`
- Verified with real 18,902-play dataset spanning 2015–2026
- 26 tests

### Phase 6: MCP Tool Endpoints & History Queries — DONE
- 11 MCP tools across 3 categories (history, spotify, ops)
- Decorator-based tool registry with `GET /mcp/tools` + `POST /mcp/call` dispatcher
- 6 history REST endpoints at `/history/users/{user_id}/*`
- SQLAlchemy query builders with PostgreSQL/SQLite dialect detection
- TIMESTAMPTZ migration (28 columns across 10 tables, removed ~30 `.replace(tzinfo=None)` hacks)
- All tools verified with real data and live Spotify API
- 39 tests

### Phase 7: Admin API & Authentication — NOT STARTED
- Admin user management endpoints (list, detail, pause/resume, trigger-sync, delete)
- Admin authentication middleware (token + basic auth modes)
- Operational endpoints (paginated job runs, import jobs)
- Structured DB logging handler + log viewer endpoint
- Log retention/purge endpoint

### Phase 8: Admin Frontend — NOT STARTED
- Server-rendered UI with Jinja2 + HTMX
- 7 pages: dashboard, users, user detail, imports, jobs, logs, analytics
- Charts for top artists/tracks and listening heatmap
- Frontend → API client for all admin endpoints

### Phase 9: Production Readiness & Documentation — NOT STARTED
- Security: rate limiting, security headers, CSRF, authorization review
- Observability: structured JSON logging, request-ID middleware, metrics
- Docker: restart policies, resource limits
- Documentation: README, deployment guide, ChatGPT integration guide, troubleshooting
- Additional testing: integration tests, error scenarios, coverage >80%

---

## What Exists Today

### Backend (fully operational)

```
services/
├── shared/src/shared/
│   ├── config/          — DatabaseSettings
│   ├── crypto.py        — TokenEncryptor (Fernet)
│   ├── db/
│   │   ├── base.py      — DeclarativeBase, utc_now()
│   │   ├── enums.py     — 6 StrEnums
│   │   ├── session.py   — DatabaseManager
│   │   ├── operations.py — MusicRepository
│   │   └── models/      — user, music, operations, log (11 tables)
│   ├── spotify/
│   │   ├── client.py    — SpotifyClient (retry, backoff, semaphore)
│   │   ├── models.py    — 20+ Pydantic response models
│   │   ├── exceptions.py
│   │   └── constants.py
│   └── zip_import/
│       ├── parser.py    — Streaming JSON parser
│       ├── normalizers.py — Extended + Account Data format normalizers
│       ├── models.py    — NormalizedPlayRecord
│       └── constants.py
│
├── api/src/app/
│   ├── main.py          — FastAPI app with lifespan, 4 routers
│   ├── settings.py      — AppSettings
│   ├── dependencies.py  — db_manager singleton
│   ├── auth/            — OAuth flow, tokens, crypto, state (COMPLETE)
│   ├── history/         — schemas, queries, service, router (COMPLETE)
│   ├── mcp/             — registry, router, tools/* (COMPLETE)
│   ├── admin/           — router (upload + status only), schemas (PARTIAL)
│   ├── logging/         — __init__.py only (STUB)
│   └── alembic/         — 001_initial_schema + 002_timestamptz
│
├── collector/src/collector/
│   ├── main.py          — Entry point with signal handling (COMPLETE)
│   ├── runloop.py       — Priority-based run loop (COMPLETE)
│   ├── initial_sync.py  — Backward paging sync (COMPLETE)
│   ├── polling.py       — Incremental polling (COMPLETE)
│   ├── zip_import.py    — ZIP import processor (COMPLETE)
│   ├── job_tracking.py  — JobRun management (COMPLETE)
│   ├── tokens.py        — CollectorTokenManager (COMPLETE)
│   └── settings.py      — CollectorSettings (COMPLETE)
│
└── frontend/src/frontend/
    └── main.py          — Health endpoint only (STUB)
```

### Known Gaps in Completed Phases

| Gap | Original Phase | Notes |
|-----|---------------|-------|
| Admin auth middleware | Phase 6 (original) | Env vars defined (`ADMIN_AUTH_MODE`, `ADMIN_TOKEN`) but not enforced |
| Admin user endpoints | Phase 6 (original) | Pause/resume/trigger-sync/list/detail — all missing |
| `log_to_db()` | Phase 4 (original) | `logs` table exists but nothing writes to it |
| MCP endpoint auth | Phase 7 (original) | MCP tools are publicly accessible — no token validation |

These are all addressed in the revised Phase 7.

---

## Key Technical Decisions Made During Implementation

1. **Shared package pattern** — Code used by both api and collector lives in `services/shared/`. Docker build context is `./services` so both can COPY it.

2. **TIMESTAMPTZ everywhere** — All DateTime columns use `DateTime(timezone=True)`. Always use `datetime.now(UTC)`. Never strip tzinfo. SQLite tests may need `.replace(tzinfo=None)` in assertions only.

3. **Separate token managers** — `app.auth.tokens.TokenManager` (API) and `collector.tokens.CollectorTokenManager` (collector) are intentionally separate. Both share `shared.crypto.TokenEncryptor`.

4. **Decorator-based MCP registry** — Tools self-register at import time via `@registry.register(...)`. The `/mcp/call` endpoint wraps errors in the response body (not HTTP errors).

5. **PostgreSQL/SQLite dialect detection** — Heatmap queries use `EXTRACT(ISODOW ...)` on PostgreSQL and `strftime('%w', ...)` on SQLite. Detected via `session.bind.dialect.name`.

6. **Test isolation** — API and collector tests run separately due to SQLite BigInteger compilation conflicts. Never `pytest` from root.

---

## Test Summary

| Suite | Location | Count | Coverage |
|-------|----------|-------|----------|
| Auth | `api/tests/test_auth/` | 21 | OAuth flow, crypto, tokens, state |
| Spotify client | `api/tests/test_spotify/` | 29 | Client methods, retry, backoff |
| DB operations | `api/tests/test_db/` | 11 | Upsert, dedup, batch processing |
| ZIP normalizers | `api/tests/test_zip_import/` | 7 | Both formats, edge cases |
| Admin endpoints | `api/tests/test_admin/` | 5 | Upload, import status |
| History queries | `api/tests/test_history/` | 21 | Queries, service, router |
| MCP tools | `api/tests/test_mcp/` | 18 | Registry, router, history/ops tools |
| ZIP parser | `api/tests/test_zip_import/` | 12 | Parser, format detection |
| Collector polling | `collector/tests/` | 3 | Poll, empty, dedup |
| Initial sync | `collector/tests/` | 7 | All stop conditions |
| Job tracking | `collector/tests/` | 3 | Start, complete, fail |
| Run loop | `collector/tests/` | 5 | Priority, cycle, errors |
| ZIP import service | `collector/tests/` | 4 | Full pipeline |
| Collector tokens | `collector/tests/` | 6 | Get, refresh, error |
| **Total** | | **159** | |
