# Phase 6: MCP Tool Endpoints, History Queries & TIMESTAMPTZ Migration — Summary

## What Was Built

Phase 6 delivers the core value proposition of the project: making 10+ years of Spotify listening data queryable through an MCP-compatible tool interface for ChatGPT/assistant integration. It also includes a cross-cutting migration from naive `TIMESTAMP` to timezone-aware `TIMESTAMPTZ` across the entire database.

### New Components

| Component | Files | Purpose |
|-----------|-------|---------|
| **History schemas** | `api/history/schemas.py` | 7 Pydantic response models: `ArtistCount`, `TrackCount`, `HeatmapCell`, `ListeningHeatmap`, `RepeatStats`, `CoverageStats`, `TasteSummary` |
| **History queries** | `api/history/queries.py` | 5 SQLAlchemy query builders with PostgreSQL/SQLite dialect detection |
| **History service** | `api/history/service.py` | Stateless `HistoryService` class with 6 methods composing queries into response models |
| **History REST endpoints** | `api/history/router.py` | 6 endpoints at `/history/users/{user_id}/*` |
| **MCP schemas** | `api/mcp/schemas.py` | `MCPToolParam`, `MCPToolDefinition`, `MCPCallRequest`, `MCPCallResponse` |
| **MCP registry** | `api/mcp/registry.py` | Decorator-based `MCPToolRegistry` with global singleton |
| **MCP dispatcher** | `api/mcp/router.py` | `GET /mcp/tools` catalog + `POST /mcp/call` unified invocation |
| **History tools** | `api/mcp/tools/history_tools.py` | 6 handlers wrapping `HistoryService` |
| **Spotify live tools** | `api/mcp/tools/spotify_tools.py` | 2 handlers for real-time Spotify API (`get_top`, `search`) |
| **Ops tools** | `api/mcp/tools/ops_tools.py` | 3 handlers for sync/job/import status queries |
| **TIMESTAMPTZ migration** | `alembic/versions/002_timestamp_to_timestamptz.py` | Converts 28 columns across 10 tables |
| **Test suites** | 9 new test files | 39 new tests across `test_history/` and `test_mcp/` |

### Modified Components

| File | Change |
|------|--------|
| `shared/db/base.py` | `utc_now()` returns tz-aware `datetime.now(UTC)` |
| `shared/db/models/*.py` (4 files) | All `DateTime` → `DateTime(timezone=True)` — 28 columns |
| `shared/zip_import/normalizers.py` | Produce tz-aware datetimes (no more naive output) |
| `collector/tokens.py` | Removed `.replace(tzinfo=None)` hacks |
| `collector/polling.py` | Removed naive hacks, added defensive tz checks for SQLite |
| `collector/initial_sync.py` | Removed `.replace(tzinfo=None)` from 3 locations |
| `collector/job_tracking.py` | Removed `.replace(tzinfo=None)` from 3 locations |
| `collector/zip_import.py` | Removed `.replace(tzinfo=None)` from 3 locations |
| `api/main.py` | Mounted history + MCP routers |
| `CLAUDE.md` | Updated datetime convention and implementation status |
| Test files | Updated assertions for tz-aware datetimes |

---

## Architecture Decisions

### MCP Tool Registry — Decorator-Based Registration

```python
registry = MCPToolRegistry()  # Global singleton

@registry.register(name="history.top_artists", ...)
async def top_artists(args: dict, session: AsyncSession) -> Any: ...
```

Each tool module self-registers at import time. The `mcp/tools/__init__.py` imports all modules to trigger registration. This is simple, explicit, and avoids classpath scanning. The handler signature `(args: dict, session: AsyncSession) -> Any` keeps tools testable (pass a test session) and HTTP-decoupled.

The `/mcp/call` endpoint catches handler exceptions and returns `MCPCallResponse(success=False, error=str(exc))` rather than HTTP errors — matching MCP protocol semantics where errors live in the response body.

### History Queries — Dialect-Aware SQL

The heatmap query needs `EXTRACT(ISODOW/HOUR FROM ...)` on PostgreSQL but `strftime('%w'/'%H', ...)` on SQLite. We use `session.bind.dialect.name` to branch:

```python
if dialect == "sqlite":
    weekday_expr = (cast(func.strftime("%w", Play.played_at), Integer) + 6) % 7
else:
    weekday_expr = cast(extract("isodow", Play.played_at), Integer) - 1
```

All other queries use standard SQLAlchemy constructs that work on both dialects.

### Layered Architecture

```
HTTP request → router.py → service.py → queries.py → SQLAlchemy → DB
                                           ↓
MCP request → mcp/router.py → registry → handler → service.py → queries.py
```

The history REST endpoints and MCP tools share the same `HistoryService` and query layer. The MCP tools are thin wrappers that parse `args` and call service methods.

### TIMESTAMPTZ Migration Strategy

**Problem**: Phases 2–5 accumulated ~30 `.replace(tzinfo=None)` hacks to strip timezone info before writing to the database or comparing with naive DB values. Each new feature risked a naive-vs-aware `TypeError`.

**Solution**: Migrate all 28 `DateTime` columns to `DateTime(timezone=True)` (PostgreSQL `TIMESTAMPTZ`) and remove every hack:

1. Update all model definitions: `DateTime` → `DateTime(timezone=True)`
2. Change `utc_now()` in `base.py` to return tz-aware `datetime.now(UTC)`
3. Remove all `.replace(tzinfo=None)` calls across the codebase
4. Alembic migration `002_timestamp_to_timestamptz` using `ALTER COLUMN TYPE`
5. PostgreSQL treats existing naive values as UTC during conversion (correct for our data)

---

## Bugs Found & Fixed

### 1. OAuth Callback Timezone Mismatch
**Symptom**: `asyncpg.exceptions.DataError: can't subtract offset-naive and offset-aware datetimes` during OAuth callback.

OAuth service computed `expires_at = datetime.now(UTC) + timedelta(...)` (tz-aware) but the DB column was naive `TIMESTAMP`. Initially fixed with `.replace(tzinfo=None)`, then properly fixed by the TIMESTAMPTZ migration.

### 2. TokenManager Comparison Error
**Symptom**: `TypeError: can't compare offset-naive and offset-aware datetimes` in `auth/tokens.py` line 37.

The DB stored naive `token_expires_at` but code compared it with `datetime.now(UTC)`. Same root cause, same fix trajectory.

### 3. SQLite Naive Datetime Round-Trip
**Symptom**: `TypeError` in `test_poll_user_dedup` after TIMESTAMPTZ migration.

SQLite stores tz-aware datetimes as text with `+00:00` suffix but reads them back as naive strings. The second poll call tried to compare a tz-aware value with the naive value read from SQLite. Fixed with defensive checks in `polling.py`:

```python
if latest_played_at.tzinfo is None:
    latest_played_at = latest_played_at.replace(tzinfo=UTC)
```

### 4. Normalizer Output Timezone
**Symptom**: `test_normalize_account_data_record_valid` expected tz-aware datetime but normalizer produced naive.

The account data normalizer used `datetime.strptime(...)` which produces naive datetimes. Fixed by adding `.replace(tzinfo=UTC)`.

---

## Test Results

| Suite | Tests | Status |
|-------|-------|--------|
| API (existing) | 92 | Passed |
| API (new — history + MCP) | 39 | Passed |
| Collector | 28 | Passed |
| **Total** | **159** | **All passing** |

Ruff lint, ruff format, and mypy strict — all clean.

## Production Verification

All 11 MCP tools verified with real data after re-importing from ZIP:

| Tool | Result |
|------|--------|
| `history.taste_summary` (3650 days) | Full 10-year analysis: 18,952 plays, 4,445 tracks, 1,632 artists, 1,170 listening hours |
| `history.top_artists` | Rankings from ZIP + API data combined |
| `history.top_tracks` | Play counts spanning import + live collection |
| `history.listening_heatmap` | Weekday/hour distribution over full history |
| `history.repeat_rate` | Repeat metrics: 4.26x rate across 10 years |
| `history.coverage` | 18,902 import + 50 API plays, 2,543 active days |
| `spotify.get_top` (artists) | Live Spotify API with real OAuth token |
| `spotify.get_top` (tracks) | Live Spotify API, all three time ranges |
| `spotify.search` | Real-time search returning tracks/artists/albums |
| `ops.sync_status` | Checkpoint with initial sync + poll timestamps |
| `ops.latest_job_runs` | Recent poll, initial_sync, import_zip jobs |
| `ops.latest_import_jobs` | Import job with 18,902 records ingested |

All timestamps in the database confirmed tz-aware (with `+00` suffix).

---

## Insights & Lessons Learned

### 1. Use TIMESTAMPTZ From Day One

The biggest pain point of Phase 6 was not the MCP tools themselves but the timezone migration. Starting with naive `TIMESTAMP` created a steadily growing tax of `.replace(tzinfo=None)` calls at every boundary between Python's tz-aware `datetime.now(UTC)` and the DB's naive values. By Phase 5 there were ~30 such hacks. Each new code path risked a `TypeError`.

**Recommendation**: Always use `DateTime(timezone=True)` / `TIMESTAMPTZ` in PostgreSQL projects. The migration is straightforward (PostgreSQL treats existing naive values as UTC), but it touches every model, every test, and every piece of code that constructs or compares datetimes.

### 2. SQLite Is a Leaky Abstraction for DateTime Tests

SQLite ignores `DateTime(timezone=True)` entirely. It stores tz-aware datetimes as text and reads them back as naive strings. This means:
- Tests using SQLite can pass while the same code fails against PostgreSQL (or vice versa)
- Defensive tz-awareness checks are needed in production code to handle SQLite test scenarios
- Consider adding a small set of PostgreSQL integration tests (via testcontainers or Docker) for datetime-sensitive code paths

### 3. Decorator-Based Registry Scales Well

The `@registry.register(...)` pattern for MCP tools is clean and self-documenting. Adding a new tool requires:
1. Write the handler function with the right signature
2. Add the `@registry.register` decorator with metadata
3. Import the module in `tools/__init__.py`

No need to touch router code, no central configuration file. At 11 tools this works perfectly. It may need namespacing or categories if it grows to 50+.

### 4. Layered Architecture Pays Off

Having separate layers (queries → service → router/MCP handler) meant:
- History REST endpoints and MCP tools share the same business logic
- Tests can target the query layer directly (fast, isolated) or the full HTTP layer (integration)
- Adding a new output format (e.g., GraphQL) would only need a new thin adapter

### 5. `taste_summary` Composition Pattern

The `get_taste_summary()` method doesn't have its own mega-query. Instead it calls `query_top_artists`, `query_top_tracks`, `query_play_stats`, `query_heatmap`, and `query_coverage` individually and composes them. This is:
- Easier to maintain (each query is independent)
- Easier to test (each query has its own tests)
- Acceptable performance (5 queries in sequence, all <100ms on ~19k plays)

At scale this could become a bottleneck; consider parallel execution or pre-aggregation if needed.

---

## Pointers for Next Phases

### Phase 7: Admin Frontend

The frontend service (`services/frontend/`) has a FastAPI skeleton but no templates. It should provide:
- **User management**: List users, view profiles, toggle sync on/off
- **Sync dashboard**: Per-user sync status, initial sync progress, poll history
- **Import management**: Upload ZIPs, view import job status/stats
- **Job history**: Browse recent job runs with filters
- **Log viewer**: Browse structured logs from the `logs` table

**Key decisions**:
- Jinja2 + HTMX for server-rendered interactivity (no JS build step)
- Frontend calls API service at `API_BASE_URL`, never touches DB directly
- Admin API endpoints need expanding — currently only ZIP upload exists
- `ADMIN_AUTH_MODE` (basic/token) for securing admin access

### Phase 8: Structured Logging & Observability

The `logs` table schema exists but nothing writes to it:
- Implement a Python logging handler that writes structured events to the DB
- Add request-ID middleware for trace correlation across service calls
- Log retention policy (auto-purge older than N days)
- Consider log levels: collector job lifecycle events, API errors, auth events

### Phase 9: Audio Features Enrichment

The `audio_features` table exists but is empty. `SpotifyClient.get_audio_features()` is already implemented (supports batch of 100 IDs per request).
- Add an `enrich` job type to the collector run loop
- Batch-fetch audio features for tracks missing them
- Rate-limit aware (Spotify 429 handling already in SpotifyClient)
- Enables future MCP tools: "what's my average danceability?", "find my most energetic tracks"

### Phase 10: Local Track Resolution

ZIP imports without Spotify URIs create deterministic local IDs (`local:<sha1(artist|track|album)>`). These can't be enriched.
- Use `SpotifyClient.search()` to match local tracks to real Spotify IDs
- Merge strategy: update `tracks.spotify_id`, re-link plays, handle conflicts with existing tracks
- Success rate will vary — some tracks may have been removed from Spotify
- Run as a lower-priority background job

### Cross-Cutting Concerns

- **Performance at scale**: Current queries work well on ~19k plays. At 100k+ plays, consider indexes on `plays(user_id, played_at, track_id)`, materialized views for heatmap/coverage, and query result caching
- **Test isolation**: API and collector tests must still be run separately due to conftest BigInteger-SQLite compilation conflicts
- **Test count**: 159 tests total (131 API + 28 collector). Each phase should maintain or increase coverage
- **Pre-commit hooks**: ruff v0.15.0 + mypy strict on every commit; never use `--no-verify`
