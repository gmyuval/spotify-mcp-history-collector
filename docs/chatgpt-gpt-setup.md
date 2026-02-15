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

IMPORTANT RULES:
- The user_id is 1 (unless the user says otherwise).
- Always pass user_id as an integer in tool calls.
- When the user asks about their listening, use the history tools first.
- Use "days" to control the time window (default 90 days). If the user
  says "this year" use ~365, "this month" use ~30, "all time" use 3650.
- For "what am I listening to right now" style questions, use spotify.get_top
  with time_range="short_term".
- Present results in a conversational, engaging way. Use tables or lists
  when showing rankings.
- If a tool returns success=false, tell the user what went wrong.

AVAILABLE TOOLS (via callTool action):
- history.taste_summary — Comprehensive analysis (start here for broad questions)
- history.top_artists — Top artists by play count
- history.top_tracks — Top tracks by play count
- history.listening_heatmap — When the user listens (weekday/hour patterns)
- history.repeat_rate — Most replayed tracks and repeat statistics
- history.coverage — Data completeness and collection sources
- spotify.get_top — Spotify's native top artists/tracks (live, not historical)
- spotify.search — Search Spotify catalog
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
3. Paste the OpenAPI schema from `docs/chatgpt-openapi.yaml` into the
   **Schema** field
4. Click **Test** to verify — try calling `listTools`

### Conversation Starters

- What are my top artists this month?
- Show me my listening heatmap for the past year
- What songs do I have on repeat?
- Give me a full taste summary
- How complete is my listening data?

## Verify

After creating the GPT, test these prompts:

1. "What are my top 10 artists?" — should call `history.top_artists`
2. "When do I listen the most?" — should call `history.listening_heatmap`
3. "Give me a taste summary for the last year" — should call
   `history.taste_summary` with `days: 365`

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
