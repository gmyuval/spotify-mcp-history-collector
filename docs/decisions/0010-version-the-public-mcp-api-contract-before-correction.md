# ADR 0010 - Version the public MCP/API contract before correction

Date: 2026-08-27 (UTC)
Status: Accepted
Decision owners: Yuval Moran
Linear issue: [SPM-5](https://linear.app/stratex/issue/SPM-5/audit-and-update-for-spotify-web-api-changes-through-august-2026)

Owner evidence: after reviewing additive in-place correction, parallel versioning, and an immediate
clean break, Yuval Moran selected a modified parallel-versioning approach with:

> I'd go with modified option B - freeze v1, introduce v2, ensure nothing breaks, retire v1. In
> general, not much is currently connected to the MCP

## Context

The repository exposes two related public integration surfaces:

- the existing ChatGPT Custom GPT Action calls `POST /mcp/call`, with `GET /mcp/tools` as
  its catalog and a response envelope containing `tool`, `success`, `result`, and `error`; and
- Claude and other native MCP clients can use the Streamable HTTP server mounted at `/mcp/v1`.

Both surfaces use the same tool registry but do not have the same wire contract. The Action accepts
flat arguments, `arguments`, legacy `args`, and aliases such as `search_type`. The native MCP server
uses MCP content blocks but currently serializes tool failures as ordinary text results without
setting the protocol's `isError` flag. The current Spotify Search catalog advertises a default of
10 and a range of 1 through 50, while Spotify's current documented endpoint defaults to 5 and
accepts at most 10 results per request. Playlist restriction warnings also contain an unsupported
approximate 100-track explanation.

Changing these behaviors in place would be operationally simple, but it would make it difficult to
distinguish a deliberate correction from an accidental client break. Very few clients are believed
to be connected today, which makes an explicit migration inexpensive. Low observed traffic alone
does not prove that a dormant client no longer exists.

The [MCP tools specification](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
supports structured tool results and an `isError` signal. Both
[OpenAI](https://developers.openai.com/api/docs/guides/tools-connectors-mcp) and
[Anthropic](https://platform.claude.com/docs/en/agents-and-tools/mcp-connector) support remote MCP
tool use, but the repository's existing ChatGPT Action remains a separate OpenAPI contract. A
version boundary must therefore cover both adapters rather than assuming that changing the native
server automatically migrates the Action.

## Decision drivers

- Do not break the current ChatGPT Action, Claude configuration, scripts, or undocumented but
  observable v1 behavior while a replacement is being proven.
- Correct stale Spotify Search, quota-error, and playlist-warning semantics in one coherent target
  contract rather than accumulating special cases in v1.
- Make failures machine-readable and protocol-correct without requiring text parsing.
- Keep migration proportional to an initial one-to-five-user, personal-and-friends product.
- Make v1 temporary: versioning is a migration mechanism, not a commitment to permanent dual
  maintenance.
- Require evidence about every known consumer and actual v1 use before removal.
- Preserve ADR 0008's separate owner gate for retiring undocumented embed scraping.
- Keep client configuration, production traffic, credentials, deployment, and destructive removal
  behind their applicable plans and authority gates.

## Options considered

### Correct the current contract additively in place

Preserve the existing endpoints, names, aliases, success shapes, and playlist fidelity fields while
adding structured errors and correcting unsupported limits. This has the least implementation
overhead, but even justified corrections can change how existing clients react to errors or invalid
Search requests.

### Freeze v1, introduce v2, migrate, and retire v1

Capture and protect v1, build a corrected v2 contract at explicit versioned endpoints, migrate the
small known client set with rollback available, observe the absence of v1 use, and then retire v1
through a separately reviewed removal gate. This adds temporary duplication but makes compatibility
evidence and the end state explicit.

### Replace the current contract immediately

Make native MCP the only canonical surface, remove legacy Action forms, correct Search and errors,
and require all clients to move at once. This reaches the cleanest shape fastest but creates an
unnecessary coordinated cutover and conflicts with the requirement to demonstrate that nothing
breaks.

## Decision

Freeze v1, introduce a corrected v2, migrate every known consumer, and retire v1 after evidence and
an explicit removal gate.

1. Define the v1 compatibility surface as:

   - `GET /mcp/tools` and `POST /mcp/call` for the Action adapter;
   - `/mcp/v1` for the existing native MCP server;
   - the current tool names, request forms, aliases, success-result shapes, error text/envelopes,
     playlist fidelity fields, and documented defaults; and
   - the current ChatGPT OpenAPI and tool-catalog documents.

   Before v2 implementation, capture this surface in version-scoped contract fixtures and tests.
   V1 receives no new product features. Security fixes, provider-compatibility repairs, and defects
   may be fixed only when regression evidence shows the public v1 shape remains compatible. Internal
   translation may use several bounded, quota-aware Spotify requests to honor a legacy v1 request;
   it must not silently claim complete success after a partial provider result.

2. Expose v2 through explicit versioned boundaries:

   - `GET /api/v2/mcp/tools` and `POST /api/v2/mcp/call` for the Action adapter; and
   - `/mcp/v2` for the native MCP server.

   The separate `/api/v2/mcp` prefix prevents the Action adapter from colliding with the native MCP
   mount. Route and mount ordering must still be tested so `/mcp/v1` and `/mcp/v2` remain isolated.
   Both v2 adapters must invoke one shared v2 application contract rather than implementing
   independent business semantics. Tool names remain stable within the v2 server; clients select
   a version by endpoint, not by choosing duplicated `*.v2` tool names.

3. Give v2 a deliberate contract:

   - Spotify Search defaults to 5 and accepts product-useful limits from 1 through 10. Invalid
     values receive a validation error; they are not silently clamped.
   - Tool failures have stable codes, a safe human message, `retryable`, and an optional
     `retry_after_seconds` only when supported by valid provider evidence.
   - `QUOTA_EXCEEDED` maps to a non-retryable `spotify_quota_exhausted` error. Ordinary rolling
     rate limits remain distinct and may be retryable only when the operation and provider evidence
     permit it. No quota size, reset time, or retry delay is invented.
   - Native MCP failures set `isError: true`, preserve a useful text content block, and provide
     structured content and output schemas where supported.
   - The v2 Action keeps transport/authentication failures distinct from tool-execution failures.
     Tool failures use a stable JSON envelope rather than exposing exception class names.
   - The stale approximate 100-track Development warning is removed. Playlist restriction and
     completeness are represented by stable machine-readable codes and source-neutral fidelity
     data plus safe human guidance.
   - V2 has one canonical request form per adapter. The Action may retain a documented alias such
     as `search_type` when required by its OpenAPI representation, but it does not inherit legacy
     `args` or ambiguous precedence rules. Native MCP follows MCP `arguments`.
   - Existing authorization, user isolation, destructive-operation confirmation, and track-only
     media boundaries remain unchanged unless another accepted decision changes them.

4. Keep undocumented embed retirement separate. During the ADR 0008 migration, v1 retains its
   current embed-visible fields. V2 uses source-neutral fidelity fields that can report a
   transitional embed source without promising the private parser as a permanent provider. Removing
   the parser, stopping outbound embed calls, or declaring the transitional value unreachable still
   requires ADR 0008's replacement evidence and explicit owner retirement gate.

5. Migrate without live shadow side effects:

   - Inventory every known Action schema, Custom GPT, Claude MCP configuration, script, and other
     consumer before changing one.
   - Validate v1 and v2 against deterministic fixtures and the supported client SDK/protocol
     harnesses. Do not duplicate live Spotify reads, writes, quota consumption, or playlist
     mutations merely to compare versions.
   - Migrate known consumers one at a time. Each client must pass representative discovery,
     read-only, validation-error, quota-error, restricted-playlist, and authorized write flows as
     applicable, with a documented route back to v1.
   - Changing a real ChatGPT/Claude configuration, using credentials or real Spotify data, and
     exercising production traffic remain separately authorized external effects.

6. Add privacy-safe version observability before migration. Count authenticated calls, successes,
   error codes, and latency by contract version and tool class. Do not place user IDs, account IDs,
   tokens, playlist or track IDs, queries, arguments, result data, or other PII in metric labels or
   ordinary logs. V1 deprecation notices may use headers or server metadata only when they do not
   alter the frozen response body.

7. Retire v1 as a planned contraction, not automatically:

   - every known consumer is inventoried, migrated, and verified on v2;
   - the owner confirms that the inventory includes every intended connection;
   - authenticated v1 call telemetry shows zero calls for 30 consecutive days after the last known
     consumer migrates; any v1 call resets the observation window and is investigated;
   - v2 has no unresolved migration incident and all contract, security, and client-compatibility
     gates are green;
   - a tested rollback can restore the v1 route from a known repository/deployment revision; and
   - the removal is covered by a separately reviewed plan and explicit owner approval at the
     retirement gate.

   A calendar date, low traffic, or the initial small cohort cannot substitute for these checks.
   Once the gate is approved and completed, remove v1 routes, adapters, fixtures that exist only to
   preserve v1 quirks, and v1 setup documentation in one reviewable delivery. Do not leave an
   undocumented compatibility route active indefinitely.

8. This ADR records the accepted target and migration boundary. It does not itself grant authority
   to implement v2, change live clients, inspect credentials or user data, deploy, modify production,
   or remove v1.

## Consequences

- Current integrations can remain on a regression-tested v1 while v2 is developed and proven.
- V2 can use correct Spotify limits and MCP error semantics without pretending they are wire-identical
  to v1.
- The small number of known connections makes one-at-a-time migration practical.
- Temporary dual maintenance increases route, schema, documentation, and test work.
- The 30-day zero-use window may dominate the retirement schedule, but it is inexpensive and
  protects dormant clients.
- V1 cannot receive new product features, preventing the migration bridge from becoming a permanent
  second product surface.
- V2's source-neutral playlist fidelity contract avoids another public breaking change when the
  separately governed embed parser is eventually retired.

## Validation

The implementation and rollout plans must include:

- frozen v1 catalog, request-normalization, success, error, Search, playlist-fidelity, and Action
  OpenAPI snapshot tests;
- v1 regression tests for ChatGPT Action and native MCP clients, including legacy aliases and
  inputs actually documented or observed;
- v2 endpoint isolation and route-order tests proving `/mcp/v1`, `/mcp/v2`, and `/api/v2/mcp`
  cannot intercept or masquerade as one another;
- v2 Search tests for default 5, limits 1 and 10, invalid 0 and 11, provider pagination boundaries,
  and no silent clamping or partial-completeness claim;
- v2 native MCP tests for `isError`, structured content, output-schema conformance, and safe text;
- v2 Action tests for its canonical request form, structured error envelope, and transport versus
  tool-error distinction;
- exact quota tests for non-retrying `spotify_quota_exhausted`, ordinary rate limits, malformed or
  missing `Retry-After`, and absence of invented reset data;
- playlist restriction, completeness, track-only, and transitional-source tests consistent with
  ADRs 0007 and 0008;
- user-isolation, authorization, write-confirmation, sensitive-data redaction, and privacy-safe
  version-metric tests;
- a named consumer inventory and per-consumer migration checklist in Linear, not in this ADR;
- authorized compatibility evidence for each real client before its cutover, plus rollback proof;
  and
- retirement evidence covering owner-confirmed inventory, the complete 30-day zero-call window,
  v2 health, rollback readiness, and fresh Standards and Spec reviews.

## Rollback / revisit trigger

Before v1 retirement, a v2 defect or client incompatibility rolls the affected consumer back to v1
without changing that consumer's data. Pause migration, preserve version telemetry, correct v2, and
repeat the client gate. Do not repair a migration incident by changing frozen v1 response bodies.

After an approved v1 retirement, an incident rollback may restore the last known v1-capable
repository and deployment revision through the documented rollback procedure. Long-term restoration
of v1, relaxation of the retirement evidence, or a new public version requires an amendment or
superseding ADR.

Revisit this decision if a critical v1 vulnerability cannot be fixed compatibly, a required client
cannot consume v2, either provider materially changes its MCP/Action support, or measured dual-stack
cost is disproportionate before the retirement gates can be satisfied.

## Related decisions

- [ADR 0002](0002-azure-target-architecture-and-migration-boundaries.md) preserves `/mcp/v1`,
  `/mcp/tools`, and `/mcp/call` until a separate compatibility decision. This ADR supplies that
  decision while leaving deployment and production cutover plan-first.
- [ADR 0004](0004-separate-provider-identities-and-minimize-profile-retention.md) governs provider
  identity, retained profile data, and the remaining Search-related OAuth scope boundary.
- [ADR 0005](0005-support-spotify-development-mode-as-the-common-denominator.md) selects the
  restricted Spotify surface and internal quota policy that v2 exposes safely.
- [ADR 0007](0007-keep-playlist-media-contract-track-only.md) keeps both versions track-only.
- [ADR 0008](0008-stage-retirement-of-undocumented-playlist-embed-scraping.md) separately governs
  parser retirement and the owner gate for stopping transitional embed retrieval.
- [ADR 0009](0009-use-soundcharts-as-the-default-audio-features-provider.md) governs the default
  Audio Features provider independently of public-contract versioning.
