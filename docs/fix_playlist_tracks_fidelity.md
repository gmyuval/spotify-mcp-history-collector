# Fix Plan: Playlist Track Retrieval Fidelity

**Issue:** `docs/spotify_playlist_tracks_fidelity_issue.md`
**Date:** 2026-03-05
**Branch:** `fix/playlist-tracks-fidelity`

## Diagnosis

Three root causes identified in the codebase:

### 1. Unavailable tracks silently dropped (API path)
**File:** `services/api/src/app/mcp/tools/playlist_tools.py` line 225
```python
if item.track:  # None tracks (removed/unavailable) are skipped
```
When a track is removed or unavailable in the user's market, Spotify returns
`track: null` in the playlist item. These are silently skipped, causing
`len(tracks) < tracks_total`.

### 2. Embed tracks without IDs silently dropped
**File:** `services/shared/src/shared/spotify/embed.py` line 189
```python
if not track_id:
    continue  # tracks without a valid spotify:track: URI are skipped
```

### 3. Backfill filters null IDs
**File:** `services/api/src/app/mcp/tools/playlist_ledger_tools.py` line 789
```python
track_ids = [t["id"] for t in playlist_data.get("tracks", []) if t.get("id")]
```

### Why duplicates appear correct but counts mismatch
Duplicates are preserved (no de-dup). But `tracks_total` counts all items
including unavailable ones that are dropped, so e.g. `tracks_total=67` but
only 64 items are returned.

### No mismatch detection
No `tracks_returned` count or warning when `len(tracks) != tracks_total`.

## Implementation Plan

### Step 1: Include unavailable tracks as placeholders (API path)
**File:** `services/api/src/app/mcp/tools/playlist_tools.py`

In `get_playlist()`, when `item.track` is None, emit a placeholder:
```python
{"id": None, "name": None, "artists": [], "added_at": item.added_at, "unavailable": True}
```
This preserves positional integrity and makes the count match `tracks_total`.

### Step 2: Include unresolvable tracks as placeholders (embed path)
**Files:**
- `services/shared/src/shared/spotify/models.py` — make `EmbedTrackItem.track_id` optional (`str | None`)
- `services/shared/src/shared/spotify/embed.py` — emit `EmbedTrackItem` with `track_id=None` instead of `continue`
- `services/api/src/app/mcp/tools/playlist_tools.py` — in embed handler, emit placeholder for None track_id items

### Step 3: Add mismatch reporting
**File:** `services/api/src/app/mcp/tools/playlist_tools.py`

Add to the response dict:
- `tracks_returned: int` — actual number of track entries returned (including placeholders)
- `tracks_unavailable: int` — count of unavailable/placeholder entries
- When `tracks_returned != tracks_total`, add `tracks_mismatch_warning: str`

### Step 4: Update backfill to handle unavailable tracks
**File:** `services/api/src/app/mcp/tools/playlist_ledger_tools.py`

- Filter out unavailable entries (null IDs) when building `track_ids` list for snapshot storage (snapshots are ID-based, can't store null)
- Add `unavailable_count` to the backfill result so callers know about the gap
- Add `tracks_total` from the playlist data to the result for comparison

### Step 5: Tests
- API path with None tracks produces placeholder entries
- Embed path with missing URIs produces placeholder entries
- Mismatch warning appears when counts differ
- Backfill reports unavailable_count correctly
- Cache stores and serves placeholder entries correctly

## Files Modified (Expected)
1. `services/shared/src/shared/spotify/models.py`
2. `services/shared/src/shared/spotify/embed.py`
3. `services/api/src/app/mcp/tools/playlist_tools.py`
4. `services/api/src/app/mcp/tools/playlist_ledger_tools.py`
5. `services/api/tests/test_mcp/test_playlist_tools.py` (new/modified tests)
6. `services/shared/tests/test_spotify/test_embed.py` (new/modified tests)

## No Migration Needed
No database schema changes. Snapshots already store `track_ids: list[str]` —
unavailable tracks are simply excluded from the stored list with an
`unavailable_count` reported to the caller.
