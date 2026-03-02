# Phase 9 — MCP Memory: Playlist Ledger

## Context

Phases 0-8 are complete. The memory subsystem (Phase 7-8) established taste profiles and preference events. Phase 9 extends this with a **playlist ledger** — a durable record of every assistant-created/edited playlist with full event history and snapshot-based reconstruction. The ledger is the canonical record even when Spotify read-back is blocked (403, missing scopes).

---

## Implementation Steps

### Step 1: New Enums

**File:** `services/shared/src/shared/db/enums.py`

Add two new StrEnums (following existing `PreferenceEventSource`/`PreferenceEventType` pattern):

```python
class PlaylistSnapshotSource(enum.StrEnum):
    CREATE = "create"
    PERIODIC = "periodic"
    MANUAL = "manual"

class PlaylistEventType(enum.StrEnum):
    ADD_TRACKS = "ADD_TRACKS"
    REMOVE_TRACKS = "REMOVE_TRACKS"
    REORDER = "REORDER"
    UPDATE_META = "UPDATE_META"
```

### Step 2: New DB Models

**File:** `services/shared/src/shared/db/models/memory.py` (extend existing)

Add 3 new models alongside existing `TasteProfile` and `PreferenceEvent`:

**`MemoryPlaylist`** — Playlist metadata:
- `playlist_id` (String 80, PK) — Spotify playlist ID
- `user_id` (BigInteger FK → users, indexed)
- `name` (String 500)
- `description` (Text, nullable)
- `intent_tags` (JSONB, default `[]`)
- `seed_context` (JSONB, default `{}`)
- `latest_snapshot_id` (UUID FK → playlist_snapshots, nullable)
- `idempotency_key` (String 255, nullable, unique) — for create dedup
- `created_at`, `updated_at` (DateTime timezone=True)

**`PlaylistSnapshot`** — Point-in-time track lists:
- `snapshot_id` (UUID PK)
- `playlist_id` (String 80 FK → memory_playlists, indexed)
- `created_at` (DateTime timezone=True)
- `track_ids` (JSONB) — ordered array of Spotify track IDs
- `source` (Enum PlaylistSnapshotSource)

**`PlaylistEvent`** — Append-only mutation ledger:
- `event_id` (UUID PK)
- `playlist_id` (String 80 FK → memory_playlists, indexed)
- `user_id` (BigInteger FK → users)
- `timestamp` (DateTime timezone=True)
- `type` (Enum PlaylistEventType)
- `payload_json` (JSONB)
- `client_event_id` (UUID, nullable, unique) — for mutation dedup
- Index on `(playlist_id, timestamp)` for event ordering

### Step 3: Update Model Imports

**File:** `services/shared/src/shared/db/models/__init__.py`

Add imports for `MemoryPlaylist`, `PlaylistSnapshot`, `PlaylistEvent` to `__all__`.

### Step 4: Alembic Migration

**File:** `services/api/alembic/versions/007_playlist_ledger.py`

- `down_revision = "006_memory_taste"`
- Create `memory_playlists`, `playlist_snapshots`, `playlist_events` tables
- Create enum types: `playlist_snapshot_source`, `playlist_event_type`
- Create indexes: `(playlist_id, timestamp)` on events, `user_id` on playlists
- Downgrade drops tables + enum types

### Step 5: New MCP Tool Handlers

**File:** `services/api/src/app/mcp/tools/playlist_ledger_tools.py` (new)

Class: `PlaylistLedgerToolHandlers` (follows `MemoryToolHandlers` pattern)

**5 tools:**

1. **`memory.log_playlist_create(user_id, playlist_id, name, track_ids, description?, intent_tags?, seed_context?, idempotency_key?)`**
   - Validates user_id, playlist_id, name, track_ids (non-empty array)
   - Parses JSON string params (ChatGPT compat): intent_tags, seed_context, track_ids
   - Creates `MemoryPlaylist` + initial `PlaylistSnapshot` (source=create)
   - Sets `latest_snapshot_id` to the new snapshot
   - Idempotent: if `idempotency_key` matches existing record, return existing (no error)
   - Returns: `{playlist_id, snapshot_id, created_at, stored_track_count}`

2. **`memory.log_playlist_mutation(user_id, playlist_id, type, payload, client_event_id?)`**
   - Validates playlist exists and belongs to user
   - Validates `type` against PlaylistEventType enum
   - Validates payload structure per type (ADD_TRACKS/REMOVE_TRACKS need `track_ids`, REORDER needs `track_ids`, UPDATE_META needs at least one field)
   - Parses JSON string payload (ChatGPT compat)
   - Idempotent: if `client_event_id` matches existing event, return existing
   - After insert, count events since last snapshot — if >= 10, auto-create periodic snapshot via reconstruction
   - Returns: `{event_id, playlist_id, timestamp, new_snapshot_id?}`

3. **`memory.get_playlists(user_id, limit?, cursor?)`**
   - List playlists for user, ordered by `updated_at DESC`
   - Cursor-based pagination using `updated_at` of last item
   - For each playlist, compute `track_count` from latest snapshot's `track_ids` length
   - Returns: `{items: [{playlist_id, name, created_at, updated_at, intent_tags, track_count}], next_cursor}`

4. **`memory.get_playlist(user_id, playlist_id, include_events_limit?)`**
   - Validates playlist exists and belongs to user
   - Loads playlist metadata + latest snapshot + recent events (default 50, max 500)
   - Returns: `{playlist, latest_snapshot, recent_events}`

5. **`memory.reconstruct_playlist(user_id, playlist_id, at_time?)`**
   - Finds nearest snapshot before `at_time` (or latest if no `at_time`)
   - Applies subsequent events (ADD_TRACKS, REMOVE_TRACKS, REORDER) in order
   - Returns: `{playlist_id, as_of, track_ids, reconstruction: {used_snapshot_id, applied_event_count}}`

**Reconstruction logic:**
- Start from snapshot `track_ids`
- For each event after snapshot:
  - `ADD_TRACKS`: append track_ids (or insert at position if `insert_at` specified)
  - `REMOVE_TRACKS`: remove matching track_ids
  - `REORDER`: replace entire list with payload track_ids
  - `UPDATE_META`: skip (no track changes)

**Snapshot compaction logic (in `log_playlist_mutation`):**
- After inserting event, count events since latest snapshot
- If count >= 10: reconstruct current track list, create new `PlaylistSnapshot` (source=periodic), update `latest_snapshot_id`

### Step 6: Register Tool Module

**File:** `services/api/src/app/mcp/tools/__init__.py`

Add: `import app.mcp.tools.playlist_ledger_tools as playlist_ledger_tools  # noqa: F401`

### Step 7: Update ChatGPT OpenAPI Schema

**File:** `docs/chatgpt-openapi.json`

- Add 5 tools to tool enum: `memory.log_playlist_create`, `memory.log_playlist_mutation`, `memory.get_playlists`, `memory.get_playlist`, `memory.reconstruct_playlist`
- Add new parameters:
  - `intent_tags` (string, JSON array as string)
  - `seed_context` (string, JSON object as string)
  - `mutation_type` (string, enum: ADD_TRACKS/REMOVE_TRACKS/REORDER/UPDATE_META)
  - `include_events_limit` (integer)
  - `cursor` (string)
  - `at_time` (string, date-time)
  - `idempotency_key` (string)
  - `client_event_id` (string)
- Note: reuse existing `playlist_id`, `name`, `description`, `track_ids`, `payload`, `user_id`, `limit`

### Step 8: Update ChatGPT GPT Setup Guide

**File:** `docs/chatgpt-gpt-setup.md`

- Add PLAYLIST MEMORY section to instructions (per plan-v2.md Phase 9 changelog)
- Add 5 tools to AVAILABLE TOOLS list under "Memory (persistent taste preferences)"
- Update session bootstrap to optionally call `memory.get_playlists`
- Add conversation starter: "What playlists did you make for me?"
- Add Phase 9 changelog entry

### Step 9: Tests

**File:** `services/api/tests/test_mcp/test_playlist_ledger_tools.py` (new)

Following `test_memory_tools.py` pattern (SQLite in-memory, override deps, seeded user):

**Test categories:**
- **Create:** happy path, idempotency (same key returns existing), validation errors (missing fields, empty track_ids)
- **Mutation:** ADD_TRACKS, REMOVE_TRACKS, REORDER, UPDATE_META — each with correct payload validation
- **Mutation idempotency:** same client_event_id returns existing event
- **Snapshot compaction:** after 10 mutations, new snapshot auto-created
- **Get playlists:** list with pagination (cursor), empty list, track_count accuracy
- **Get playlist:** full detail with events, NOT_FOUND for missing/wrong-user
- **Reconstruct:** from snapshot + events, at_time filtering, no snapshot case
- **User isolation:** user A can't see user B's playlists
- **ChatGPT compat:** JSON string params for track_ids, intent_tags, seed_context, payload

### Step 10: Update plan-v2.md Status

**File:** `docs/plan-v2.md`

Mark Phase 9 as **DONE** in the status table.

---

## Files Summary

**New files (3):**
- `services/api/alembic/versions/007_playlist_ledger.py`
- `services/api/src/app/mcp/tools/playlist_ledger_tools.py`
- `services/api/tests/test_mcp/test_playlist_ledger_tools.py`

**Modified files (6):**
- `services/shared/src/shared/db/enums.py` — add 2 enums
- `services/shared/src/shared/db/models/memory.py` — add 3 models
- `services/shared/src/shared/db/models/__init__.py` — add imports
- `services/api/src/app/mcp/tools/__init__.py` — import new module
- `docs/chatgpt-openapi.json` — add 5 tools + params
- `docs/chatgpt-gpt-setup.md` — add playlist memory instructions

**Updated (1):**
- `docs/plan-v2.md` — mark Phase 9 done

---

## Verification

1. **Lint + Type check:** `make lint && make typecheck`
2. **Tests:** `make test` — all existing + new tests pass
3. **Docker integration:**
   - `docker-compose up --build` — all services start, healthz responds
   - Run migration: `docker-compose exec api alembic upgrade head`
   - Test via curl:
     ```bash
     # Create playlist in memory
     curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
       -d '{"tool":"memory.log_playlist_create","user_id":1,"playlist_id":"test123abc","name":"Test Playlist","track_ids":["track1","track2"]}' \
       http://localhost:8000/mcp/call

     # Get playlists
     curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
       -d '{"tool":"memory.get_playlists","user_id":1}' \
       http://localhost:8000/mcp/call

     # Log mutation
     curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
       -d '{"tool":"memory.log_playlist_mutation","user_id":1,"playlist_id":"test123abc","mutation_type":"ADD_TRACKS","payload":"{\"track_ids\":[\"track3\"]}"}' \
       http://localhost:8000/mcp/call

     # Get playlist detail
     curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
       -d '{"tool":"memory.get_playlist","user_id":1,"playlist_id":"test123abc"}' \
       http://localhost:8000/mcp/call

     # Reconstruct
     curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
       -d '{"tool":"memory.reconstruct_playlist","user_id":1,"playlist_id":"test123abc"}' \
       http://localhost:8000/mcp/call
     ```
   - `docker-compose down` after testing
4. **Tool catalog:** `GET /mcp/tools` shows 5 new tools in memory category
