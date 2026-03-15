# Phase 3 — MCP Protocol Compliance & Claude Integration

**Branch:** `feat/phase-3-mcp-protocol`
**Version:** 0.3.0 → 0.4.0
**PRD reference:** `docs/prd-dev-step2.md` § Phase 3

---

## Overview

Three deliverables:
1. **3.1 MCP JSON-RPC Server** — Standards-compliant MCP server using the official `mcp` Python SDK, mounted alongside the existing ChatGPT-compatible `/mcp/call` endpoint.
2. **3.2 User API Tokens** — New `api_tokens` DB table, token management API endpoints, and Explorer UI so users can generate long-lived Bearer tokens for Claude Desktop / Claude Code.
3. **3.3 Claude Integration Config** — `.mcp.json` for Claude Code + setup guide documentation.

---

## Key Design Decision: Official MCP Python SDK

Instead of implementing JSON-RPC 2.0 from scratch, we use the **official `mcp` Python SDK** (`modelcontextprotocol/python-sdk`, `mcp>=1.12.0`). It provides:
- `Server` class with `streamable_http_app()` → returns an ASGI app
- Built-in streamable HTTP transport (POST for requests, GET for SSE)
- Session management (`Mcp-Session-Id` header)
- JSON-RPC 2.0 handling (initialize, tools/list, tools/call, ping)

We write a thin **adapter layer** that bridges our existing `MCPToolRegistry` (34 tools) to the SDK's handler callbacks. No need for custom `jsonrpc.py` or `sse_transport.py`.

---

## File Checklist

### API layer (`services/api/`)

- [ ] **NEW** `src/app/mcp/mcp_server.py` — MCP SDK adapter: creates `mcp.server.Server`, registers `list_tools` and `call_tool` handlers that delegate to `MCPToolRegistry`, exposes ASGI app for mounting
- [ ] `src/app/mcp/router.py` — Keep existing `/mcp/call` and `/mcp/tools` (ChatGPT compat); no changes needed
- [ ] `src/app/main.py` — Mount MCP SDK ASGI app; manage MCP session lifecycle in lifespan
- [ ] `src/app/auth/middleware.py` — Extend `_extract_token` to resolve non-JWT Bearer tokens by looking up hashed tokens in `api_tokens` table
- [ ] **NEW** `src/app/auth/api_tokens.py` — `ApiTokenService`: generate, validate, list, revoke tokens; SHA-256 hashing
- [ ] `src/app/explorer/router.py` — Add token management endpoints: `GET /api/me/tokens`, `POST /api/me/tokens`, `DELETE /api/me/tokens/{token_id}`
- [ ] `src/app/explorer/schemas.py` — Add token request/response schemas

### Shared DB (`services/shared/`)

- [ ] **NEW** `src/shared/db/models/api_token.py` — `ApiToken` model: id, user_id (FK), name, token_prefix (first 8 chars), token_hash (SHA-256), created_at, last_used_at, revoked_at
- [ ] `src/shared/db/models/__init__.py` — Export `ApiToken`

### Migration (`services/api/alembic/`)

- [ ] **NEW** `versions/011_api_tokens.py` — Create `api_tokens` table with index on `(user_id, revoked_at)`

### Explorer frontend (`services/explorer/`)

- [ ] `src/explorer/api_client.py` — Add `get_tokens()`, `create_token()`, `revoke_token()` methods
- [ ] **NEW** `src/explorer/routes/settings.py` — `SettingsRouter`: token list page, create/revoke actions
- [ ] `src/explorer/routes/__init__.py` — Export `settings_router`
- [ ] `src/explorer/main.py` — Register settings router at `/settings`
- [ ] **NEW** `src/explorer/templates/settings/tokens.html` — Token management UI (list, create, revoke, show-once modal for new tokens)
- [ ] `src/explorer/templates/base.html` — Add "Settings" nav link

### Config files

- [ ] **NEW** `.mcp.json` — Claude Code MCP config (placeholder URL + Bearer token)
- [ ] **NEW** `docs/claude-integration-setup.md` — Setup guide for Claude Desktop + Claude Code

### Dependencies

- [ ] `services/api/pyproject.toml` — Add `mcp>=1.12.0` dependency
- [ ] `services/api/requirements.txt` — Recompile via pip-compile

### Version bump

- [ ] `services/shared/src/shared/version.py` — `0.3.0` → `0.4.0`

---

## API Contracts

### MCP Protocol Endpoint

Standard MCP JSON-RPC 2.0 — handled by the SDK. The ASGI app is mounted so that `POST` and `GET` requests reach the SDK's streamable HTTP handler.

Supported methods:
- `initialize` → server info + capabilities (`{tools: {listChanged: false}}`)
- `tools/list` → all 34 tools in MCP `inputSchema` format
- `tools/call` → dispatches to existing handlers, wraps result as `{content: [{type: "text", text: "<json>"}]}`
- `ping` → keep-alive
- `notifications/cancelled` → no-op (acknowledged)

Auth: `Authorization: Bearer <token>` header (JWT or API token). The adapter resolves `user_id` from request context and injects it into tool args.

### `POST /api/me/tokens` — Create API token

Request:
```json
{"name": "Claude Desktop"}
```

Response (201, token shown only once):
```json
{
  "token_id": 1,
  "name": "Claude Desktop",
  "token": "smcp_a1b2c3d4e5f6...",
  "prefix": "smcp_a1b",
  "created_at": "2026-03-14T12:00:00Z"
}
```

### `GET /api/me/tokens` — List tokens

Response:
```json
{
  "items": [
    {
      "token_id": 1,
      "name": "Claude Desktop",
      "prefix": "smcp_a1b",
      "created_at": "2026-03-14T12:00:00Z",
      "last_used_at": "2026-03-14T15:30:00Z"
    }
  ]
}
```

### `DELETE /api/me/tokens/{token_id}` — Revoke token

Response: 204 No Content (soft delete via `revoked_at` timestamp)

### Existing ChatGPT Endpoints (unchanged)

`POST /mcp/call` and `GET /mcp/tools` continue working with admin Bearer token at their current paths.

---

## Routing Strategy

The existing `/mcp` prefix hosts ChatGPT endpoints (`/mcp/call`, `/mcp/tools`). The MCP SDK app handles `POST /mcp/v1` and `GET /mcp/v1`.

- ChatGPT: `POST /mcp/call`, `GET /mcp/tools` — existing FastAPI router (unchanged)
- MCP protocol: `POST /mcp/v1`, `GET /mcp/v1` — SDK ASGI app mounted via Starlette `Mount`
- Claude Desktop/Code config uses `url: "https://music.praxiscode.dev/mcp/v1"`
- Caddy already routes `/mcp/*` → api:8000 with no auth gate

---

## Auth Flow for MCP

1. User generates API token via Explorer UI (`/settings/tokens`)
2. Token format: `smcp_` prefix + 32 bytes URL-safe base64 (total ~49 chars)
3. Token stored as SHA-256 hash in DB; plaintext shown once on creation
4. User configures Claude Desktop/Code with `Authorization: Bearer smcp_...`
5. On MCP request: middleware extracts Bearer token → not a JWT (no dots) → not admin token → look up `sha256(token)` in `api_tokens` → set `request.state.user_id`
6. MCP server adapter reads `user_id` from request context and injects into tool args
7. `last_used_at` updated on each successful token validation

---

## UI Behavior

### `/settings/tokens` page

- Card-based layout showing existing tokens (name, prefix, created, last used)
- "Create Token" button → modal/form with name input
- On create: show token once in a highlighted box with copy button + warning "This token won't be shown again"
- "Revoke" button per token → confirmation → soft delete
- Empty state: "No API tokens yet. Create one to use with Claude Desktop or Claude Code."

---

## Tests

### API tests (`services/api/tests/`)

- `test_api_tokens.py` — Token CRUD: create, list, revoke, validate hash, duplicate names allowed, revoked tokens rejected
- `test_token_auth_middleware.py` — API token auth in middleware: valid token → user_id set, revoked token → unauthenticated, unknown token → unauthenticated
- `test_mcp/test_mcp_server.py` — MCP protocol: adapter correctly translates registry tools to MCP schema, tools/call dispatches correctly

### Explorer tests (`services/explorer/tests/`)

- `test_settings_route.py` — Token management pages: list, create, revoke, login required

---

## Implementation Order

1. DB model + migration (`api_tokens` table)
2. `ApiTokenService` (generate, validate, hash, list, revoke)
3. Auth middleware extension (resolve API tokens from DB)
4. Token management API endpoints + schemas
5. MCP SDK adapter (`mcp_server.py`) — bridge registry → SDK handlers
6. Mount MCP SDK app in `main.py`
7. Explorer API client methods for tokens
8. Explorer settings router + template
9. Config files (`.mcp.json`, `docs/claude-integration-setup.md`)
10. Tests
11. Version bump to 0.4.0
12. Docker test (`docker-compose up --build`), verify all services healthy
13. Present changes for approval

---

## Workflow

1. Implement in order above
2. Run unit tests locally (API + Explorer separately)
3. `docker-compose up --build` — verify all services healthy, test MCP endpoint with curl, test token management UI
4. `docker-compose down`
5. Present summarized file list for approval
6. Bump version to 0.4.0, commit, push, create PR via GitHub MCP
