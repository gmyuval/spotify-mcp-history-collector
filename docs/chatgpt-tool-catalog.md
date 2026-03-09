# Tool Catalog — Spotify Listening Analyst

Complete reference for all available tools via the callTool action.
All tools require `user_id` (integer) unless noted otherwise.

## History (DB-backed analysis)

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `ops.list_users` | List all registered users. Call this first — no args needed. | *(none)* |
| `history.taste_summary` | Comprehensive listening analysis. Start here for broad questions. | `days` (default 90) |
| `history.top_artists` | Top artists by play count | `days`, `limit` |
| `history.top_tracks` | Top tracks by play count | `days`, `limit` |
| `history.listening_heatmap` | When the user listens (weekday/hour patterns) | `days` |
| `history.repeat_rate` | Most replayed tracks and repeat statistics | `days` |
| `history.coverage` | Data completeness and collection sources | `days` |

## Spotify (live API)

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `spotify.get_top` | Spotify's native top artists/tracks (live, not from DB history) | `entity` (artists/tracks), `time_range` (short_term/medium_term/long_term), `limit` |
| `spotify.search` | Search Spotify catalog | `q`, `search_type` (not "type"), `limit` |
| `spotify.get_track` | Detailed track info | `track_id` |
| `spotify.get_artist` | Detailed artist info | `artist_id` |
| `spotify.get_album` | Album details with track listing | `album_id` |
| `spotify.list_playlists` | List user's Spotify playlists | `limit` |
| `spotify.get_playlist` | Playlist details with tracks | `playlist_id` |
| `spotify.create_playlist` | Create a new playlist | `name`, optional `description`, `public` |
| `spotify.add_tracks` | Add tracks to playlist (max 100) | `playlist_id`, `track_ids` (list) |
| `spotify.remove_tracks` | Remove tracks from playlist (max 100) | `playlist_id`, `track_ids` (list) |
| `spotify.update_playlist` | Update playlist name/description/visibility | `playlist_id`, optional `name`, `description`, `public` |

## Memory — Taste Preferences

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `memory.get_profile` | Get user's persistent taste profile. Call at session start. | *(just user_id)* |
| `memory.update_profile` | Update taste profile via merge-patch | `patch` (JSON string), optional `reason`, `source` |
| `memory.append_preference_event` | Log a preference event | `event_type` (not "type": like/dislike/rule/feedback), `payload` (JSON string), optional `source` |
| `memory.clear_profile` | Clear/reset taste profile | optional `clear_events` (boolean) |

## Memory — Playlist Ledger

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `memory.log_playlist_create` | Log a newly created playlist | `playlist_id`, `name`, `track_ids`, optional `intent_tags` (JSON string), `seed_context` (JSON string — MUST include `origin.created_by`: `"assistant"` / `"user"` / `"spotify"` / `"import"` / `"other"`), `idempotency_key` |
| `memory.log_playlist_mutation` | Log a playlist edit | `playlist_id`, `mutation_type` (not "type": ADD_TRACKS/REMOVE_TRACKS/REORDER/UPDATE_META), `payload` (JSON string) |
| `memory.get_playlists` | List assistant-tracked playlists | optional `limit`, `cursor` |
| `memory.get_playlist` | Full playlist details with snapshot and events | `playlist_id`, optional `include_events_limit` |
| `memory.reconstruct_playlist` | Reconstruct playlist track list from memory | `playlist_id`, optional `at_time` (ISO datetime) |
| `memory.backfill_playlist` | Import an existing Spotify playlist into memory ledger. Pass `track_ids` + `name` to bypass Spotify fetch entirely (for private/restricted playlists). | `playlist_id`, optional `intent_tags` (JSON string), `seed_context` (JSON string — include `origin.created_by`: `"assistant"` / `"user"` / `"spotify"` / `"import"` / `"other"`), `idempotency_key`, `track_ids` (list of Spotify track IDs or full URIs — both `"4iV5W9uYEdYUVa79Axb7Rh"` and `"spotify:track:4iV5W9uYEdYUVa79Axb7Rh"` are accepted; skips Spotify fetch, requires `name`), `name` (playlist name — required when `track_ids` is supplied) |

## Memory — Search & Data Management

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `memory.search` | Search across all memory by keyword | `query`, optional `limit` |
| `memory.export_user_data` | Export all stored memory data as JSON | *(just user_id)* |
| `memory.delete_user_data` | Delete ALL stored memory data (irreversible) | `confirm` (must be true) |

## Ops (system status)

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `ops.sync_status` | Check data collection status | *(just user_id)* |
| `ops.latest_job_runs` | Recent sync job history | optional `limit` |
| `ops.latest_import_jobs` | Recent data import status | optional `limit` |

## Parameter Format Notes

- All parameters go as **top-level fields** alongside `"tool"` in the callTool request. Do NOT nest in `"arguments"` or `"args"`.
- Example: `{"tool": "history.taste_summary", "user_id": 1, "days": 90}`
- `user_id` is always an integer.
- `patch`, `payload`, and `seed_context` accept either native JSON objects or JSON-encoded strings.
- `intent_tags` accepts either a native JSON string array or a JSON-encoded string.
- Use `"search_type"` (not `"type"`) for spotify.search.
- Use `"event_type"` (not `"type"`) for memory.append_preference_event.
- Use `"mutation_type"` (not `"type"`) for memory.log_playlist_mutation.
- The `"days"` parameter controls time windows: "this month" ~30, "this year" ~365, "all time" ~3650.
