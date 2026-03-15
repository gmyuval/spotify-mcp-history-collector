# Claude Integration Setup

Connect Claude Desktop or Claude Code to your Spotify listening data via MCP.

## Prerequisites

- A registered account on the Spotify MCP Explorer
- An API token (created via the Settings page)

## 1. Create an API Token

1. Open the Explorer UI and navigate to **Settings > API Tokens** (`/settings/tokens`)
2. Enter a name (e.g., "Claude Desktop") and click **Create Token**
3. Copy the token immediately — it won't be shown again
4. The token format is `smcp_...` (approximately 49 characters)

## 2. Claude Code

The repository includes a `.mcp.json` file. Update it with your token:

```json
{
  "mcpServers": {
    "spotify-mcp": {
      "type": "streamable-http",
      "url": "https://music.praxiscode.dev/mcp/v1",
      "headers": {
        "Authorization": "Bearer smcp_YOUR_TOKEN_HERE"
      }
    }
  }
}
```

Claude Code will automatically detect this file when you open the project.

## 3. Claude Desktop

Add the following to your Claude Desktop configuration file:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "spotify-mcp": {
      "type": "streamable-http",
      "url": "https://music.praxiscode.dev/mcp/v1",
      "headers": {
        "Authorization": "Bearer smcp_YOUR_TOKEN_HERE"
      }
    }
  }
}
```

Restart Claude Desktop after saving.

## 4. Verify Connection

Ask Claude: *"What are my top artists from the last 30 days?"*

Claude should use the `history.top_artists` tool and return your listening data.

## Available Tools

34 tools across four categories:

| Category | Examples |
|----------|---------|
| **History** | `history.taste_summary`, `history.top_artists`, `history.top_tracks`, `history.listening_heatmap` |
| **Spotify Live** | `spotify.search`, `spotify.get_track`, `spotify.create_playlist`, `spotify.add_tracks` |
| **Memory** | `memory.get_profile`, `memory.search`, `memory.log_playlist_create` |
| **Ops** | `ops.list_users`, `ops.sync_status` |

## Troubleshooting

- **"Authentication required"**: Verify your token is correct and not revoked
- **Connection refused**: Ensure the server is running and accessible
- **Token not working**: Create a new token from Settings; old tokens may have been revoked

## Security Notes

- Tokens are stored as SHA-256 hashes — the server never stores plaintext tokens
- Revoke tokens you no longer use from the Settings page
- Each token is scoped to your user account only
