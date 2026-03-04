# Issue: Spotify playlist backfill — track retrieval blocked (RESOLVED)

## Status: RESOLVED (PR #37 + Phase 11.5)

**Root causes identified and fixed:**

1. **Stale cache bug** (PR #37): `list_playlists` cached `snapshot_id` without track rows; `get_playlist` served empty-tracks cache entries. Fixed by treating empty-tracks cache as a miss.
2. **Spotify 403 restriction** (PR #37): Spotify Development Mode blocks `GET /playlists/{id}` and `/tracks` (requires Extended Quota Mode). Fixed with graceful degradation — returns metadata + `tracks_restricted` flag.
3. **Embed fallback** (Phase 11.5): Spotify's embed page (`/embed/playlist/{id}`) returns complete track listings in `__NEXT_DATA__` JSON — no auth required. Used as automatic fallback when API returns 403.
4. **Backfill tool** (Phase 11.5): New `memory.backfill_playlist` MCP tool imports existing Spotify playlists into the memory ledger in a single call.

## Original Report (historical)

We could list playlists and fetch playlist metadata, but **could not retrieve the track contents** of a playlist via the Spotify MCP tools. This prevented backfilling playlists into the MCP memory store because memory logging requires a non-empty ordered list of `track_ids`.

### Previous symptoms
- `spotify.list_playlists` worked and returned playlist IDs + `tracks_total`.
- `spotify.get_playlist(playlist_id)` returned correct metadata but `tracks` was always an **empty array** (`tracks: []`).
- `memory.log_playlist_create` failed with **`track_ids must be a non-empty array`**.

### Previous impact
- Could not backfill existing Spotify playlists into MCP memory.
- Could not reconstruct or reason about historical playlists unless they were created by the assistant and logged at creation time.
- Taste profiling from the "playlist corpus" was blocked.

## Resolution Details

### Fix 1: Stale cache (PR #37)
The `list_playlists` tool caches playlist metadata (including `snapshot_id`) but not track data. When `get_playlist` found a matching `snapshot_id` in cache, it returned the cached entry with empty tracks instead of fetching them. Fix: cache entries with empty tracks are treated as misses.

### Fix 2: Spotify 403 graceful degradation (PR #37)
Spotify's Development Mode restricts `GET /playlists/{id}` and `GET /playlists/{id}/tracks` endpoints (requires Extended Quota Mode). The handler now catches 403 on both endpoints and returns cached metadata with a `tracks_restricted` flag and explanation.

### Fix 3: Embed fallback (Phase 11.5)
Spotify's embed endpoint (`https://open.spotify.com/embed/playlist/{id}`) returns complete track listings in its server-rendered `__NEXT_DATA__` JSON blob. No authentication required. The `get_playlist` tool automatically falls back to this when the API returns 403. Returns `tracks_source: "embed"` to indicate the data source.

### Fix 4: Backfill tool (Phase 11.5)
New `memory.backfill_playlist` MCP tool that fetches a playlist's tracks (via API or embed) and creates the memory ledger entry in a single call. Eliminates the previous 3-step manual workflow.
