# ChatGPT Integration Guide

## Overview

The Spotify MCP History Collector API exposes two endpoints that enable ChatGPT Custom GPTs to analyze Spotify listening history:

- **GET /mcp/tools** -- Returns the tool catalog (list of available tools with their parameters and descriptions)
- **POST /mcp/call** -- Invokes a tool by name with arguments and returns the result

ChatGPT Custom GPT Actions can call these endpoints directly, giving a GPT the ability to query collected listening data, access live Spotify data, and check system status -- all through natural conversation.

## Prerequisites

- The system is deployed and accessible via HTTPS (Custom GPTs require HTTPS endpoints)
- At least one Spotify user has completed the OAuth authorization flow (`/auth/login`)
- `ADMIN_TOKEN` is configured in the API environment (this token authenticates GPT requests)

## Step 1: Create a Custom GPT

1. Go to [https://chat.openai.com](https://chat.openai.com) and navigate to **Explore GPTs** then **Create**
2. Name it something like "Spotify History Analyzer"
3. In the **Instructions** field, provide a system prompt that guides the GPT on how to use the tools

### Suggested GPT Instructions

```text
You are a Spotify music analyst. You have access to a user's Spotify listening history through a set of tools. When the user asks about their music taste, listening habits, or wants recommendations based on their history, use the available tools to fetch data and provide insightful analysis.

Available tools are in the "history", "spotify", and "ops" categories. Use history tools for analyzing collected listening data, spotify tools for live Spotify data, and ops tools for checking system status.

The default user_id is 1 (adjust if multiple users). Default to 90 days for history queries unless the user specifies otherwise.

Always present data in a readable format with highlights and insights, not just raw numbers.
```

## Step 2: Configure the GPT Action

In the GPT editor, click **Create new action** to add the API connection.

### Authentication

Configure authentication as follows:

- **Authentication Type**: API Key
- **Auth Type**: Bearer
- **Header**: Authorization
- **API Key value**: Your `ADMIN_TOKEN` value from the API environment configuration

The GPT will send requests with the header `Authorization: Bearer <your-token>`.

### OpenAPI Schema

Paste the following OpenAPI 3.1 schema into the action schema editor. Replace `https://your-domain.com` with the actual URL where your API is hosted.

```yaml
openapi: 3.1.0
info:
  title: Spotify MCP API
  version: 0.1.0
servers:
  - url: https://your-domain.com
paths:
  /mcp/tools:
    get:
      operationId: listTools
      summary: List available MCP tools
      responses:
        '200':
          description: Tool catalog
          content:
            application/json:
              schema:
                type: array
                items:
                  type: object
                  properties:
                    name:
                      type: string
                    description:
                      type: string
                    category:
                      type: string
                    parameters:
                      type: array
                      items:
                        type: object
                        properties:
                          name:
                            type: string
                          type:
                            type: string
                          description:
                            type: string
                          required:
                            type: boolean
                          default: {}
  /mcp/call:
    post:
      operationId: callTool
      summary: Invoke an MCP tool
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - tool
              properties:
                tool:
                  type: string
                  description: "Tool name (e.g., history.taste_summary)"
                args:
                  type: object
                  description: "Tool arguments as key-value pairs"
      responses:
        '200':
          description: Tool result
          content:
            application/json:
              schema:
                type: object
                properties:
                  tool:
                    type: string
                  success:
                    type: boolean
                  result: {}
                  error:
                    type: string
                    nullable: true
```

### Request Format

When the GPT calls a tool, it sends a POST request to `/mcp/call` with this JSON body:

```json
{
  "tool": "history.taste_summary",
  "args": {
    "days": 90,
    "user_id": 1
  }
}
```

The response contains the tool result:

```json
{
  "tool": "history.taste_summary",
  "success": true,
  "result": { ... },
  "error": null
}
```

If a tool call fails, `success` will be `false` and `error` will contain a description of the problem.

## Step 3: Available Tools Reference

### History Tools (DB-backed)

These tools query the locally collected listening history stored in the database.

| Tool | Description | Key Args |
|------|-------------|----------|
| `history.taste_summary` | Full listening analysis with genres, top items, and patterns | `days` (int), `user_id` (int) |
| `history.top_artists` | Top artists ranked by play count | `days` (int), `limit` (int), `user_id` (int) |
| `history.top_tracks` | Top tracks ranked by play count | `days` (int), `limit` (int), `user_id` (int) |
| `history.listening_heatmap` | Listening patterns by weekday and hour | `days` (int), `user_id` (int) |
| `history.repeat_rate` | Track repeat statistics and one-hit metrics | `days` (int), `user_id` (int) |
| `history.coverage` | Data completeness metrics (gaps, collection periods) | `days` (int), `user_id` (int) |

### Spotify Live Tools

These tools call the Spotify API directly for real-time data.

| Tool | Description | Key Args |
|------|-------------|----------|
| `spotify.get_top` | Spotify's native top items endpoint | `entity` (artists/tracks), `time_range` (short_term/medium_term/long_term), `limit` (int), `user_id` (int) |
| `spotify.search` | Search the Spotify catalog | `q` (string), `type` (track/artist/album), `limit` (int), `user_id` (int) |

### Ops Tools

These tools provide system and sync status information.

| Tool | Description | Key Args |
|------|-------------|----------|
| `ops.sync_status` | Current sync state for a user | `user_id` (int) |
| `ops.latest_job_runs` | Recent job execution history | `user_id` (int), `limit` (int) |
| `ops.latest_import_jobs` | Recent ZIP import history | `user_id` (int), `limit` (int) |

### Tool Argument Defaults

Most tools use sensible defaults when arguments are omitted:

- `days` defaults to 90
- `limit` defaults to 10 (where applicable)
- `user_id` defaults to 1
- `time_range` defaults to `medium_term` for `spotify.get_top`
- `type` defaults to `track` for `spotify.search`

You can confirm exact defaults by calling **GET /mcp/tools** to retrieve the full tool catalog with parameter metadata.

## Step 4: Test Your GPT

After saving your GPT configuration, test it with these example conversations:

1. **"What are my top 10 artists from the last 30 days?"** -- Uses `history.top_artists`
2. **"Show me my listening heatmap for the past month"** -- Uses `history.listening_heatmap`
3. **"Give me a full taste analysis of my listening over the last 90 days"** -- Uses `history.taste_summary`
4. **"What's my track repeat rate?"** -- Uses `history.repeat_rate`
5. **"How complete is my listening data?"** -- Uses `history.coverage`
6. **"What are my top tracks on Spotify right now?"** -- Uses `spotify.get_top` (live API)
7. **"Search for tracks by Radiohead"** -- Uses `spotify.search`
8. **"Is the collector running? What's the sync status?"** -- Uses `ops.sync_status`

## Troubleshooting

### Common Issues

**"Authentication failed"**
Verify that the `ADMIN_TOKEN` value in your API's environment matches exactly what you entered in the GPT Action authentication configuration. Check for leading/trailing whitespace.

**"Unknown tool"**
Check the tool name spelling. Tool names use dot notation with the category prefix (e.g., `history.taste_summary`, not just `taste_summary`). Use **GET /mcp/tools** to list all available tool names.

**"Empty results"**
No plays have been collected yet. The collector needs time to poll Spotify for recent plays, or you can upload a ZIP export through the admin frontend to backfill history immediately.

**CORS errors**
If you see CORS-related errors in the browser console, ensure `CORS_ALLOWED_ORIGINS` in the API configuration includes the ChatGPT domain. You can set it to `*` temporarily for testing, but restrict it in production.

**Connection refused or timeout**
Custom GPTs require the API to be accessible from the public internet over HTTPS. Verify that:
- The API is running and reachable at the configured URL
- TLS/SSL is properly configured (self-signed certificates will not work)
- Any firewall or reverse proxy is forwarding traffic to the API port

**Tool returns `success: false`**
Read the `error` field in the response for details. Common causes include:
- The specified `user_id` does not exist
- The user's Spotify token has expired and automatic refresh failed
- A database connection issue on the API side

### Verifying the API Independently

Before configuring the GPT, confirm the API endpoints work using curl:

```bash
# List available tools
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
     https://your-domain.com/mcp/tools

# Call a tool
curl -X POST \
     -H "Authorization: Bearer $ADMIN_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"tool": "history.top_artists", "args": {"days": 30, "user_id": 1}}' \
     https://your-domain.com/mcp/call
```

Both should return valid JSON responses. If these work but the GPT fails, the issue is likely in the GPT Action configuration (wrong URL, auth, or schema).
