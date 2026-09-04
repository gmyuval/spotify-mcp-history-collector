# SPM-6 Remote MCP Conformance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`)
> syntax for tracking.

**Goal:** Preserve every observable v1 MCP behavior while adding an isolated, protocol-conformant
v2 Action and native MCP surface with structured safe results, explicit tool metadata, and
deterministic cross-client evidence.

**Architecture:** Keep `MCPToolRegistry` as the single business-tool registry, add version-specific
projections around a shared v2 invocation contract, and construct native MCP servers with
`mcp.server.lowlevel.Server` and `StreamableHTTPSessionManager`. Isolate the one SDK 1.26.0 raw
call-handler bridge that ADR 0010 requires behind a locally owned, version-pinned adapter and
dependency contract; do not misrepresent that bridge as a documented public SDK hook. V1 and v2
receive separate Action routers, native servers, mounts, and compatibility tests. An opaque
authenticated request principal is converted to a server-owned invocation context; a v2 client can
never select or override `user_id`.

**Tech Stack:** Python 3.14, FastAPI/Starlette, Pydantic 2, MCP Python SDK 1.26.0 low-level server
and Streamable HTTP types, a version-pinned project adapter, pytest, HTTPX/TestClient, uv 0.12.3.

**Spec:** Linear SPM-6; ADR 0010, `docs/decisions/0010-version-the-public-mcp-api-contract-before-correction.md`;
the FastMCP and auth-coexistence rows in
`docs/decisions/0002-azure-target-architecture-and-migration-boundaries.md`;
the MCP 2025-11-25 [tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
and [transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
contracts; the repository-locked MCP SDK 1.26.0 API.

## Acceptance and authority boundary

Owner acceptance of this document authorizes only the repository implementation described below.
It does not authorize implementation from the plan PR itself. After acceptance, implementation
uses sequential task-aligned SPM-6 branches, worktrees, commits, and pull requests under the
repository lifecycle. Each pull request is one independently reviewable vertical slice with
`Part of SPM-6`; do not accumulate all six tasks into one oversized implementation pull request.

This plan deliberately separates three stops:

1. **Plan accepted:** the owner accepts this document before any public MCP/API code changes.
2. **Repository implementation reviewed:** frozen-v1, v2, deterministic-client, and local gate
   evidence are current-head green. This is the furthest standing repository authority reaches.
3. **Live-client evidence separately authorized:** any real ChatGPT, OpenAI Responses, Claude.ai,
   Claude Desktop, Claude Code, Claude Messages, Inspector-against-public-host, client
   configuration, credential, Spotify account/data, deployed edge, or production request waits for
   a separate owner authorization and review. A live-client failure does not justify an unreviewed
   compatibility change.

SPM-10 independently owns the dedicated authentication implementation plan required by ADR 0002.
SPM-6 may consume the current authenticated `request.state.user_id` contract and prove isolation;
it must not add remote MCP OAuth, trusted-identity headers, discovery, dynamic client registration,
new scopes/audiences, account linking, or authentication consolidation.

## Plan decisions selected by owner acceptance

Accepting this plan selects the following implementation choices so a worker does not decide them
implicitly:

1. **SDK seam:** remain on locked `mcp==1.26.0`. Build a locally owned `MCPProtocolServer` adapter
   around `Server` and `StreamableHTTPSessionManager`; do not subclass or reach through `FastMCP`
   internals and do not upgrade the dependency in this slice. The raw call-handler registration
   described next is an explicitly accepted, isolated pinned-SDK dependency, not a public-library
   guarantee.
2. **Unknown native tool:** register the native call request through the project-owned low-level
   adapter so an unknown tool returns JSON-RPC invalid-params with safe
   `data.code=unknown_tool`, as ADR 0010 requires. The SDK's convenience `Server.call_tool()`
   decorator converts handler exceptions to `isError` results, so it is not used for this one
   dispatch boundary. The project adapter may register the pinned SDK's raw request handler, but a
   dependency contract must fail closed if the exact registration or response behavior changes;
   workers then stop for a supported-SDK or plan-amendment decision.
3. **V2 identity:** both v2 adapters consume an opaque authenticated principal supplied by the
   existing upstream auth boundary and reject client-supplied `user_id`. SPM-6 does not select JWT,
   API-token, static-admin/basic, permission, scope, audience, or precedence policy. Tests use a
   synthetic principal provider. If binding either v2 route to production requires any auth-policy
   change rather than reading the already-established principal, that adapter stops on the
   accepted SPM-10 plan.
4. **User enumeration:** `ops.list_users` remains available only on frozen v1. It is absent from
   both v2 catalogs because a user-bound v2 client does not need an internal ID discovery tool and
   the current result exposes other principals. All other v2-exposed tools retain their current
   names.
5. **Result budget:** no numeric public limit is selected without evidence. Before Task 2 can
   finalize schemas, measure sanitized synthetic default/worst-case output sizes for every tool,
   revalidate current primary documentation for each intended client limit, and present explicit
   cap/export options to the owner. Until an amendment is accepted, do not expose an unbounded v2
   result, silently truncate, add artifact storage, or change `memory.export_user_data` behavior.
6. **Transport profile:** keep stateless Streamable HTTP with JSON responses. Do not add an event
   store, standalone SSE stream, resumable session, or notification promise. Deterministic tests
   assert this profile; if separately authorized live-client evidence requires another profile,
   stop for an amended plan before changing it.

## Global constraints

- SPM-6 is the only primary issue. Do not mix SPM-7, SPM-9, SPM-10, SPM-14, infrastructure,
  deployment, or v1-retirement work into its branch, commits, or pull request.
- Capture and review the v1 fixtures before changing MCP production code. A fixture update after
  that baseline is a compatibility decision, not ordinary test maintenance.
- Preserve these v1 boundaries exactly: `GET /mcp/tools`, `POST /mcp/call`, and native `/mcp/v1`.
  Preserve current tool names, ordering, schemas, aliases, precedence, defaults, result shapes,
  errors, status codes, and documented compatibility behavior.
- Add only these v2 boundaries: `GET /api/v2/mcp/tools`, `POST /api/v2/mcp/call`, and native
  `/mcp/v2`. Do not add unversioned redirects, implicit negotiation, duplicate `*.v2` tool names,
  or route fallthrough.
- Keep `mcp==1.26.0` locked for this slice. Its measured public interfaces already provide
  `Server.list_tools()`, `Server.call_tool()`, `StreamableHTTPSessionManager`, tool annotations,
  output schemas, `structuredContent`, and `isError`. A dependency upgrade is separate reviewed
  work and cannot be smuggled into private-boundary removal.
- Production code must not access `FastMCP._mcp_server` or any other underscored SDK member. Pin a
  contract test that fails on a reintroduction.
- Both v2 transports call one shared invocation service. They may translate transport envelopes,
  but cannot implement different validation, authorization, result, or error semantics.
- Keep v1's client-supplied `user_id` behavior frozen. On v2, remove `user_id` from every advertised
  input schema, reject it as an unknown property, and overwrite neither client arguments nor
  principal state. Inject the authenticated principal only after request validation.
- Tool annotations are explicit reviewed hints, never authorization controls. Every v2 tool must
  declare `readOnlyHint`, `destructiveHint`, `idempotentHint`, and `openWorldHint`; registration
  fails closed when the classification or output schema is missing.
- Preserve existing authorization, destructive-write confirmation, track-only media, playlist
  fidelity, quota, and per-user isolation rules. ADRs 0007/0008 continue to govern embed behavior.
- Redact before forming a client-visible message or ordinary log. Never log user/account IDs,
  credentials, tokens, playlist/track IDs, queries, arguments, result data, or Spotify data.
- Deterministic tests use synthetic users, database rows, provider responses, and fixed clocks.
  They perform no live Spotify reads/writes, consume no provider quota, and use no real client
  credentials or configuration.
- Do not deploy, mutate cloud resources, access production, change real clients, retire v1, change
  OAuth/retention/database behavior, or replan a Linear cycle under this plan.

## Measured baseline to preserve

- `services/api/src/app/main.py` currently mounts the native server at `/mcp/v1` and exposes the
  Action router under `/mcp`.
- `services/api/src/app/mcp/mcp_server.py` reaches through `FastMCP._mcp_server`, hides `user_id`
  from native schemas, injects it with a `ContextVar`, and returns JSON text without
  `structuredContent` or `isError` on failures.
- `services/api/src/app/mcp/router.py` exposes the legacy Action catalog/call envelope and redacts
  common credential and identity patterns. `MCPCallRequest` accepts `arguments`, `args`, flat
  fields, precedence rules, and selected field aliases.
- The locked MCP SDK is 1.26.0. Direct inspection under pinned uv 0.12.3 confirms the importable
  low-level server, documented list/call decorators, and Streamable HTTP session manager;
  `Tool` contains `outputSchema` and `annotations`, and `CallToolResult` contains
  `structuredContent` and `isError`. The raw call-handler bridge needed for ADR 0010 is separately
  acknowledged as a pinned implementation dependency. The SDK's measured supported protocol
  versions are `2024-11-05`, `2025-03-26`, `2025-06-18`, and `2025-11-25`; v2 targets
  `2025-11-25` and must reject an unsupported version through protocol negotiation rather than
  silently changing semantics.
- Existing native tests cover schema construction and principal context only; existing Action tests
  exercise legacy aliases and redaction but do not freeze the complete public v1 wire contract.

## V2 contract to implement

### Version routing

| Adapter | V1, frozen | V2, corrected |
|---|---|---|
| Action catalog | `GET /mcp/tools` | `GET /api/v2/mcp/tools` |
| Action call | `POST /mcp/call` | `POST /api/v2/mcp/call` |
| Native MCP | `/mcp/v1` | `/mcp/v2` |

Each native version owns a distinct low-level `Server` and `StreamableHTTPSessionManager` created
for one application lifespan. Enter both managers with an `AsyncExitStack`; never reuse a manager
after its `run()` context exits. Route-order tests send requests to every prefix and near-miss and
prove that no Action route consumes native traffic or vice versa.

### Shared invocation result

Use one locally owned, transport-neutral discriminated result model:

```text
MCPV2Success
  tool: str
  success: Literal[True]
  result: JSON-compatible value

MCPV2Failure
  tool: str
  success: Literal[False]
  error:
    code: stable snake_case string
    message: redacted human-safe string
    retryable: bool
    retry_after_seconds: positive integer, only with valid provider evidence
```

The error taxonomy must at least distinguish validation, authorization, playlist restriction or
incompleteness, Spotify quota exhaustion, ordinary rate limiting, provider unavailability, and
internal failure. Map `QUOTA_EXCEEDED` to non-retryable `spotify_quota_exhausted`; never invent a
quota size, reset time, or retry delay. Do not expose exception class names.

Serialize the complete structured envelope with compact UTF-8 JSON and enforce the separately
accepted evidence-backed budget before either adapter sees it. The text fallback is the same safe
compact JSON for compatibility, so it cannot disagree with `structuredContent`. Before that budget
decision, no v2 route with potentially unbounded output may be published. Tools with unbounded
logical results must use an accepted pagination/result contract or remain excluded from v2; they
cannot truncate, upload an artifact, or invent a continuation mechanism in this slice.

- **V2 Action:** accepts exactly `{"tool": "...", "arguments": {...}}`; FastAPI request-shape
  errors remain 422, authentication/authorization remain 401/403, and an accepted tool invocation
  returns 200 with either `MCPV2Success` or `MCPV2Failure`.
- **V2 native success:** returns `CallToolResult(isError=False)` with the success object in
  `structuredContent` and a deterministic JSON text fallback in `content`.
- **V2 native tool failure:** returns `CallToolResult(isError=True)` with the failure object in
  `structuredContent` and a useful redacted text block in `content`.
- **V2 native protocol failure:** malformed JSON-RPC, invalid request shape, unknown tool name, and
  unsupported method use standard JSON-RPC errors. Use the standard parse/invalid-request,
  invalid-params, or method-not-found code as applicable; any `data.code` is stable and safe. Do not
  disguise these failures as successful tool calls.

Every v2 tool advertises an output schema for its full success/failure structured envelope. The
native handler validates the structured object against that schema before returning it. The Action
response model is generated from the same locally owned contract definitions.

### Principal injection

Define an immutable `MCPInvocationContext` that carries the authenticated application principal,
contract version, and authorization facts needed by the registry. The ASGI boundary obtains the
principal from the existing authentication middleware and sets/resets it in a `finally` block for
native calls. The v2 Action dependency obtains the same principal directly. The invocation service
adds the server-owned user ID only when adapting to a legacy handler that requires it.

Tests must prove unauthenticated rejection, two concurrent principals cannot bleed context, a
client-supplied `user_id` is rejected even when it matches, a forged different ID cannot select
another user's data, context resets after success/failure/cancellation, and logs/results contain no
principal identifier.

### Deterministic client matrix

| Harness | Boundary | Required evidence |
|---|---|---|
| Frozen JSON fixtures + FastAPI `TestClient` | V1 Action | Exact catalog/OpenAPI, aliases, precedence, success/error/status behavior |
| Raw JSON-RPC + ASGI transport | V1 native | Initialize, tools/list, representative call, unknown/malformed request, auth behavior |
| FastAPI `TestClient` | V2 Action | Canonical request only, route isolation, structured success/failure, 401/403/422 distinction |
| MCP SDK `ClientSession` against the local low-level server | V2 native protocol | Negotiation, tools/list metadata, typed call success/error, output-schema validation |
| MCP SDK Streamable HTTP client against a loopback ASGI server | V2 native transport | Headers/auth, JSON response, explicit absence of session/SSE promises, reconnect, clean lifespan |
| Pinned MCP Inspector CLI against that same local synthetic server | V2 native smoke | Initialize, list, read-only call, validation error; command/version captured, no public host |
| Recorded ChatGPT/OpenAI and Claude protocol profiles | V2 projections | Deterministic request/response fixtures only; clearly labeled surrogate, not live-client proof |

The matrix covers catalog discovery; representative read-only and authorized-write tools;
confirmation rejection; search limits 5/1/10 and invalid 0/11; unknown tools; malformed arguments;
structured validation, quota, rate-limit, restriction, incomplete-result, and internal errors;
redaction; per-user isolation; disconnect/reconnect; and graceful shutdown. Pinned Inspector setup may
be added only through the repository's deterministic dependency mechanism and must not write a
real client configuration.

## Acceptance-to-evidence matrix

| SPM-6 / ADR 0010 obligation | Required repository evidence |
|---|---|
| Frozen v1 | Version-scoped catalog, OpenAPI, normalization, success/error, Search, playlist-fidelity, auth, and native transcript fixtures captured before production edits |
| Private FastMCP boundary removed | Static no-`._mcp_server` assertion plus end-to-end tests through the project-owned, version-pinned low-level adapter |
| Explicit v2 routing | Route/mount near-miss matrix for all six boundaries and independent lifespan instances |
| Shared corrected semantics | Native/Action table tests comparing one structured v2 success/failure model |
| Structured and protocol-compliant errors | `structuredContent`, output-schema, `isError`, JSON-RPC error-code, safe-text, result-budget, and retry-evidence tests |
| Tool annotations | Complete v2 exposure/classification matrix and exact `tools/list` assertions; missing metadata fails registration |
| Authenticated per-user injection | Opaque synthetic-principal, hidden/rejected `user_id`, two-user concurrency, forged-ID, cancellation, and context-reset tests; any auth-policy binding stops on SPM-10 |
| Cross-client behavior | Deterministic SDK/raw-wire/Action/Inspector/profile matrix, clearly separated from live-client proof |
| Privacy-safe migration evidence | Version/boundary/outcome metrics including rejected auth, plus negative log/label assertions |
| Separate live authority | An explicit STOP after repository delivery and an owner-visible authorization request before each named real client/environment |

## Root-owned per-task commit protocol

Each task uses a fresh branch and isolated worktree from the newly verified `origin/main` after the
preceding dependent task is merged. One delegated writer may edit only that task's named files and
stops with an unstaged evidence report. The root verifies the real diff and RED/GREEN evidence,
stages only the task's named paths, commits the stated SPM-6 subject, packages the fixed-base diff,
and dispatches independent review. A reviewer never writes in the writer checkout. One fix writer
handles the complete finding set; any byte change expires the old review and gate evidence. Root
publishes one task-aligned `Part of SPM-6` pull request and lands it before branching the next
dependent task. If a slice ceases to be independently reviewable, split it again at a tested
interface without introducing a second issue.

---

### Task 1: Freeze the complete v1 compatibility surface

**Files:**
- Create: `services/api/tests/test_mcp/fixtures/v1/action_catalog.json`
- Create: `services/api/tests/test_mcp/fixtures/v1/action_openapi.json`
- Create: `services/api/tests/test_mcp/fixtures/v1/action_calls.json`
- Create: `services/api/tests/test_mcp/fixtures/v1/native_transcripts.json`
- Create: `services/api/tests/test_mcp/fixtures/v1/document_contracts.json`
- Create: `services/api/tests/test_mcp/test_v1_contract.py`
- Modify only if a fixture serializer is required: `services/api/tests/test_mcp/conftest.py`

**Interfaces:**
- Consumes current `origin/main` before any production MCP edit.
- Produces reviewed deterministic fixtures for all observable ADR 0010 v1 behavior.

- [ ] **Step 1: Enumerate v1 observations before snapshotting**

  Inventory every tool and both catalogs; `arguments`, `args`, flat, mixed-precedence, and field
  aliases; documented defaults; success/error envelopes; Search boundaries; playlist fidelity;
  authentication/authorization; redaction; native initialize/list/call/protocol errors; and
  normalized contracts for `docs/chatgpt-openapi.json` and `docs/chatgpt-tool-catalog.md`.

- [ ] **Step 2: Generate sanitized fixtures from fixed synthetic state**

  Use stable IDs, fixed clocks, sorted keys, deterministic catalog order, and mocked providers.
  Hand-review the fixture diff for credentials, PII, Spotify data, machine paths, and volatile
  values. Commit generated bytes; do not make tests regenerate or bless them automatically.

- [ ] **Step 3: Add exact fixture comparisons and mutation controls**

  Require byte-normalized equality for JSON/OpenAPI and semantic equality for protocol transcripts.
  Demonstrate a temporary mutation of a route, alias precedence, result field, error text, and
  native schema fails, then restore GREEN.

- [ ] **Step 4: Run the v1 baseline gate and stop for root review**

  Run the complete `test_mcp` suite plus focused v1 contracts with pinned uv 0.12.3. Record the
  exact base SHA and fixture hashes. Root reviews and commits:
  `test(mcp): freeze v1 compatibility contract (SPM-6)`.

### Task 2: Add the locally owned v2 contract and explicit tool metadata

**Files:**
- Create: `services/api/src/app/mcp/v2_contract.py`
- Modify: `services/api/src/app/mcp/registry.py`
- Modify: `services/api/src/app/mcp/schemas.py`
- Modify: `services/api/src/app/mcp/tools/*.py`
- Create: `services/api/tests/test_mcp/test_v2_contract.py`
- Modify: `services/api/tests/test_mcp/test_registry.py`

**Interfaces:**
- Produces `MCPInvocationContext`, `MCPV2Success`, `MCPV2Failure`, stable error mapping, and one
  registry invocation service used by both v2 adapters.
- Extends internal tool definitions with explicit annotations and result schemas without changing
  the serialized v1 `MCPToolDefinition`.

- [ ] **Step 1: Write RED contract, error, and metadata tests**

  Require all current tools to declare all four annotation hints and an output schema. Assert
  fail-closed registration for omitted metadata, stable error-code/retry mapping, safe messages,
  and exact JSON-compatible success/failure serialization. Pin `ops.list_users` as v1-only and
  prove all other expected v2 names are present.

- [ ] **Step 2: Measure result sizes and stop for the budget decision**

  Generate sanitized synthetic default/worst-case outputs for every tool, record compact UTF-8
  envelope sizes, and revalidate primary client limit documentation. Present cap, per-tool
  pagination, v2 exclusion, and `memory.export_user_data` options with compatibility, privacy,
  implementation, and rollback tradeoffs. Amend this plan only after explicit owner acceptance;
  do not proceed to a public v2 schema with an unbounded or guessed contract.

- [ ] **Step 3: Add internal version-specific projections**

  Keep the legacy v1 projection byte-compatible. Add a v2 projection that removes `user_id`, uses
  `additionalProperties: false`, supplies annotations and output schemas, and preserves stable tool
  names. Do not add v2 fields to the v1 Action response model.

- [ ] **Step 4: Classify every tool explicitly**

  Review every history, memory, playlist, Spotify, and ops tool. Treat annotations only as client
  hints; keep RBAC and confirmation checks authoritative. Add a test that compares the registered
  name set to the checked classification set so a future tool cannot bypass review.

- [ ] **Step 5: Implement the shared invocation service test-first**

  Validate client arguments before principal injection, adapt the server-owned principal only at
  the legacy handler seam, normalize results, map known failures, redact unknown failures, and log
  only approved low-cardinality fields.

- [ ] **Step 6: Run focused/full MCP tests and stop for root review**

  Re-run all v1 fixtures to prove the internal extension is invisible to v1. Root reviews and
  commits: `feat(mcp): define v2 invocation contract (SPM-6)`.

### Task 3: Replace the private FastMCP boundary and mount isolated native versions

**Files:**
- Modify: `services/api/src/app/mcp/mcp_server.py`
- Modify: `services/api/src/app/main.py`
- Modify: `services/api/tests/test_mcp/test_mcp_server.py`
- Create: `services/api/tests/test_mcp/test_native_version_routing.py`
- Modify: `services/api/tests/test_token_auth_middleware.py`

**Interfaces:**
- Produces low-level `Server` plus `StreamableHTTPSessionManager` factories for v1 and v2, with
  the raw call registration isolated and named as a version-pinned project dependency.
- Preserves the native v1 wire while routing native v2 through the shared v2 invocation service.

- [ ] **Step 1: Add RED pinned-boundary and route-isolation tests**

  Assert production source contains no `._mcp_server` access; listing uses the documented
  low-level decorator; calling is contained in the one version-tested raw-handler bridge; both
  managers start and stop exactly once per lifespan; and `/mcp/v1`, `/mcp/v2`, `/mcp`,
  `/api/v2/mcp`, trailing-slash variants, and near-misses cannot intercept one another.

- [ ] **Step 2: Build a locally owned native-server factory**

  Register listing through `Server.list_tools()`. Register calling through the locally owned pinned
  handler bridge required for ADR 0010's unknown-tool JSON-RPC error; do not describe that bridge as
  a documented SDK API. Construct each `StreamableHTTPSessionManager` with the existing
  JSON-response, stateless, and transport-security settings. Keep context injection in locally
  owned middleware and always reset its token.

- [ ] **Step 3: Keep v1 and v2 translation separate**

  Route v1 through its frozen projection/legacy result adapter. Route v2 through the v2 catalog and
  invocation result. The locally owned low-level call handler returns JSON-RPC invalid-params for
  an unknown name before invoking the SDK convenience result wrapper; execution failures return
  `CallToolResult(isError=True)`. Share registry semantics, not wire envelopes.

- [ ] **Step 4: Prove auth isolation and cancellation cleanup**

  Exercise no principal, two concurrent principals, forged `user_id`, handler failure, disconnect,
  and cancellation. Assert no context leak and no sensitive ordinary logs.

- [ ] **Step 5: Run v1/v2 native gates and stop for root review**

  Re-run the frozen v1 suite and dependency contract. Root reviews and commits:
  `refactor(mcp): isolate native server boundary (SPM-6)`.

### Task 4: Add the canonical v2 Action adapter

**Files:**
- Create: `services/api/src/app/mcp/v2_router.py`
- Modify: `services/api/src/app/main.py`
- Create: `services/api/tests/test_mcp/test_v2_router.py`
- Modify: `services/api/tests/test_admin/test_auth.py`

**Interfaces:**
- Produces `GET /api/v2/mcp/tools` and `POST /api/v2/mcp/call` over the same v2 projections and
  invocation service as native v2.

- [ ] **Step 1: Add RED canonical-request and failure-layer tests**

  Accept `tool` plus `arguments` only. Reject `args`, flat fields, ambiguous combinations,
  `user_id`, and unknown properties. Consume an opaque synthetic authenticated principal in
  adapter tests; separately assert unauthenticated, forbidden-as-supplied-by-auth-boundary, 422,
  200-success, and 200-tool-failure behavior without choosing credential or permission policy.

- [ ] **Step 2: Add the explicit router without touching legacy routing**

  Mount only at `/api/v2/mcp`; consume the existing upstream principal and call the shared v2
  service. Do not delegate to the legacy `MCPRouter.call_tool` request normalizer. If a production
  binding needs credential-mode, permission, scope, audience, or precedence changes, stop this
  adapter on the separately accepted SPM-10 plan.

- [ ] **Step 3: Prove native/Action semantic parity**

  Table-drive the same synthetic cases through both v2 adapters and compare the structured object
  after removing transport-only fields. Pin catalog name/input/output/annotation parity.

- [ ] **Step 4: Re-run frozen v1 and stop for root review**

  Root reviews and commits: `feat(mcp): expose isolated v2 action routes (SPM-6)`.

### Task 5: Complete deterministic client and protocol conformance

**Files:**
- Create: `services/api/tests/test_mcp/test_v2_client_matrix.py`
- Create: `services/api/tests/test_mcp/fixtures/v2/client_profiles.json`
- Modify as required: repository dependency manifest/lock for an exact Inspector version
- Modify: `.github/workflows/ci.yml` only if the deterministic Inspector gate is proven reliable

**Interfaces:**
- Produces the deterministic matrix defined above, with explicit separation between real protocol
  clients and recorded branded-client profiles.

- [ ] **Step 1: Add SDK in-process and Streamable HTTP clients**

  Use MCP `ClientSession` with the low-level server for protocol semantics and a loopback
  ASGI server for full HTTP/auth/lifespan behavior. Bind only loopback on an ephemeral port; use
  synthetic tokens and state. Assert stateless JSON response behavior and no advertised or implied
  event-store, resumable-session, standalone-SSE, or notification contract.

- [ ] **Step 2: Pin and add the Inspector smoke gate**

  Verify the exact Inspector package/version and invocation from primary documentation, then add
  it through deterministic repository tooling. Run only against the synthetic local server. If a
  hermetic Inspector gate cannot be achieved, record it as unavailable evidence and keep it out of
  required CI rather than adding a flaky or floating command.

- [ ] **Step 3: Add branded-client protocol profiles without overclaiming**

  Capture only documented request/response expectations necessary for ChatGPT/OpenAI and Claude
  projections. Label these fixtures as deterministic surrogates. A green fixture never counts as
  proof that a current hosted/desktop client connects or renders the result.

- [ ] **Step 4: Exercise the complete matrix and negative controls**

  Cover the scenarios listed in this plan. Mutate annotations, output schema, route, auth header,
  `isError`, structured content, retry evidence, redaction, and context cleanup one at a time; each
  mutation must fail before restoring GREEN.

- [ ] **Step 5: Run the full repository gate and stop for root review**

  Root reviews and commits: `test(mcp): prove deterministic v2 conformance (SPM-6)`.

### Task 6: Add privacy-safe version observability and correct setup documentation

**Files:**
- Modify: `services/api/src/app/middleware.py` or add one narrowly owned MCP metrics module
- Modify: `services/api/src/app/mcp/router.py`
- Modify: `services/api/tests/test_middleware.py`
- Modify: `services/api/tests/test_mcp/test_router.py`
- Modify: `docs/claude-integration-setup.md`
- Modify: `docs/chatgpt-gpt-setup.md`
- Modify: `README.md`

**Interfaces:**
- Produces privacy-safe request counts/outcomes/latency by contract version, boundary, and tool
  class, including requests rejected before handlers run.
- Documents v1 as current and v2 as available without changing a real client configuration.

- [ ] **Step 1: Add RED metric/log privacy tests**

  Cover all six v1/v2 boundaries and rejected authentication. Permit only bounded version,
  boundary, aggregate auth outcome, result code, latency, and reviewed tool-class labels. Prove
  user/account IDs, credentials, tool arguments, identifiers, queries, and results never appear.

- [ ] **Step 2: Instrument the authentication/edge boundary**

  Count every non-health request even when rejected before routing. Do not use telemetry to infer
  v1 retirement or start a 30-day clock in this slice.

- [ ] **Step 3: Correct documentation without migrating consumers**

  Document exact v1/v2 URLs, canonical v2 request form, structured errors, annotations, and the
  current auth boundary. Mark any real-client setup or migration step as separately authorized.
  Do not add credentials, machine-specific paths, `.mcp.json`, or desktop configuration files.

- [ ] **Step 4: Re-run frozen v1 and stop for root review**

  Root reviews and commits: `docs(mcp): document versioned conformance surface (SPM-6)`.

## Root-owned integration, review, and delivery

For each Task 1-6 slice, and again after the final slice lands, the root:

1. Reconciles every SPM-6 acceptance criterion and ADR 0010 validation row against the final diff.
   Confirm SPM-10 authentication design, Azure/deployment work, real-client mutation, production,
   Spotify data, database/retention, and v1 retirement remain absent.
2. Runs with pinned uv 0.12.3: focused v1/v2 MCP tests; all API tests; `make agent-contract`;
   `uv run --locked ruff check .`; `uv run --locked ruff format --check .`; strict mypy over all
   service source roots; `uv run --locked pre-commit run --all-files`; `git diff --check`; and every
   repository CI-parity gate. Any unavailable check is a gap, not green evidence.
3. Runs fresh v1 fixture hashes, every client-matrix control and mutation, the SDK/Inspector
   dependency contract, the route near-miss matrix, concurrency/cancellation isolation, and a
   masked sensitive-content audit without printing matches.
4. Dispatches whole-slice spec and quality reviews from a fixed `origin/main...HEAD` range. Any
   byte change expires review evidence. One writer resolves the complete finding set in one review
   round, then root reruns exact-head gates and scoped re-review.
5. Publishes that task's `codex/spm-6-...` branch and `SPM-6:` pull request only after plan
   acceptance, using `Part of SPM-6`. Follow `coderabbit-review` and `gate-oracle`; merge only a
   qualifying exact head under standing repository authority. Refresh `origin/main` before the
   next task. No slice merge deploys or migrates a client.
6. Reads back GitHub, `origin/main`, worktrees, and Linear after every merge. Reconcile SPM-6 only
   to the state proven by the landed repository slices; do not use `Fixes SPM-6` or mark
   live-client, production, Azure, or retirement gates complete from deterministic evidence.

## Separately authorized live-client evidence

Do not execute this section under plan acceptance or repository-delivery authority. Prepare a
fresh, owner-visible authorization request naming the exact client, account/environment,
configuration mutation, credential handling, public endpoint, Spotify side-effect budget, rollback,
and evidence retention before each live batch.

When separately approved, measure—do not infer—initialize/version negotiation, advertised
capabilities, discovery, representative read-only/validation/quota/restriction/write-confirmation
flows, structured-result rendering, error rendering, reconnect, graceful shutdown, and rollback to
v1 for each approved client. The expected transport result is successful JSON-only Streamable HTTP
POST behavior plus the standards-defined GET/no-SSE behavior for the selected stateless profile.
Record whether the client tolerates that profile; if it requires SSE, resumption, or notifications,
stop for the transport amendment instead of treating SSE as required success evidence. Record
current client and server versions. Keep OpenAI/ChatGPT, Claude variants, and Inspector evidence
distinct. A result from one client never proves another.

Changing real client configuration, exercising a deployed edge, using production credentials or
Spotify data, cutover, deployment, and starting v1 retirement each require their own explicit
authority. V1 retirement still requires the separate reviewed removal plan, owner-confirmed
consumer inventory, and complete 30-day zero-use evidence in ADR 0010.

## Rollback and revisit triggers

- Until a separately authorized client migration occurs, reverting the reviewed SPM-6
  implementation removes only the isolated v2 routes and observability while the frozen v1 routes
  remain the compatibility path; no data rollback or schema migration is involved.
- A separately authorized migrated client that fails returns to its recorded v1 configuration.
  Do not repair it by changing frozen v1 response bodies or by bypassing auth, schema, or error
  gates.
- Stop and amend this plan before implementation if locked SDK 1.26.0 no longer supplies the
  measured low-level seam, no result-budget/export option is accepted, the annotation matrix
  exposes a material ambiguity, or the opaque principal cannot be consumed without SPM-10 work.
- Stop after deterministic repository delivery if a real client requires SSE/resumption, OAuth
  discovery/registration, a different protocol version, a different result budget, or a client
  configuration/public-edge change. Present measured evidence and an explicit owner choice before
  expanding the contract.
- Do not begin v1 retirement in SPM-6. It remains gated by the owner-confirmed inventory, 30
  consecutive days of zero non-health v1 use including rejected authentication, healthy v2,
  rollback proof, a separately reviewed removal plan, and explicit owner approval.
