# Bug Report / Fix Request: Large Spotify playlists are truncated at 100 tracks during backfill

## Summary
When backfilling Spotify playlists into MCP memory, `spotify.get_playlist` works correctly for small and medium playlists, but for **large playlists (>100 tracks)** it returns only the **first 100 items** even when `tracks_total` is much larger.

This blocks complete backfill for large reference/library playlists, because we can only retrieve a partial ordered track list.

## Current Status
### Working
- Small and medium playlists:
  - Playlist metadata is returned correctly
  - Track items are returned
  - Ordered `track_ids` can be logged into memory
- Private playlists:
  - Previously blocked by 403
  - Now fixed for tested private playlist(s)

### Still broken
- Large playlists over 100 tracks are truncated to 100 items
- No paginated playlist-tracks tool is exposed to the GPT/tool surface to fetch the remaining items

## Evidence / Observed Behavior

### 1) Metal Classics
- **playlist_id:** `5qsaQsbyxZZXI2QHUNILRO`
- **name:** `Metal Classics`
- **tracks_total:** `180`
- **tracks_returned:** `100`
- Response includes:
  - `tracks_mismatch_warning: "Spotify reports 180 tracks but 100 were returned. 0 unavailable placeholder(s) included."`

### 2) Classic Rock Classics
- **playlist_id:** `2vCR0MBUZ8XLDtcLO1mlTx`
- **name:** `Classic Rock Classics`
- **tracks_total:** `300`
- **tracks_returned:** `100`
- Response includes:
  - `tracks_mismatch_warning: "Spotify reports 300 tracks but 100 were returned. 0 unavailable placeholder(s) included."`

### Contrast: smaller playlists work
Examples that were successfully retrieved and backfilled end-to-end:
- `Upbeat Rotation + Breathers (Last 60 Days vibe)` — 45 tracks
- `Steel, Spark and Benediction` — 57 tracks
- `Symphonic mix 2025-01-24` — 58 tracks
- `some symphonic Metal` — 60 tracks
- `Bridges & Crossroads` — 40 tracks
- `Retroactive: Fresh From the Archives` — 51 tracks

This strongly suggests the remaining issue is **pagination / large playlist retrieval**, not general playlist access.

## Impact
- Large playlists cannot be backfilled accurately into memory
- Any taste analysis based on those playlists is incomplete
- Ordered track lists in memory would be partial if logged as-is
- The assistant has to stop and avoid writing incomplete data to memory
- Two known playlists currently blocked from completion:
  - `Metal Classics`
  - `Classic Rock Classics`

## Root Cause Hypothesis
Most likely, `spotify.get_playlist` is currently returning only the **first page** of playlist items (Spotify standard page size often defaults/caps at 100) and is not internally paginating across the remaining pages.

The fact that:
- `tracks_total` is correct
- `tracks_returned` is capped at 100
- a mismatch warning is present

...strongly indicates the connector already knows more items exist, but does not fetch them all.

## Expected Behavior
For any playlist, including large playlists:
- the MCP tool should return the **full ordered playlist item list**
- `len(tracks)` should equal `tracks_total`, unless there are explicit unavailable placeholders or other documented exceptions
- duplicates should be preserved if they exist in the playlist
- the assistant should be able to use the returned `track_ids` directly for `memory.log_playlist_create`

## Actual Behavior
For playlists with more than 100 items:
- `spotify.get_playlist` returns only the first 100 tracks
- `tracks_total` is greater than `tracks_returned`
- assistant cannot complete backfill without risking partial/inaccurate memory records

## Reproduction Steps
1. Call:
   - `spotify.get_playlist(user_id=1, playlist_id="5qsaQsbyxZZXI2QHUNILRO")`
2. Observe:
   - `tracks_total = 180`
   - `tracks_returned = 100`
   - mismatch warning present

3. Call:
   - `spotify.get_playlist(user_id=1, playlist_id="2vCR0MBUZ8XLDtcLO1mlTx")`
4. Observe:
   - `tracks_total = 300`
   - `tracks_returned = 100`
   - mismatch warning present

## Proposed Fixes

### Option A (preferred): make `spotify.get_playlist` internally paginate
Update `spotify.get_playlist` so that when tracks are requested, it:
1. fetches the first page of playlist items
2. continues fetching subsequent pages until all items are retrieved
3. returns the complete ordered list in `tracks`

#### Recommended behavior
- Keep current tool name and shape
- Internally page through Spotify playlist items until:
  - all tracks are fetched, or
  - a documented hard cap is reached
- Return:
  - `tracks_total`
  - `tracks`
  - `tracks_returned`
  - optionally `fully_loaded: true|false`

#### Benefits
- No GPT/tool wiring changes required
- Simplest UX for the assistant
- Best backward compatibility

### Option B: expose a paginated tool for playlist items
Add a dedicated tool, for example:

#### `spotify.get_playlist_tracks`
**Inputs**
- `playlist_id: string`
- `limit: integer` (<=100)
- `offset: integer` (>=0)

**Outputs**
- `items: [{ id, name?, artists?, added_at? }]`
- `total: integer`
- `next_offset: integer | null`

#### Benefits
- Explicit pagination
- More scalable for very large playlists
- Easier to debug and reason about in tooling

#### Tradeoff
- GPT/tool registry must expose the new tool
- Assistant logic must iterate pages before logging to memory

### Option C: add an `include_all_tracks` flag
Extend `spotify.get_playlist` with something like:
- `include_all_tracks: true`

If true:
- the connector internally paginates and returns all tracks

This is essentially Option A with explicit control over performance cost.

## Recommended Implementation Details
- Preserve track order exactly as Spotify returns it
- Preserve duplicates if the playlist contains duplicate items
- Include placeholders or explicit null IDs only if Spotify returns unavailable items and you need to preserve positional fidelity
- Return a field such as:
  - `tracks_returned`
  - `tracks_total`
  - `fully_loaded`
  - `pagination_used`
- If internal pagination fails mid-way:
  - return partial results only with a strong failure indicator
  - do not silently imply completeness

## Acceptance Criteria
1. For `Metal Classics` (`5qsaQsbyxZZXI2QHUNILRO`):
   - `tracks_total = 180`
   - `tracks_returned = 180`
   - returned order matches Spotify playlist order

2. For `Classic Rock Classics` (`2vCR0MBUZ8XLDtcLO1mlTx`):
   - `tracks_total = 300`
   - `tracks_returned = 300`
   - returned order matches Spotify playlist order

3. For smaller playlists:
   - existing behavior remains unchanged
   - no regressions in metadata or track retrieval

4. Assistant can then call:
   - `memory.log_playlist_create(...)`
   using the full ordered `track_ids` list for those playlists

## Optional Additional Improvements
- Add `fully_loaded: true|false` to `spotify.get_playlist`
- Add `partial_reason` when incomplete
- Add `max_page_size_used`
- Add debug logging when pagination occurs
- Add unit/integration tests for:
  - playlist with 50 tracks
  - playlist with 180 tracks
  - playlist with 300 tracks
  - playlist with duplicates
  - private playlist
  - unavailable/market-restricted items

## Why this matters
The MCP memory system is now working well for:
- taste profiles
- playlist logging
- origin tagging
- search and retrieval

The remaining limitation is specifically on the Spotify connector side for large playlists. Fixing this will allow complete backfill of the final unlogged reference playlists and make playlist-based taste analysis much more reliable.

## Blocked Playlists Pending Fix
These two playlists should be retried after the fix:
- `Metal Classics` — `5qsaQsbyxZZXI2QHUNILRO`
- `Classic Rock Classics` — `2vCR0MBUZ8XLDtcLO1mlTx`
