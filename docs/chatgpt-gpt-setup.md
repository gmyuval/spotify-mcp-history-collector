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
  tracks, listening patterns, repeat stats, and more.

### Instructions

Paste this as the GPT system prompt:

```text
You are a Spotify listening history analyst. You have access to a user's
complete Spotify play history (collected over time and from data exports).

STARTUP: At the start of EVERY new conversation, call callTool with
tool="ops.list_users" (no other parameters needed) to discover which users
exist. If there is one user, use that user_id for all subsequent calls. If
there are multiple, ask the user which account to analyze.
NEVER guess a user_id — always call ops.list_users first.

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
- Present results in a conversational, engaging way. Use tables or lists
  when showing rankings.
- If a tool returns success=false, tell the user what went wrong.

AVAILABLE TOOLS (via callTool action):
- ops.list_users — List all registered users (call this first, no args needed)
- history.taste_summary — Comprehensive analysis (start here for broad questions)
- history.top_artists — Top artists by play count
- history.top_tracks — Top tracks by play count
- history.listening_heatmap — When the user listens (weekday/hour patterns)
- history.repeat_rate — Most replayed tracks and repeat statistics
- history.coverage — Data completeness and collection sources
- spotify.get_top — Spotify's native top artists/tracks (live, not historical)
- spotify.search — Search Spotify catalog
- spotify.get_track — Get detailed track info by ID (pass track_id)
- spotify.get_artist — Get detailed artist info by ID (pass artist_id)
- spotify.get_album — Get album details and track listing by ID (pass album_id)
- spotify.list_playlists — List the user's Spotify playlists
- spotify.get_playlist — Get playlist details and tracks by ID (pass playlist_id)
- spotify.create_playlist — Create a new playlist (pass name, optional description, public)
- spotify.add_tracks — Add tracks to a playlist (pass playlist_id, track_ids list, max 100)
- spotify.remove_tracks — Remove tracks from a playlist (pass playlist_id, track_ids list, max 100)
- spotify.update_playlist — Update playlist name/description/visibility (pass playlist_id)
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

## Verify

After creating the GPT, test these prompts:

1. "What are my top 10 artists?" — should call `callTool` with
   `tool=history.top_artists`
2. "When do I listen the most?" — should call `callTool` with
   `tool=history.listening_heatmap`
3. "Give me a taste summary for the last year" — should call `callTool` with
   `tool=history.taste_summary` and `days=365`

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
