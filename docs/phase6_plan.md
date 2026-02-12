# Phase 6: MCP Tool Endpoints & History Queries

## Context

Phases 1–5 built the complete data collection pipeline: OAuth, Spotify API client, collector run loop (initial sync + polling + ZIP imports), and a verified 18,902-play dataset spanning 10+ years. **The data is ready — Phase 6 makes it queryable.**

This phase implements 11 MCP-compatible tools across three categories (history analysis, Spotify live, operational status) plus a dispatcher endpoint for ChatGPT/assistant integration. This is the core value proposition of the project.

---

## New Files

| # | File | Purpose |
|---|------|---------|
| 1 | `services/api/src/app/history/schemas.py` | Pydantic response models: `ArtistCount`, `TrackCount`, `ListeningHeatmap`, `RepeatStats`, `CoverageStats`, `TasteSummary` |
| 2 | `services/api/src/app/history/queries.py` | Raw SQLAlchemy query builders for all 6 history tools |
| 3 | `services/api/src/app/history/service.py` | `HistoryService` class orchestrating queries → response models |
| 4 | `services/api/src/app/history/router.py` | Direct REST endpoints at `/history/users/{user_id}/*` |
| 5 | `services/api/src/app/mcp/schemas.py` | `MCPToolDefinition`, `MCPCallRequest`, `MCPCallResponse` |
| 6 | `services/api/src/app/mcp/registry.py` | `MCPToolRegistry` with decorator-based tool registration |
| 7 | `services/api/src/app/mcp/router.py` | `GET /mcp/tools` catalog + `POST /mcp/call` dispatcher |
| 8 | `services/api/src/app/mcp/tools/__init__.py` | Imports all tool modules to trigger registration |
| 9 | `services/api/src/app/mcp/tools/history_tools.py` | 6 history tool handlers registered with registry |
| 10 | `services/api/src/app/mcp/tools/spotify_tools.py` | 2 Spotify live tools (`get_top`, `search`) |
| 11 | `services/api/src/app/mcp/tools/ops_tools.py` | 3 ops tools (`sync_status`, `latest_job_runs`, `latest_import_jobs`) |
| 12 | `services/api/tests/test_history/__init__.py` | Test package |
| 13 | `services/api/tests/test_history/test_queries.py` | Tests for raw query functions |
| 14 | `services/api/tests/test_history/test_service.py` | Tests for HistoryService methods |
| 15 | `services/api/tests/test_history/test_router.py` | Tests for direct REST endpoints |
| 16 | `services/api/tests/test_mcp/__init__.py` | Test package |
| 17 | `services/api/tests/test_mcp/test_registry.py` | Tests for tool registration/invocation |
| 18 | `services/api/tests/test_mcp/test_router.py` | Tests for MCP dispatcher endpoints |
| 19 | `services/api/tests/test_mcp/test_history_tools.py` | Tests for history tools via dispatcher |
| 20 | `services/api/tests/test_mcp/test_ops_tools.py` | Tests for ops tools via dispatcher |

## Modified Files

| File | Change |
|------|--------|
| `services/api/src/app/history/__init__.py` | Re-export `router` and `HistoryService` |
| `services/api/src/app/mcp/__init__.py` | Re-export `router` |
| `services/api/src/app/main.py` | Mount history router at `/history` and MCP router at `/mcp` |

---

## Detailed Design

### 1. History Query Service

#### `history/schemas.py` — Response Models

```python
class ArtistCount(BaseModel):
    artist_id: int
    artist_name: str
    play_count: int

class TrackCount(BaseModel):
    track_id: int
    track_name: str
    artist_name: str       # Primary artist
    play_count: int

class HeatmapCell(BaseModel):
    weekday: int           # 0=Monday .. 6=Sunday (ISO)
    hour: int              # 0-23
    play_count: int

class ListeningHeatmap(BaseModel):
    days: int
    total_plays: int
    cells: list[HeatmapCell]

class RepeatStats(BaseModel):
    days: int
    total_plays: int
    unique_tracks: int
    repeat_rate: float     # total / unique
    most_repeated: list[TrackCount]

class CoverageStats(BaseModel):
    days: int
    total_plays: int
    earliest_play: datetime | None
    latest_play: datetime | None
    api_source_count: int
    import_source_count: int
    active_days: int       # Distinct dates with plays
    requested_days: int    # The `days` parameter value

class TasteSummary(BaseModel):
    days: int
    total_plays: int
    unique_tracks: int
    unique_artists: int
    total_ms_played: int
    listening_hours: float
    top_artists: list[ArtistCount]
    top_tracks: list[TrackCount]
    repeat_rate: float
    peak_weekday: int | None     # ISO weekday with most plays
    peak_hour: int | None        # Hour with most plays
    coverage: CoverageStats
```

#### `history/queries.py` — SQLAlchemy Query Builders

All queries follow the same pattern:
1. Calculate `cutoff = datetime.now() - timedelta(days=days)`
2. Filter `plays` by `user_id` and `played_at >= cutoff`
3. JOIN with `tracks`, `track_artists`, `artists` as needed
4. Return raw dicts (service layer converts to Pydantic)

Key queries:
- **`query_top_artists`**: `plays → tracks → track_artists → artists`, `GROUP BY artist.id`, `ORDER BY COUNT DESC`
- **`query_top_tracks`**: `plays → tracks`, `GROUP BY track.id`, `ORDER BY COUNT DESC`, then fetch primary artist name per track
- **`query_heatmap`**: `EXTRACT(DOW/HOUR FROM played_at)` for PostgreSQL, `strftime` for SQLite tests
- **`query_play_stats`**: Single query for total plays, unique tracks, unique artists, total ms_played
- **`query_coverage`**: `CASE WHEN source = 'spotify_api'` breakdowns, `COUNT(DISTINCT DATE(played_at))` for active days

**PostgreSQL vs SQLite compatibility**: The heatmap query needs dialect detection. Use `session.bind.dialect.name` to switch between `EXTRACT(ISODOW FROM ...)` (PostgreSQL) and `CAST(strftime('%w', ...) AS INTEGER)` (SQLite).

#### `history/service.py` — `HistoryService`

Stateless service class that:
- Accepts `(user_id, session, days, limit)` parameters
- Calls query functions from `queries.py`
- Builds Pydantic response models
- `get_taste_summary()` composes results from multiple queries

#### `history/router.py` — Direct REST Endpoints

```
GET /history/users/{user_id}/top-artists?days=90&limit=20
GET /history/users/{user_id}/top-tracks?days=90&limit=20
GET /history/users/{user_id}/heatmap?days=90
GET /history/users/{user_id}/repeat-rate?days=90
GET /history/users/{user_id}/coverage?days=90
GET /history/users/{user_id}/taste-summary?days=90
```

Each endpoint validates user exists (404 if not), uses `Depends(db_manager.dependency)` for session.

### 2. MCP Dispatcher

#### `mcp/schemas.py` — MCP Protocol Models

```python
class MCPToolParam(BaseModel):
    name: str
    type: str              # "int", "str"
    description: str
    required: bool = True
    default: Any = None

class MCPToolDefinition(BaseModel):
    name: str              # e.g. "history.taste_summary"
    description: str
    category: str          # "history", "spotify", "ops"
    parameters: list[MCPToolParam]

class MCPCallRequest(BaseModel):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)

class MCPCallResponse(BaseModel):
    tool: str
    success: bool
    result: Any = None
    error: str | None = None
```

#### `mcp/registry.py` — Tool Registry

```python
ToolHandler = Callable[[dict[str, Any], AsyncSession], Awaitable[Any]]

class MCPToolRegistry:
    def register(name, description, category, parameters) -> decorator
    def get_catalog() -> list[MCPToolDefinition]
    async def invoke(tool_name, args, session) -> Any
    def is_registered(tool_name) -> bool
```

Global singleton: `registry = MCPToolRegistry()`

#### `mcp/tools/history_tools.py`

Registers 6 tools using `@registry.register(...)` decorator. Each handler creates `HistoryService()`, calls the appropriate method, returns `model.model_dump()`.

#### `mcp/tools/spotify_tools.py`

Registers 2 tools:
- **`spotify.get_top`**: Uses `TokenManager(get_settings())` to get access token, creates `SpotifyClient`, calls `get_top_artists()` or `get_top_tracks()`
- **`spotify.search`**: Same token flow, calls `SpotifyClient.search()`

Reuses: `app.auth.tokens.TokenManager`, `shared.spotify.client.SpotifyClient`

#### `mcp/tools/ops_tools.py`

Registers 3 tools with simple DB queries:
- **`ops.sync_status`**: `SELECT * FROM sync_checkpoints WHERE user_id = ?`
- **`ops.latest_job_runs`**: `SELECT * FROM job_runs WHERE user_id = ? ORDER BY started_at DESC LIMIT ?`
- **`ops.latest_import_jobs`**: `SELECT * FROM import_jobs WHERE user_id = ? ORDER BY created_at DESC LIMIT ?`

#### `mcp/router.py`

```python
@router.get("/tools") -> list[MCPToolDefinition]
@router.post("/call") -> MCPCallResponse
```

The `/call` endpoint catches exceptions from handlers and returns `MCPCallResponse(success=False, error=str(exc))` rather than raising HTTP errors — the MCP protocol wraps errors in the response body.

### 3. Router Integration

In `main.py._setup_routers()`, add:
```python
from app.history import router as history_router
from app.mcp import router as mcp_router

self.app.include_router(history_router, prefix="/history", tags=["history"])
self.app.include_router(mcp_router, prefix="/mcp", tags=["mcp"])
```

---

## Implementation Order

1. `history/schemas.py` — Pydantic models (no dependencies)
2. `history/queries.py` — SQL queries (depends on DB models)
3. `history/service.py` — Service layer (depends on schemas + queries)
4. `history/router.py` + `history/__init__.py` — REST endpoints
5. Tests: `test_history/` — test queries and service with sample data
6. `mcp/schemas.py` — MCP protocol models
7. `mcp/registry.py` — Tool registration system
8. `mcp/tools/history_tools.py` — Register history tools
9. `mcp/tools/ops_tools.py` — Register ops tools
10. `mcp/tools/spotify_tools.py` — Register Spotify tools
11. `mcp/tools/__init__.py` + `mcp/router.py` + `mcp/__init__.py` — Dispatcher
12. `main.py` — Mount new routers
13. Tests: `test_mcp/` — registry, router, tool integration tests
14. Run full lint/typecheck/test suite
15. Docker build and verify with real data

## Verification

1. `ruff check` + `ruff format --check` across all packages
2. `mypy` across all packages
3. `pytest services/api/tests/` — all API tests pass (existing + new)
4. `docker-compose up --build` — all services start healthy
5. Manual test via curl:
   - `GET /mcp/tools` returns 11 tools
   - `POST /mcp/call {"tool": "history.taste_summary", "args": {"user_id": 1, "days": 3650}}` returns analysis of 10-year history
   - `GET /history/users/1/top-artists?days=3650` returns top artists directly
   - `POST /mcp/call {"tool": "ops.sync_status", "args": {"user_id": 1}}` returns sync checkpoint
