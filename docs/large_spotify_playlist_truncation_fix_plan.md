# Fix Plan: Large Spotify Playlist Truncation at 100 Tracks

> **Status: COMPLETE** — Merged in PR #42 (2026-03-08). See commit history for full implementation.

## Problem

Playlists with >100 tracks are truncated to exactly 100 tracks when fetched via `spotify.get_playlist` or `memory.backfill_playlist`. The `tracks_mismatch_warning` correctly fires but the data is incomplete.

**Affected playlists:**
- Metal Classics (`5qsaQsbyxZZXI2QHUNILRO`) — 180 tracks, returns 100
- Classic Rock Classics (`2vCR0MBUZ8XLDtcLO1mlTx`) — 300 tracks, returns 100

Small/medium playlists (<100 tracks) work correctly.

## Root Cause (confirmed via production logs)

**`GET /playlists/{id}/tracks` returns 403 Forbidden** in Spotify's development mode for non-owned playlists. The existing embed fallback only extracts ~100 tracks with no pagination.

The flow was:
1. `GET /playlists/{id}` → 200 OK (metadata + first 100 embedded tracks)
2. `GET /playlists/{id}/tracks?limit=50&offset=0` → **403 Forbidden**
3. Token refresh + retry → still 403
4. Embed fallback → 100 tracks from HTML (no pagination)

### Investigation timeline

1. **Initial hypothesis (wrong):** Spotify reduced max `limit` from 100 to 50, breaking pagination. Fix: reduced page_size to 50 and added offset fallback. Deployed — bug persisted.

2. **Production logs revealed:** The `/tracks` endpoint returns 403 entirely. The page_size was irrelevant.

3. **Attempted fix (broken):** Added `get_playlist_all_tracks_via_metadata()` to paginate via `GET /playlists/{id}?offset=X&limit=Y`. Deployed — caused duplication bug (200 tracks for 180-track playlist).

4. **Final discovery:** `GET /playlists/{id}?offset=X` does NOT paginate embedded tracks. Spotify ignores offset/limit params and always returns the first 100 tracks, causing duplicates.

## Final Fix

When `GET /playlists/{id}/tracks` returns 403:
1. Token refresh + retry `/tracks` (existing)
2. **Use `pl.tracks.items`** from the already-fetched metadata response — no separate API call needed
3. Embed fallback (last resort if metadata is also 403)

This correctly returns the first 100 tracks from the metadata response with `tracks_source: "api_metadata"` and a mismatch warning when `tracks_total > 100`.

### Limitation

In Spotify's development mode, only the first ~100 tracks of non-owned playlists are accessible. Full track lists require either:
- **Extended Quota Mode** approval from Spotify
- **Manual backfill** via `memory.backfill_playlist` with `track_ids` parameter

## Changes Made

### `services/shared/src/shared/spotify/client.py`
- Reduced `page_size` default from 100 to 50 (matching current Spotify API limits)
- Added offset-based fallback pagination when `next` URL is absent
- Added debug logging to pagination loop

### `services/api/src/app/mcp/tools/playlist_tools.py`
- When `/tracks` returns 403 after token refresh, use `pl.tracks.items` from the metadata response
- Set `tracks_source = "api_metadata"` for these responses

### Tests
- Added pagination tests (offset fallback, 180-track large playlist)
- Added metadata tracks fallback handler test
- Updated existing 403/embed tests for new fallback chain

## Not in Scope
- No ChatGPT instruction changes — tool shape unchanged
- No new MCP tools
- No database migrations
