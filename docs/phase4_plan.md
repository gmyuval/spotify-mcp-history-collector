# Phase 4: Initial Sync, Job Tracking & Collector Run Loop

## Objective

Implement the initial sync service (backward paging with stop conditions), job tracking lifecycle, and the autonomous collector run loop that ties initial sync and incremental polling together.

---

## New Files

| # | File | Purpose |
|---|------|---------|
| 1 | `services/collector/src/collector/job_tracking.py` | `JobTracker` class — create/complete/fail `JobRun` records |
| 2 | `services/collector/src/collector/initial_sync.py` | `InitialSyncService` — backward paging with 5 stop conditions |
| 3 | `services/collector/src/collector/runloop.py` | `CollectorRunLoop` — priority-based cycle (imports → sync → poll) |
| 4 | `services/collector/tests/test_initial_sync.py` | Tests for all stop conditions + checkpoint updates |
| 5 | `services/collector/tests/test_job_tracking.py` | Tests for job lifecycle (start/complete/fail) |
| 6 | `services/collector/tests/test_runloop.py` | Tests for priority ordering and pause/skip logic |

## Modified Files

| File | Change |
|------|--------|
| `services/collector/src/collector/main.py` | Replace placeholder with real entry point (settings, run loop, SIGTERM) |
| `services/collector/src/collector/polling.py` | Integrate `JobTracker` — record poll results in `JobRun` |

---

## Detailed Design

### 1. `job_tracking.py` — Job Lifecycle Management

```python
class JobTracker:
    async def start_job(user_id, job_type, session) -> JobRun
    async def complete_job(job_run, fetched, inserted, skipped, session) -> None
    async def fail_job(job_run, error_message, session) -> None
```

- Creates `JobRun` record with `status=running` and `started_at=now`
- `complete_job` sets `status=success`, timestamps, record stats
- `fail_job` sets `status=error` with error message
- All operations flush immediately for visibility

### 2. `initial_sync.py` — Backward Paging Service

`InitialSyncService` class mirroring `PollingService` pattern:

- **Constructor**: Takes `CollectorSettings`
- **`sync_user(user_id, session)`**: Main method
  1. Check `SyncCheckpoint` — skip if `initial_sync_completed_at` is set
  2. Set `initial_sync_started_at`, `status=syncing`
  3. Loop: `SpotifyClient.get_recently_played(limit=50, before=cursor)`
  4. Each batch: `MusicRepository.batch_process_play_history()`
  5. Track `oldest_played_at` → next `before = oldest_played_at_ms - 1`

**5 Stop Conditions** (spec Section 5.1):
1. Empty batch (`len(response.items) == 0`)
2. No progress (`oldest_played_at` unchanged from previous batch)
3. Reached `INITIAL_SYNC_MAX_DAYS` (oldest play > N days ago)
4. Reached `INITIAL_SYNC_MAX_REQUESTS` (request counter)
5. Excessive 429s (caught via `SpotifyRateLimitError`)

**On success**: `initial_sync_completed_at` + `initial_sync_earliest_played_at` + `status=idle`
**On error**: `status=error` + `error_message`, leave `completed_at` null

### 3. `runloop.py` — Main Collector Loop

```python
class CollectorRunLoop:
    async def run(shutdown_event: asyncio.Event) -> None
```

Each cycle:
1. Query all users with `SyncCheckpoint.status != paused`
2. For each user (with concurrency semaphore):
   - If `INITIAL_SYNC_ENABLED` and `initial_sync_completed_at is None` → initial sync
   - Else → incremental poll
3. Sleep `COLLECTOR_INTERVAL_SECONDS`
4. ZIP import processing is a placeholder (Phase 5)

Error handling: per-user exceptions logged and skipped, loop continues.

### 4. Updated `main.py`

- Load `CollectorSettings`
- Create `DatabaseManager`
- Register SIGTERM/SIGINT → set `asyncio.Event`
- Run `CollectorRunLoop.run(shutdown_event)`
- Dispose DB on exit

### 5. Updated `polling.py`

- Add `JobTracker` integration: create `JobRun` before poll, complete/fail after
- Set `SyncCheckpoint.last_poll_started_at` before API call

---

## Tests

### `test_initial_sync.py`
- Stop: empty batch (API returns 0 items)
- Stop: no progress (oldest `played_at` static)
- Stop: max days reached
- Stop: max requests reached
- Stop: rate limit error (`SpotifyRateLimitError`)
- Happy path: 2 batches then empty → checkpoint fields correct
- Skip: already-completed sync

### `test_job_tracking.py`
- Start job → `status=running`, timestamps set
- Complete job → `status=success`, stats recorded
- Fail job → `status=error`, error message set

### `test_runloop.py`
- Runs initial sync for incomplete users
- Runs polling for users with completed sync
- Skips paused users
- Continues after per-user error

---

## Conventions

- **DB datetimes**: Strip `tzinfo` before DB writes (`.replace(tzinfo=None)`)
- **Token management**: Reuse `CollectorTokenManager` + callback pattern from `polling.py`
- **Test isolation**: SQLite in-memory with BigInteger compilation (`conftest.py`)
- **No `from __future__ import annotations`**: Python 3.14 PEP 649

---

## Definition of Done

- [ ] All 5 stop conditions tested and working
- [ ] `SyncCheckpoint` fields updated correctly
- [ ] `JobRun` records created for poll and initial_sync
- [ ] Collector runs autonomously: initial sync → incremental polling
- [ ] Graceful shutdown on SIGTERM
- [ ] Paused users skipped
- [ ] Per-user errors don't crash the loop
- [ ] `mypy` passes on all collector modules
- [ ] All tests pass via `cd services/collector && pytest tests/`
