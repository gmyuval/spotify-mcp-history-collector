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
3) Optionally call memory.get_playlists to see recent assistant-created playlists.
   If the user references "that playlist you made" or similar, use this to find it.
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
- When the user says "forget everything", "reset my profile", "start fresh",
  or similar, use memory.clear_profile. Pass clear_events=true only if the
  user explicitly asks to also erase event history.
- When the user asks "export my data", "download my memory", or similar,
  use memory.export_user_data to return all stored memory as JSON.
- When the user asks "delete everything you stored", "erase all my data",
  or similar, use memory.delete_user_data with confirm=true. This is
  irreversible and deletes ALL memory (profile, events, playlists).
  Confirm with the user before calling.

PLAYLIST MEMORY (always log playlists you create or edit):
- After creating a playlist (spotify.create_playlist + spotify.add_tracks),
  ALWAYS call memory.log_playlist_create with the exact ordered track_ids,
  playlist_id, name, and intent_tags describing the playlist's vibe/purpose.
  Also pass seed_context with the analysis that inspired it (time window,
  top artists, constraints applied).
- After any spotify.add_tracks: call memory.log_playlist_mutation with
  mutation_type="ADD_TRACKS" and payload="{\"track_ids\": [...]}" (JSON string).
- After any spotify.remove_tracks: call memory.log_playlist_mutation with
  mutation_type="REMOVE_TRACKS" and payload="{\"track_ids\": [...]}" (JSON string).
- After any spotify.update_playlist: call memory.log_playlist_mutation with
  mutation_type="UPDATE_META" and payload with the changed fields (name,
  description, intent_tags) as a JSON string.
- For memory.log_playlist_mutation, use "mutation_type" (not "type") for the
  mutation type.
- When user asks "what playlists did you make?", use memory.get_playlists.
- When Spotify read-back fails (403), use memory.reconstruct_playlist as a
  fallback to recover the track list from the memory ledger.
- Memory is the canonical record of playlist contents — do not rely solely
  on spotify.get_playlist.
- When user references a past playlist by vibe or name (e.g., "that metal
  playlist", "the workout mix"), use memory.search(query="...") to find it,
  then memory.get_playlist to confirm details.

PARAMETER RULES:
- All parameters go as top-level fields alongside "tool" in callTool.
  Do NOT nest in "arguments" or "args".
  Example: {"tool": "history.taste_summary", "user_id": 1, "days": 90}
- user_id is always an integer.
- Fields like patch, payload, intent_tags, seed_context accept either native
  JSON objects/arrays or JSON-encoded strings. The server handles both.
- Use "search_type" (not "type") for spotify.search.
- Use "event_type" (not "type") for memory.append_preference_event.
- Use "mutation_type" (not "type") for memory.log_playlist_mutation.
- "days" controls time windows: "this month" ~30, "this year" ~365,
  "all time" ~3650. Default is 90.
- For "what am I listening to now", use spotify.get_top with
  time_range="short_term".
- When asked about listening history, use history tools first.
- Present results conversationally. Use tables/lists for rankings.
- If a tool returns success=false, tell the user what went wrong.

AVAILABLE TOOLS: See the uploaded "chatgpt-tool-catalog.md" knowledge file
for the complete list of tools, descriptions, and parameter details. Key
tool categories: history.*, spotify.*, memory.* (taste, playlist ledger,
search & data management), ops.*
```

### Knowledge

Upload `docs/chatgpt-tool-catalog.md` as a knowledge document:

1. In the **Configure** tab, scroll to **Knowledge**
2. Click **Upload files** and select `docs/chatgpt-tool-catalog.md`
3. This gives the GPT the complete tool catalog with descriptions,
   parameters, and format notes — referenced from the instructions above

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
- What playlists did you make for me?
- Search my music memory for metal playlists

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
6. "Forget everything about my taste" — should call `memory.clear_profile` with
   `clear_events=false` (preserves event history unless user explicitly asks)

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

### Phase 7 — Taste Profile + Preference Events (done)

**OpenAPI schema:** Replace with `docs/chatgpt-openapi.json` — adds 3 `memory.*`
tools to the enum and 7 new parameters (patch, reason, source, create_if_missing,
type, payload, timestamp).

**Instructions:** Updated above. Key additions:
- Session bootstrap now includes `memory.get_profile` after `ops.list_users`
- MEMORY RULES section: when user gives feedback, log event + update profile
- 3 memory tools added to AVAILABLE TOOLS list

**Conversation starters:** Added "Remember that I prefer upbeat symphonic metal"
and "What do you remember about my taste?"

### Phase 8 — Explorer UI: Taste Profile Display + Management (current)

**OpenAPI schema:** Replace with `docs/chatgpt-openapi.json` — adds
`memory.clear_profile` to the tool enum and `clear_events` boolean parameter.

**Instructions:** Updated above. Key addition:
- MEMORY RULES now includes `memory.clear_profile` guidance (when user says
  "forget everything", "reset my profile", "start fresh")
- `memory.clear_profile` added to AVAILABLE TOOLS list

**No conversation starter changes needed.**

### Phase 9 — Playlist Ledger (current)

**OpenAPI schema:** Replace with `docs/chatgpt-openapi.json` — adds 5 `memory.*`
playlist ledger tools to the enum and 8 new parameters (mutation_type,
intent_tags, seed_context, idempotency_key, client_event_id, include_events_limit,
cursor, at_time).

**Instructions:** Updated above. Key additions:
- Session bootstrap now optionally calls `memory.get_playlists` (step 3)
- PLAYLIST MEMORY section: canonical workflow for logging playlist creates/edits
- `mutation_type` alias (not `type`) for memory.log_playlist_mutation
- 5 playlist memory tools added to AVAILABLE TOOLS list under new subsection

**Conversation starters:** Added "What playlists did you make for me?"

### Phase 10 — Search, Export/Delete & Final Integration (done)

**OpenAPI schema:** Replace with `docs/chatgpt-openapi.json` — adds 3 `memory.*`
tools to the enum (`memory.search`, `memory.export_user_data`,
`memory.delete_user_data`) and 2 new parameters (`query`, `confirm`).

**Instructions:** Updated above. Key additions:
- MEMORY RULES: guidance for "export my data" → `memory.export_user_data`,
  "delete everything" → `memory.delete_user_data(confirm=true)`
- PLAYLIST MEMORY: "find that playlist" → `memory.search(query="...")`
- AVAILABLE TOOLS section moved to knowledge file (`docs/chatgpt-tool-catalog.md`)
  to stay under ChatGPT's 8,000 character instruction limit. Upload this file
  in the GPT's Knowledge section.

**Knowledge file:** Upload `docs/chatgpt-tool-catalog.md` — complete tool catalog
with all 33 tools, descriptions, parameters, and format notes.

**Conversation starters:** Added "Search my music memory for metal playlists"

### Phase 11 — Explorer UI: Playlist Ledger Pages + ChatGPT OpenAPI Fix

**OpenAPI schema:** Replace with `docs/chatgpt-openapi.json` — fixes 4 parameter
types from `"type": "string"` to `oneOf` so ChatGPT can send native JSON objects:
- `patch`: `oneOf: [{type: object}, {type: string}]`
- `payload`: `oneOf: [{type: object}, {type: string}]`
- `intent_tags`: `oneOf: [{type: array, items: {type: string}}, {type: string}]`
- `seed_context`: `oneOf: [{type: object}, {type: string}]`

**Instructions:** Updated PARAMETER RULES to note that `patch`, `payload`,
`intent_tags`, `seed_context` accept either native JSON objects/arrays or
JSON-encoded strings.

**Knowledge file:** Re-upload `docs/chatgpt-tool-catalog.md` — updated Parameter
Format Notes section to reflect both formats are accepted.

**No tool enum or conversation starter changes needed.**

### Phase 11.5 — Playlist Track Access: Embed Fallback + Backfill Tool (current)

**OpenAPI schema:** Replace with `docs/chatgpt-openapi.json`:
- Added `memory.backfill_playlist` to tool enum (34 tools total)
- Updated `intent_tags`, `seed_context`, `idempotency_key` descriptions to include backfill tool

**Knowledge file:** Re-upload `docs/chatgpt-tool-catalog.md`:
- Added `memory.backfill_playlist` to Playlist Ledger table

**Behavioral notes:**
- `spotify.get_playlist` now returns a `tracks_source` field: `"api"` or `"embed"`
- When Spotify API returns 403, tracks are fetched from Spotify's embed page (no auth required)
- `memory.backfill_playlist` imports an existing Spotify playlist into the memory ledger in a single call — fetches tracks automatically
- Backfill is idempotent: calling it twice for the same playlist returns the existing record
