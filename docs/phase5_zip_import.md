# Phase 5: ZIP Import Processing — Summary & Insights

## What Was Built

Phase 5 implements the full pipeline to upload, parse, normalize, and ingest Spotify "Download your data" ZIP exports into the database. This fills the gap that the Spotify API cannot — providing full listening history going back years.

### New Components

| Component | Files | Purpose |
|-----------|-------|---------|
| **ZIP Import package** | `shared/zip_import/` (5 files) | Format detection, streaming JSON parsing, record normalization |
| **MusicRepository extensions** | `shared/db/operations.py` | 5 new import methods: upsert track/artist from import, insert play, batch processing |
| **ZipImportService** | `collector/zip_import.py` | Orchestrates pending import job processing in the collector |
| **Admin API** | `api/admin/router.py`, `schemas.py` | `POST /admin/users/{id}/import` upload + `GET /admin/import-jobs/{id}` status |
| **Test suite** | 7 test files | 30 new tests covering normalizers, parser, DB operations, service, and endpoints |

### Modified Components

| File | Change |
|------|--------|
| `collector/runloop.py` | Integrated ZIP import as first priority in collector cycle |
| `api/main.py` | Registered admin router at `/admin` prefix |
| `api/settings.py` | Added `UPLOAD_DIR` and `IMPORT_MAX_ZIP_SIZE_MB` |
| `shared/pyproject.toml` | Added `ijson` dependency for streaming JSON parsing |
| `shared/db/base.py` | Added `enum_values()` and `utc_now()` typed helpers |
| All model files | Replaced untyped lambdas with `enum_values`, deprecated `utcnow` with `utc_now` |
| `docker-compose.yml` | Changed Postgres host port to 5434 to avoid collisions |

## Architecture Decisions

### Streaming JSON Parsing
Used `ijson` to parse JSON files inside ZIPs without loading them into memory. This allows processing exports with millions of records within Docker's memory constraints.

### Batch Transactions
Records are committed in batches of 5,000 (configurable). Each batch is its own transaction for crash safety — if the process dies mid-import, only the current batch is lost and the job can be retried.

### Deterministic Local IDs
When ZIP records lack Spotify URIs, we generate `local:<sha1(artist|track|album)>` identifiers. This enables deduplication across re-imports without requiring Spotify API lookups.

### Format Detection
Spotify exports come in two naming conventions, both using the extended format schema:
- **Legacy**: `endsong_*.json`
- **Current**: `Streaming_History_Audio_*.json`

A third format, `StreamingHistory*.json` (no underscores), uses a simpler schema with fewer fields.

## Bugs Found & Fixed

### 1. PostgreSQL Enum Value Mismatch
**Symptom**: `invalid input value for enum importstatus: "PENDING"`

SQLAlchemy's `SQLEnum(SomeEnum)` sends the enum **name** (uppercase) but PostgreSQL expects the **value** (lowercase). Fixed by adding `values_callable=enum_values` to all `SQLEnum` definitions across the codebase.

### 2. Format Detection Misclassification
**Symptom**: Real Spotify export (with `Streaming_History_Audio_*.json` files) parsed as `account_data` format, producing 0 records.

The regex `Streaming_History_Audio_.*\.json` was in `ACCOUNT_DATA_PATTERN` but these files use the **extended** format schema (`ts`, `master_metadata_track_name`, etc.). Moved the pattern to `EXTENDED_HISTORY_PATTERN`.

### 3. Stale Requirements File
**Symptom**: Docker build succeeded but containers failed with `ModuleNotFoundError: No module named 'ijson'`.

`shared/requirements.txt` was not regenerated after adding `ijson` to `pyproject.toml`. Fixed by running `pip-compile`.

## Test Results

- **API tests**: 92 passed (30 new for Phase 5)
- **Collector tests**: 28 passed (4 new for Phase 5)
- **Total**: 120 tests, all passing

## Production Verification

Successfully imported a real Spotify Extended Streaming History export:
- **18,902 plays** ingested (48 skipped as duplicates/incomplete)
- **4,444 tracks** and **1,632 artists** created
- **Date range**: 2015-07-01 to 2026-02-06 (10+ years)
- Processing time: ~53 seconds for ~19k records across 2 JSON files

---

## Suggestions for Phase 6

### Priority: MCP Tool Endpoints & History Queries

With 10+ years of listening data now in the database, the next logical step is making it queryable via MCP tools for ChatGPT/assistant integration.

#### Recommended scope:

1. **History query service** (`api/history/`)
   - `taste_summary(days, user_id)` — top artists, genres, listening hours, diversity metrics
   - `top_artists(days, limit, user_id)` and `top_tracks(days, limit, user_id)` — leaderboards by play count
   - `listening_heatmap(days, user_id)` — weekday/hour distribution matrix
   - `repeat_rate(days, user_id)` — how often tracks are replayed
   - `coverage(days, user_id)` — data completeness (API vs import, gaps)

2. **MCP dispatcher** (`api/mcp/`)
   - `GET /mcp/tools` — tool catalog with schemas
   - `POST /mcp/call` — tool invocation endpoint
   - Route `history.*` tools to the history service
   - Route `ops.*` tools to sync/import status queries

3. **Spotify live tools** (lower priority, requires active OAuth)
   - `spotify.get_top(entity, time_range, limit, user_id)` — Spotify's native "top" endpoint
   - `spotify.search(q, type, limit, user_id)` — search

#### Key considerations:
- History queries need efficient SQL — add appropriate indexes, consider materialized views for heavy aggregations
- MCP response format should be concise text summaries (not raw JSON) for assistant consumption
- Time range parameters should handle the full 10-year span from imports gracefully
- Consider caching for expensive queries (taste_summary over large date ranges)

### Also Consider:
- **Admin frontend** (`frontend/`) — the skeleton exists but has no templates; useful for monitoring imports, viewing sync status, browsing logs
- **Structured DB logging** — the `logs` table exists but nothing writes to it yet; the collector could emit structured log events during import/sync
- **Track enrichment** — resolve `local:*` track IDs to real Spotify IDs via search API, backfill audio features
