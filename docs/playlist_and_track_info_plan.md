# Plan: Spotify Playlist Management & Track Info MCP Tools

## Context

ChatGPT can currently only *read* listening history and search Spotify. The user wants ChatGPT to also:
- Get detailed info about tracks, artists, and albums
- Create, modify, and delete playlists

This requires extending the SpotifyClient (currently GET-only) to support POST/PUT/DELETE, adding Pydantic models for playlist/album responses, adding 9 new MCP tools, updating OAuth scopes, and updating the ChatGPT OpenAPI schema.

**Existing users must re-authorize** via `/auth/login` to grant new playlist scopes. Write tools will return a clear error if scopes are missing.

## New MCP Tools (9 total)

| Tool | Method | Description |
|------|--------|-------------|
| `spotify.get_track` | GET | Track details (artists, album, duration, popularity) |
| `spotify.get_artist` | GET | Artist details (genres, popularity, followers) |
| `spotify.get_album` | GET | Album details with track listing |
| `spotify.list_playlists` | GET | User's playlists (name, id, track count) |
| `spotify.get_playlist` | GET | Playlist details with tracks |
| `spotify.create_playlist` | POST | Create new playlist |
| `spotify.add_tracks` | POST | Add tracks to a playlist (by track IDs) |
| `spotify.remove_tracks` | DELETE | Remove tracks from a playlist |
| `spotify.update_playlist` | PUT | Update playlist name/description/visibility |

---

## Phase A — PR #1: SpotifyClient Foundation + Models

Extend the shared Spotify client to support POST/PUT/DELETE and add all new Pydantic models. No new MCP tools yet — just the building blocks.

### Files to modify:

**`services/shared/src/shared/spotify/constants.py`** — Add URL constants:
- `ALBUMS_URL = f"{SPOTIFY_API_BASE}/albums"`
- `USER_PLAYLISTS_URL = f"{SPOTIFY_API_BASE}/me/playlists"`
- `PLAYLIST_URL = f"{SPOTIFY_API_BASE}/playlists"`

**`services/shared/src/shared/spotify/models.py`** — Add ~10 Pydantic models:
- `SpotifyTrackSimplified` — track without album field (for album track listings)
- `SpotifyAlbumTracksPage` — paging object for album tracks
- `SpotifyAlbumFull(SpotifyAlbumSimplified)` — full album with tracks, genres, popularity, label
- `SpotifyPlaylistOwner` — owner object (id, display_name)
- `SpotifyPlaylistTrackItem` — playlist track entry (track + added_at)
- `SpotifyPlaylistTracks` — paging object for playlist tracks
- `SpotifyPlaylist` — full playlist (name, description, public, owner, tracks)
- `SpotifyPlaylistSimplified` — simplified playlist for list endpoints
- `UserPlaylistsResponse` — paginated response from `GET /me/playlists`
- `SpotifySnapshotResponse` — response from add/remove tracks (`snapshot_id`)

**`services/shared/src/shared/spotify/client.py`** — Extend client:
- Add `json_body: dict[str, Any] | None = None` param to `_request()`, pass as `json=json_body` to `httpx.request()`
- Add 9 new public methods: `get_track`, `get_artist`, `get_album`, `get_user_playlists`, `get_playlist`, `create_playlist`, `add_tracks_to_playlist`, `remove_tracks_from_playlist`, `update_playlist_details`

### Tests:
- **`services/api/tests/test_spotify/test_client.py`** (extend) — ~10 tests using `respx` mocks for each new client method

### Verification:
- `make lint` + `make typecheck` pass
- `pytest services/api/tests/test_spotify/` passes

---

## Phase B — PR #2: Read-Only MCP Tools (info + playlist read)

Add 5 read-only MCP tools that use the new client methods. Update OAuth scopes.

### Files to modify:

**`services/api/src/app/constants.py`** — Add `playlist-read-private` to OAuth scopes:
```python
SPOTIFY_SCOPES = (
    "user-read-recently-played user-top-read user-read-email user-read-private "
    "playlist-read-private"
)
```

**`services/api/src/app/mcp/tools/spotify_tools.py`** — Add 3 info tools to existing `SpotifyToolHandlers`:
- `spotify.get_track(user_id, track_id)` — returns curated dict (id, name, artists, album, duration, popularity)
- `spotify.get_artist(user_id, artist_id)` — returns curated dict (id, name, genres, popularity, followers)
- `spotify.get_album(user_id, album_id)` — returns curated dict (id, name, tracks listing, artists, release_date)

**`services/api/src/app/mcp/tools/playlist_tools.py`** — New file with `PlaylistToolHandlers`:
- `spotify.list_playlists(user_id, limit)` — list user's playlists
- `spotify.get_playlist(user_id, playlist_id)` — get playlist details with tracks
- Own `_get_client()` helper (same pattern as `SpotifyToolHandlers`)

**`services/api/src/app/mcp/tools/__init__.py`** — Add `import app.mcp.tools.playlist_tools`

**`docs/chatgpt-openapi.json` + `docs/chatgpt-openapi.yaml`** — Add 5 read tool names + new params (`track_id`, `artist_id`, `album_id`, `playlist_id`)

**`docs/chatgpt-gpt-setup.md`** — Add new tools to GPT instructions

**`CLAUDE.md`** — Update MCP tools list

### Tests:
- **`services/api/tests/test_mcp/test_router.py`** — update expected tool count
- **`services/api/tests/test_mcp/test_playlist_tools.py`** (new) — ~6 tests for read tools via `/mcp/call`

### Verification:
- `make lint` + `make typecheck` pass
- `pytest services/api/tests/` passes
- Deploy, test via curl: `spotify.get_track`, `spotify.list_playlists`, `spotify.get_playlist`

---

## Phase C — PR #3: Playlist Write Tools

Add 4 mutating MCP tools with scope validation.

### Files to modify:

**`services/api/src/app/constants.py`** — Add write scopes:
```python
SPOTIFY_SCOPES = (
    "user-read-recently-played user-top-read user-read-email user-read-private "
    "playlist-read-private playlist-modify-public playlist-modify-private"
)
```

**`services/api/src/app/mcp/tools/playlist_tools.py`** — Add to `PlaylistToolHandlers`:
- `_check_scopes(user_id, session, required_scopes)` — queries `SpotifyToken.scope`, returns error message if missing
- `spotify.create_playlist(user_id, name, description?, public?)` — POST /me/playlists
- `spotify.add_tracks(user_id, playlist_id, track_ids)` — converts IDs to `spotify:track:{id}` URIs, caps at 100
- `spotify.remove_tracks(user_id, playlist_id, track_ids)` — DELETE with URIs, caps at 100
- `spotify.update_playlist(user_id, playlist_id, name?, description?, public?)` — PUT details

All write handlers call `_check_scopes()` first and return clear "re-authorize via /auth/login" error if missing.

**`docs/chatgpt-openapi.json` + `docs/chatgpt-openapi.yaml`** — Add 4 write tool names + params (`name`, `description`, `public`, `track_ids`)

**`docs/chatgpt-gpt-setup.md`** — Add write tools + examples

**`CLAUDE.md`** — Update MCP tools list

### Tests:
- **`services/api/tests/test_mcp/test_playlist_tools.py`** (extend) — ~8 tests: write tools via `/mcp/call`, scope validation failures, track count limits, empty list errors

### Verification:
- `make lint` + `make typecheck` pass
- `pytest services/api/tests/` passes
- Deploy, re-authorize user via `/auth/login`
- Test full flow via curl: create playlist → add tracks → remove tracks → update → verify in Spotify app
- Update ChatGPT Custom GPT action with final OpenAPI schema
- Test in ChatGPT: "Create a playlist of my top 10 tracks from the last month"

---

## Key Design Decisions

1. **`_request()` extension**: Add optional `json_body` param (not breaking — existing callers unaffected)
2. **`create_playlist` uses `POST /me/playlists`** (not the deprecated `/users/{id}/playlists`)
3. **Track ID → URI conversion**: Tool handlers convert `track_ids` to `spotify:track:{id}` URIs so ChatGPT only needs to pass IDs
4. **Scope validation on writes only**: Read tools work without extra scopes (public playlists always visible). Write tools check `SpotifyToken.scope` and return MCP error if missing
5. **Info tools in `spotify_tools.py`**, playlist tools in new `playlist_tools.py`**: separates read-only info lookups from playlist CRUD
6. **Curated MCP responses**: Return focused dicts, not raw Spotify API responses, to keep outputs concise for ChatGPT
