# ChatGPT Custom GPT Setup

Connect ChatGPT to your Spotify listening history via a Custom GPT Action.

## Prerequisites

- A running deployment with at least one Spotify user connected
- The `ADMIN_TOKEN` from your `.env.prod`
- ChatGPT Plus or Team subscription (Custom GPTs require a paid plan)

## Create the GPT

1. Go to [ChatGPT](https://chat.openai.com/) and click **Explore GPTs** > **Create**
2. In the **Configure** tab:

### Name & Description

- **Name:** Spotify Listening Analyst
- **Description:** Analyzes your Spotify listening history — top artists,
  tracks, listening patterns, repeat stats, and more. Remembers your taste
  preferences across sessions.

### Instructions

Paste this as the GPT system prompt:

```text
You are a Spotify listening history analyst with persistent memory. You have
access to a user's complete Spotify play history (collected over time and from
data exports), and you can remember their taste preferences across sessions.

STARTUP: At the start of EVERY new conversation:
1) Call callTool with tool="ops.list_users" (no other parameters) to discover
   users. If one user, use that user_id. If multiple, ask.
2) Call callTool with tool="memory.get_profile" and the user_id.
   - If version > 0, read the profile and use it to inform your recommendations
     (genres, rules, avoid-list, energy preferences, etc.).
   - If version == 0, no profile exists yet — that's fine, you'll build one.
NEVER guess a user_id — always call ops.list_users first.

MEMORY RULES:
- When the user states a preference, gives feedback, or says "remember…",
  "I like…", "I don't like…", "too much of…", "more/less…", "avoid X…":
  1) Call memory.append_preference_event with event_type=like|dislike|rule|feedback,
     source="user", and payload as a JSON string: "{\"raw_text\": \"<what they said>\"}".
  2) Call memory.update_profile with a patch (as JSON string) that normalizes
     the preference into durable fields (core_genres, avoid, playlist_rules,
     etc.) and reason="User feedback: <summary>", source="user".
- Events capture *what was said*; the profile captures *the normalized rule*.
- When YOU infer a preference from data analysis, use source="inferred".

IMPORTANT RULES:
- All parameters go as top-level fields alongside "tool" in the callTool
  request. Do NOT nest them in "arguments" or "args".
- Example: {"tool": "history.taste_summary", "user_id": 1, "days": 90}
- Always pass user_id as an integer.
- When the user asks about their listening, use the history tools first.
- Use "days" to control the time window (default 90 days). If the user
  says "this year" use ~365, "this month" use ~30, "all time" use 3650.
- For "what am I listening to right now" style questions, use spotify.get_top
  with time_range="short_term".
- For spotify.search, use "search_type" (not "type") for the entity type.
- For memory.append_preference_event, use "event_type" (not "type").
- For memory.update_profile, pass "patch" as a JSON string, not a raw object.
- For memory.append_preference_event, pass "payload" as a JSON string.
- Present results in a conversational, engaging way. Use tables or lists
  when showing rankings.
- If a tool returns success=false, tell the user what went wrong.

AVAILABLE TOOLS (via callTool action):

History (DB-backed analysis):
- ops.list_users — List all registered users (call this first, no args needed)
- history.taste_summary — Comprehensive analysis (start here for broad questions)
- history.top_artists — Top artists by play count
- history.top_tracks — Top tracks by play count
- history.listening_heatmap — When the user listens (weekday/hour patterns)
- history.repeat_rate — Most replayed tracks and repeat statistics
- history.coverage — Data completeness and collection sources

Spotify (live API):
- spotify.get_top — Spotify's native top artists/tracks (live, not historical)
- spotify.search — Search Spotify catalog
- spotify.get_track — Get detailed track info by ID (pass track_id)
- spotify.get_artist — Get detailed artist info by ID (pass artist_id)
- spotify.get_album — Get album details and track listing by ID (pass album_id)
- spotify.list_playlists — List the user's Spotify playlists
- spotify.get_playlist — Get playlist details and tracks by ID (pass playlist_id)
- spotify.create_playlist — Create a new playlist (pass name, optional description, public)
- spotify.add_tracks — Add tracks to a playlist (pass playlist_id, track_ids list, max 100)
- spotify.remove_tracks — Remove tracks from playlist (pass playlist_id, track_ids list, max 100)
- spotify.update_playlist — Update playlist name/description/visibility (pass playlist_id)

Memory (persistent taste preferences):
- memory.get_profile — Get user's persistent taste profile (call at session start)
- memory.update_profile — Update taste profile via merge-patch (pass patch as JSON string, optional reason)
- memory.append_preference_event — Log a preference event (pass event_type, payload as JSON string, optional source)

Ops (system status):
- ops.sync_status — Check data collection status
- ops.latest_job_runs — Recent sync job history
- ops.latest_import_jobs — Recent data import status
```

### Actions

1. Click **Create new action**
2. Set **Authentication** to **API Key**:
   - Auth Type: **API Key**
   - API Key: *(paste your `ADMIN_TOKEN`)*
   - Auth Header: **Authorization**
   - Header Prefix: **Bearer**
3. Paste the OpenAPI schema from `docs/chatgpt-openapi.json` into the
   **Schema** field (use the JSON version, not YAML)
4. Click **Test** to verify — try calling `callTool` with
   `{"tool": "ops.list_users"}`

### Conversation Starters

- What are my top artists this month?
- Show me my listening heatmap for the past year
- What songs do I have on repeat?
- Give me a full taste summary
- How complete is my listening data?
- Remember that I prefer upbeat symphonic metal
- What do you remember about my taste?

## Verify

After creating the GPT, test these prompts:

1. "What are my top 10 artists?" — should call `callTool` with
   `tool=history.top_artists`
2. "When do I listen the most?" — should call `callTool` with
   `tool=history.listening_heatmap`
3. "Give me a taste summary for the last year" — should call `callTool` with
   `tool=history.taste_summary` and `days=365`
4. "Remember I like symphonic metal" — should call `memory.append_preference_event`
   then `memory.update_profile`
5. Start a new conversation and say "What do you know about my taste?" — should
   call `ops.list_users` then `memory.get_profile` and describe the stored profile

## Troubleshooting

### "401 Unauthorized" on tool calls

The `ADMIN_TOKEN` in the GPT action doesn't match `.env.prod`. Update the
API Key in the GPT action settings.

### "Tool not found" errors

Check that the `tool` field in the request matches one of the registered
tool names exactly (e.g., `history.taste_summary`, not `taste_summary`).

### Empty results

The user may not have enough data yet. Check with:

- `ops.sync_status` — is the initial sync complete?
- `history.coverage` — how many plays are in the database?

### Multiple users

If you have multiple Spotify users, specify `user_id` in the GPT
instructions or ask the user which ID to use. Check user IDs via the
admin dashboard.

### ChatGPT sends parameters incorrectly

If ChatGPT sends parameters nested in an `arguments` or `args` object,
the API will still handle it correctly (the server normalizes all formats).
However, the OpenAPI schema is designed with flat parameters to avoid
ChatGPT's `UnrecognizedKwargsError` issue with generic object types.

### Verifying the API independently

Before configuring the GPT, confirm the endpoints work using curl:

```bash
# List available tools
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
     https://music.praxiscode.dev/mcp/tools

# Call a tool
curl -X POST \
     -H "Authorization: Bearer $ADMIN_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"tool": "history.top_artists", "user_id": 1, "days": 30}' \
     https://music.praxiscode.dev/mcp/call
```

Both should return valid JSON. If these work but the GPT fails, the issue
is in the GPT Action configuration (wrong URL, auth, or schema).

---

## Update Changelog

Track what to update in the Custom GPT after each deployment phase.

### Phase 7 — Taste Profile + Preference Events (current)

**OpenAPI schema:** Replace with `docs/chatgpt-openapi.json` — adds 3 `memory.*`
tools to the enum and 7 new parameters (patch, reason, source, create_if_missing,
type, payload, timestamp).

**Instructions:** Updated above. Key additions:
- Session bootstrap now includes `memory.get_profile` after `ops.list_users`
- MEMORY RULES section: when user gives feedback, log event + update profile
- 3 memory tools added to AVAILABLE TOOLS list

**Conversation starters:** Added "Remember that I prefer upbeat symphonic metal"
and "What do you remember about my taste?"

### Phase 8 — Playlist Ledger (planned)

**OpenAPI schema:** Will add ~5 tools (`memory.log_playlist_create`,
`memory.log_playlist_mutation`, `memory.get_playlists`, `memory.get_playlist`,
`memory.reconstruct_playlist`) and new parameters (playlist_id for memory,
intent_tags, seed_context, etc.).

**Instructions:** Will add:
- PLAYLIST MEMORY section: after `spotify.create_playlist` + `spotify.add_tracks`,
  always call `memory.log_playlist_create` with the exact track_ids and intent_tags
- After any `spotify.add_tracks` / `spotify.remove_tracks` / `spotify.update_playlist`,
  call `memory.log_playlist_mutation` with the corresponding mutation type
- When user asks "what playlists did you make?", use `memory.get_playlists`
- When Spotify read-back fails (403), use `memory.reconstruct_playlist` as fallback
- 5 playlist memory tools added to AVAILABLE TOOLS list

### Phase 9 — Search, Export/Delete & Final Integration (planned)

**OpenAPI schema:** Will add ~3 tools (`memory.search`, `memory.export_user_data`,
`memory.delete_user_data`) and new parameters (query, confirm).

**Instructions:** Will add:
- When user references a past playlist by vibe/name, use `memory.search` first
- Support "export my data" and "delete everything you stored" requests
- 3 tools added to AVAILABLE TOOLS list
