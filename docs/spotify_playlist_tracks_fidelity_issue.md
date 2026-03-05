# Issue: Playlist track retrieval is incomplete / inconsistent (tracks_total mismatch)

## Summary
During playlist backfill into MCP memory, `spotify.get_playlist` returns a `tracks` array, but it sometimes **does not match** Spotify’s `tracks_total`. This causes incomplete backfills (missing track IDs) and/or silently de-duplicates duplicates returned by the tool. We need a **high-fidelity playlist-items retrieval** path so backfills can be exact and repeatable.

## Observed Behavior (Evidence)
When backfilling playlists into MCP memory:

- **Steel & Starlit Horizons** (`1K5M5qAqOLtO9WB4VYfgGT`)
  - `tracks_total` reported by Spotify: **67**
  - Track IDs returned by `spotify.get_playlist`: **64**
  - The returned `tracks` list contained duplicates (same track appearing more than once), e.g. repeated entries of:
    - “Last Ride of the Day” (Nightwish) appeared twice
    - “Heroes of the Dawn” (Visions of Atlantis) appeared twice
  - After extracting unique `track_ids`, only 64 unique IDs remained, so memory stored **64**.

- **Neon Valkyries: Pop × Symphonic Metal (Arc Mix)** (`1hVCTp5AUcvGlXJpj4mIPZ`)
  - `tracks_total`: **63**
  - Track IDs returned: **62**
  - Likely one track is missing from the embed payload or is unavailable (market/removed) and therefore not included.

- Other playlists (e.g., **Steel, Spark and Benediction** `78wBK763ZfdDSN61Gh5YRD`)
  - Matched `tracks_total` exactly (**57**), showing the issue is intermittent.

The tool responses include `tracks_source: "embed"`, suggesting the current implementation is based on an “embed” view rather than the canonical Spotify playlist-items API.

## Impact
- Backfilled playlists in MCP memory may be **incomplete** (missing tracks) or **non-identical** to the Spotify playlist.
- Any downstream analysis (taste inference from playlist corpus, similarity, “what changed”) becomes less reliable.
- Troubleshooting is difficult because the mismatch is silent unless we compare counts.

## Root Cause Hypotheses
1) **Embed-based retrieval is not canonical** and may omit items or behave differently than Spotify’s playlist-items endpoint.
2) **Pagination not guaranteed**: the embed payload may not always include all tracks for larger playlists.
3) **Market/unavailability**: some tracks may be unavailable for the authenticated market and omitted.
4) **Duplicates**: embed payload can contain duplicates; the `tracks_total` might count duplicates, while our backfill expects an ordered list exactly as Spotify shows it.

## Desired / Expected Behavior
For any playlist:
- We can retrieve the **full ordered list of playlist items** (track IDs) such that:
  - The number of items returned equals Spotify’s canonical playlist item count (or we can clearly explain why not).
  - The order matches Spotify’s order.
  - Duplicates are preserved if the playlist truly contains duplicates.
  - Missing/unavailable items are represented explicitly (so we can still preserve positional integrity).

## Proposed Fix (Preferred)
### Implement canonical playlist-items retrieval (API-based) with pagination
Add (or modify) a tool that reads from Spotify’s playlist-items endpoint (not embed). Example:

#### Option A: Fix/extend `spotify.get_playlist`
Add parameters:
- `include_tracks: boolean` (default true)
- `tracks_mode: "api" | "embed"` (default **"api"**)
- `limit` (<= 100) and pagination handled internally
- `market` support if applicable

Return:
- `tracks_total` (from Spotify)
- `tracks` as an ordered list of items:
  - `track_id` (nullable if missing/unavailable)
  - `name` (optional)
  - `artists` (optional)
  - `added_at` (optional)
  - `is_local` / `is_playable` (optional)
  - `reason_unavailable` (optional)
- `next_offset` / `has_more` (optional; can be internal-only)

#### Option B: Add dedicated tool `spotify.get_playlist_tracks`
Inputs:
- `playlist_id: string`
- `limit: int` (<=100)
- `offset: int`
- optional `market: string`
Outputs:
- `items: [{ track_id, name?, artists?, added_at?, is_playable?, is_local? }]`
- `total: int`
- `next_offset: int | null`

This supports robust pagination and ensures fidelity.

## Recommended Backfill Logic Update (Assistant-side)
Once canonical items are available:
- Backfill should store **the ordered list** exactly as returned.
- Do not de-duplicate automatically.
- If `track_id` is null/unavailable, store a placeholder entry in memory to preserve ordering (optional) or store `unavailable_count` alongside.

## Acceptance Criteria / Tests
1) For a playlist with no duplicates and all items playable:
   - `len(tracks)` equals `tracks_total`.
2) For a playlist with intentional duplicates:
   - duplicates appear in returned order; counts match.
3) For a playlist containing unavailable tracks:
   - the response includes placeholder items (or explicit missing entries) and reports availability reasons.
4) For large playlists (e.g., 180 tracks):
   - all items can be retrieved across pages and returned as a complete list.
5) Backfill into MCP memory:
   - `memory.log_playlist_create` stores the same count/order as Spotify canonical items.

## Notes
- This is not a memory-system bug. Memory tools are working; the fidelity issue is in Spotify playlist-item retrieval.
- If OAuth scopes or API rate limits are involved, include those in error reporting and logs.
