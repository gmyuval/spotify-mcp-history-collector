# Issue: Spotify playlist backfill is blocked because playlist track lists are not retrievable

## Summary
We can list playlists and fetch playlist metadata, but **we cannot retrieve the track contents** of a playlist via the current Spotify MCP tools. This prevents us from backfilling playlists into the MCP memory store because memory logging requires a non-empty ordered list of `track_ids`.

## Evidence / Symptoms
- `spotify.list_playlists` works and returns playlist IDs + `tracks_total`.
- `spotify.get_playlist(playlist_id)` returns correct metadata:
  - `tracks_total` is correct
  - but `tracks` is always an **empty array** (`tracks: []`)
- When attempting to backfill a playlist into memory:
  - `memory.log_playlist_create` fails with: **`track_ids must be a non-empty array`**
  - because we currently cannot obtain any `track_ids` from Spotify for that playlist.

## Impact
- Cannot backfill existing Spotify playlists into MCP memory.
- Cannot reconstruct or reason about historical playlists unless they were created by the assistant and logged at creation time.
- Taste profiling from the “playlist corpus” is blocked (only possible from chat-created/logged playlists).

## Expected Behavior
Provide a way to return the **ordered Spotify track IDs** for a playlist, including pagination for large playlists.

## Proposed Fix (pick one)

### Option A (preferred): Fix/extend `spotify.get_playlist`
- Add a flag or default behavior to include playlist items:
  - return `tracks` as a list of items containing at least:
    - `track_id` (Spotify track ID)
    - (optional) track name, artist(s)
- Must support pagination (Spotify playlists can exceed 100 items).
- Ensure returned order matches Spotify order.

### Option B: Add a dedicated playlist-items tool
Implement a new tool:

#### `spotify.get_playlist_tracks`
- **Inputs:**
  - `playlist_id` (string)
  - `limit` (int, <= 100)
  - `offset` (int, >= 0)
- **Outputs:**
  - `track_ids` (array of strings)
  - `next_offset` (int | null)
- Optional: also return rich items:
  - `items: [{ track_id, name, artists, added_at }]`

## Acceptance Criteria
- For a playlist with `tracks_total > 0`, we can retrieve a non-empty set of `track_ids`.
- We can iterate through all pages and reconstruct the full ordered track list.
- After retrieving `track_ids`, calling `memory.log_playlist_create` succeeds for that playlist.
- Works for both:
  - small playlists (e.g., 10 tracks)
  - large playlists (e.g., 180 tracks like “Metal Classics”).

## Notes
- This is not a “memory” bug: memory endpoints are functioning.
- The blocker is the Spotify connector/tool not returning playlist items.
- If Spotify scopes are the cause, confirm required OAuth scopes for reading playlist items and ensure they are granted.
