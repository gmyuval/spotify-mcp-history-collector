# Fix Plan: Large Spotify Playlist Truncation at 100 Tracks

## Problem

Playlists with >100 tracks are truncated to exactly 100 tracks when fetched via `spotify.get_playlist` or `memory.backfill_playlist`. The `tracks_mismatch_warning` correctly fires but the data is incomplete.

**Affected playlists:**
- Metal Classics (`5qsaQsbyxZZXI2QHUNILRO`) — 180 tracks, returns 100
- Classic Rock Classics (`2vCR0MBUZ8XLDtcLO1mlTx`) — 300 tracks, returns 100

Small/medium playlists (<100 tracks) work correctly.

## Root Cause

Spotify reduced the max `limit` for `GET /playlists/{id}/tracks` from 100 to 50. The latest Spotify API reference states:

> `limit: Default: 20. Minimum: 1. Maximum: 50. Range: 0 - 50`

Our `get_playlist_all_tracks()` in `services/shared/src/shared/spotify/client.py` requests `limit=100`. When Spotify receives a limit above its max, it returns up to 100 items (legacy tolerance) but does NOT set the `next` URL — causing the pagination loop to exit after one iteration.

## Code Paths Investigated

1. **`spotify.get_playlist` MCP handler** (`services/api/src/app/mcp/tools/playlist_tools.py:264`) — calls `client.get_playlist_all_tracks(playlist_id)` correctly
2. **`get_playlist_all_tracks()`** (`services/shared/src/shared/spotify/client.py:302-333`) — pagination loop follows `page.next`, but `page.next` is `None` after the first page due to oversized limit
3. **Cache layer** (`services/api/src/app/cache/service.py`) — correctly detects stale entries (`len(cached_tracks) >= cached_total` guard at line 209)
4. **`memory.backfill_playlist`** (`services/api/src/app/mcp/tools/playlist_ledger_tools.py:839`) — delegates to `get_playlist()`, inherits the same truncation

## Changes

### 1. Reduce `page_size` to 50 (`client.py`)

- Change default `page_size` from `100` to `50`
- Change clamp: `min(page_size, 50)` instead of `min(page_size, 100)`
- Matches Spotify's current documented maximum

### 2. Add offset-based pagination fallback (`client.py`)

If `page.next` is `None` but `len(all_items) < page.total`, manually compute the next offset and continue. Guards against Spotify API quirks where `next` is unexpectedly absent.

### 3. Add debug logging to pagination loop (`client.py`)

Log each page: offset, items received, `next` URL presence, running total. Aids future debugging.

### 4. Update pagination tests

Add/update tests for:
- Playlist with >100 tracks (multi-page pagination)
- `next` URL absent but items remaining (fallback path)
- Normal single-page playlist (no regression)

### 5. Docker integration test

- `docker-compose up --build`
- Call `spotify.get_playlist` for the two affected playlists via MCP
- Verify `tracks_returned == tracks_total` and no `tracks_mismatch_warning`
- `docker-compose down`

## Not in Scope

- No ChatGPT instruction changes — tool shape unchanged
- No new MCP tools — internal pagination is sufficient
- No database migrations
- No schema changes

## Acceptance Criteria

1. Metal Classics: `tracks_returned == tracks_total` (180)
2. Classic Rock Classics: `tracks_returned == tracks_total` (300)
3. Small playlists: no regression
4. All existing tests pass
