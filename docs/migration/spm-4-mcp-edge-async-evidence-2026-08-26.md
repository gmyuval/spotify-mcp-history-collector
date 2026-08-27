# SPM-4 MCP edge and asynchronous-work evidence - 2026-08-26 UTC

This dated note supports the remaining SPM-4 public-edge decision. It evaluates whether a real,
planned product feature requires Server-Sent Events (SSE), and whether ordinary asynchronous job
tools are portable across ChatGPT and Claude. It does not accept or amend ADR 0002, change the
public MCP/API contract, or authorize Azure, production, credential, OAuth, or account access.

Evidence labels:

- **Measured** - observed at repository revision
  `271b009cf3cb837f95dacab9d6db8d477b7da3ce`, in live Linear on 2026-08-26 UTC, or in the linked
  first-party documentation.
- **Inferred** - a design conclusion from measured evidence that still needs the named SPM-6
  client test.
- **Unresolved** - not documented or not tested and therefore unavailable as compatibility
  evidence.

## Conclusion

- **Measured:** no committed near-term feature in the repository or live Linear backlog requires
  SSE. The plausible candidates need durable background work, status retrieval, or browser upload
  progress; none needs an unsolicited MCP server-to-client event stream.
- **Measured:** MCP 2026-07-28 Streamable HTTP can return a JSON object or a request-scoped SSE
  response. Request progress notifications flow only on that SSE response, while long-lived
  change notifications use an SSE response to `subscriptions/listen`. Tasks use ordinary
  `tasks/get` polling by default, but their optional `notifications/tasks` push path also uses
  `subscriptions/listen`. Front Door's explicit no-SSE rule therefore closes standards-defined
  MCP progress and task-notification paths; its WebSocket support does not substitute for them.
  [MCP Streamable HTTP](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http),
  [MCP Tasks](https://modelcontextprotocol.io/extensions/tasks/overview),
  [Front Door WebSocket/SSE behavior](https://learn.microsoft.com/en-us/azure/frontdoor/standard-premium/websocket)
- **Inferred:** a single-hostname Front Door topology remains functionally viable only as a
  polling-first subset: ordinary JSON tool calls, durable application jobs, and `tasks/get` can
  work, but future standards-defined MCP notification optionality would require another public
  hostname or an SSE-capable edge. Each HTTP call must remain bounded below the 240-second ceiling.
  [Front Door origin timeout](https://learn.microsoft.com/en-us/azure/frontdoor/how-to-configure-origin)
- **Measured:** both ChatGPT and Claude support ordinary MCP tools and later tool calls. ChatGPT's
  own guidance says to return stable identifiers that later tools can reuse, and its test guidance
  explicitly includes follow-up requests using earlier identifiers. Claude documents MCP tool use
  and multi-step work. [OpenAI MCP server guidance](https://developers.openai.com/plugins/build/mcp-server),
  [OpenAI ChatGPT test guidance](https://developers.openai.com/plugins/deploy/connect-chatgpt),
  [Claude remote connectors](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)
- **Unresolved:** neither vendor documents that its hosted client will keep a conversation awake,
  autonomously poll indefinitely, or preserve a job identifier across every reconnect. Correctness
  must not depend on that behavior.
- **Measured:** native MCP Tasks is not a portable current client baseline. The 2026-07-28
  extension requires explicit client and server opt-in; polling is the default, while optional
  task notifications are delivered through `subscriptions/listen`.
  Claude says its hosted connector supports tools, prompts, and resources while advanced/draft
  capabilities are not yet supported, and its API MCP connector says only tool calls are currently
  supported. The complete current OpenAI plugin documentation contains no `tasks/get`,
  `io.modelcontextprotocol/tasks`, or MCP Tasks support claim. Treat absence as an undocumented
  capability, not proof that a particular build can never negotiate it.
  [MCP Tasks](https://modelcontextprotocol.io/extensions/tasks/overview),
  [Claude connector capabilities](https://claude.com/docs/connectors/building),
  [Claude Platform MCP connector](https://platform.claude.com/docs/en/agents-and-tools/mcp-connector),
  [OpenAI complete plugin documentation](https://developers.openai.com/plugins/llms-full.txt)

## Actual near-term feature pressure

Live Linear items below were in `Backlog` on 2026-08-26 UTC. They are desired planned work, not
implemented commitments or authority to change their public contracts.

| Planned or current behavior | What could appear to need SSE | Evidence-based fit |
|---|---|---|
| Current MCP surface | Streaming is a generic MCP capability. | The server sets `stateless_http=True` and `json_response=True` in `services/api/src/app/mcp/mcp_server.py`, mounts it at `/mcp/v1`, and returns one JSON result per useful call. No current tool exposes useful server-push behavior. |
| Existing ZIP import, initial sync, polling, and enrichment jobs | Long work and progress reporting. | `ImportJob`, `JobRun`, status endpoints, cancellation, and `ops.latest_*` tools already establish a database-backed status/poll pattern. Import progress granularity needs improvement, but no held connection is required. |
| [SPM-12 - React admin](https://linear.app/stratex/issue/SPM-12/migrate-the-admin-dashboard-to-react) | Upload and ingestion progress. | Upload-byte progress belongs to the browser upload request. Post-upload ingestion is a durable job and can use bounded query polling/refetch; the ticket already requires cache invalidation/refetch and cancellation. SSE would be an optional UX enhancement, not a requirement. |
| [SPM-14 - Now Playing](https://linear.app/stratex/issue/SPM-14/expose-now-playing-playback-state-devices-and-queue) | Live playback ticks and state changes. | The ticket explicitly requires demand-driven reads or a bounded cache and prohibits quota-wasting background polling. An SSE connection cannot create fresher Spotify data without the server polling upstream, so it conflicts with the stated quota posture rather than solving it. |
| [SPM-16 - calculated taste profile](https://linear.app/stratex/issue/SPM-16/build-a-deterministic-provenance-aware-calculated-taste-profile) | Long recalculation with progress. | A resumable, idempotent background job with durable status/result is the natural fit. There is no planned interactive partial-result experience. |
| [SPM-17 - exact playlist plan/preview/apply](https://linear.app/stratex/issue/SPM-17/build-a-safe-plan-preview-apply-workflow-for-exact-playlists) | Resolution, ranking, batched writes, approval, and partial failures. | Separate preview and explicitly approved apply operations already create a durable workflow boundary. Bounded batches plus a job handle preserve idempotency and recovery better than one streamed call. |
| [SPM-18 - enrichment operations](https://linear.app/stratex/issue/SPM-18/operationalize-soundcharts-and-musicbrainz-enrichment) | Resumable refresh/backfill under provider limits. | This is the strongest async-job candidate: the ticket explicitly calls for resumable, bounded controls. Pollable persisted state is preferable to keeping an assistant connection open across rate-limited work. |

The only foreseeable near-term product SSE benefits are smoother admin completion notifications
and a live-looking Now Playing UI. Neither is specified as push-driven, and both have simpler
bounded polling designs. That product observation is not the whole edge decision: the current MCP
standard already defines request-scoped progress and optional task/change notifications over SSE,
so preserving protocol optionality can be valuable before a concrete product feature commits to
it.

The 2026-07-28 revision deprecates the old standalone HTTP+SSE transport, not SSE framing inside
modern Streamable HTTP. Every MCP request is an HTTP POST; its response may be JSON or a
request-scoped SSE stream, and `subscriptions/listen` is a long-lived POST whose response is SSE.
That distinction is decisive for edge compatibility.
[MCP 2026-07-28 release](https://blog.modelcontextprotocol.io/posts/2026-07-28/),
[MCP Streamable HTTP](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http),
[MCP subscriptions](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/subscriptions)

## Portable asynchronous tool contract

Use ordinary tools for the compatibility baseline; do not require native MCP Tasks:

```text
<domain>.start_<operation>(..., idempotency_key)
  -> {job_id, state, accepted_at, poll_after_seconds, expires_at}

ops.get_job(job_id)
  -> {state, progress?, status_message?, poll_after_seconds?, terminal_summary?}

ops.wait_job(job_id, max_wait_seconds <= 30)
  -> same status shape, returning on state change or at the bound

ops.get_job_result(job_id, cursor?)
  -> bounded/paginated terminal result

ops.cancel_job(job_id)
  -> idempotent cooperative cancellation outcome
```

Required properties:

- `job_id` is stable, opaque, scoped to the authenticated principal, and survives process/revision
  changes for the documented result TTL. It is not a client-supplied internal user/account ID.
- `start` durably records the job before returning and is idempotent across a lost response and
  retry. The response target is seconds, not minutes.
- `get` and `result` are fast, read-only calls. `wait` is an optional bounded long-poll, not SSE,
  and stays far below the selected edge's 240-second ceiling.
- Clients receive a server-selected `poll_after_seconds`; rate limiting prevents hot polling.
- Results are bounded. Large exports or evidence sets use pagination or a scoped expiring artifact,
  not an unbounded MCP result. Claude currently documents about 150,000 characters for hosted
  Claude.ai/Desktop results and a configurable 25,000-token Claude Code limit.
  [Claude connector limits](https://claude.com/docs/connectors/building)
- Cancellation is cooperative and accurately annotated as a write action. Retrying cancel and
  cancelling an already-terminal job return stable outcomes.
- User confirmation occurs before a mutating job starts unless a separately accepted interaction
  design explicitly owns an `input_required` state.

This contract is compatible with both clients because each operation is an ordinary MCP tool and
the durable handle is model-visible. OpenAI explicitly supports structured tool results and stable
identifiers for later calls. Claude's documented tool loop feeds a result back to the model so it
can select another tool. The conclusion is still **inferred** for unattended repeated polling in
the hosted UIs; the older Tasks design analysis itself notes that agent-driven polling can be
expensive and inconsistent. [OpenAI result guidance](https://developers.openai.com/plugins/build/mcp-server),
[Claude tool loop](https://platform.claude.com/docs/en/agents-and-tools/tool-use/how-tool-use-works),
[MCP Tasks design history](https://modelcontextprotocol.io/seps/1686-tasks)

Native `io.modelcontextprotocol/tasks` may later become an optional optimized mode only when the
exact client advertises the extension and SPM-6 proves its behavior. The ordinary tools remain the
fallback. Default `tasks/get` polling does not require SSE. Optional `notifications/tasks` does:
the client receives it on an SSE `subscriptions/listen` response. Request-scoped
`notifications/progress` likewise requires the originating request's SSE response.
[MCP Tasks](https://modelcontextprotocol.io/extensions/tasks/overview),
[MCP Streamable HTTP](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)

## SPM-6 validation scenarios

[SPM-6](https://linear.app/stratex/issue/SPM-6/harden-the-remote-mcp-surface-for-cross-client-conformance)
should add these exact scenarios to its existing Inspector, Claude, and OpenAI compatibility work:

1. Through each candidate edge, connect ChatGPT, OpenAI Responses remote MCP, Claude.ai or Desktop,
   Claude Code, and the Claude Messages MCP connector using Streamable HTTP; record negotiated
   versions and advertised capabilities. Distinguish JSON responses, request-scoped SSE, and the
   2026-07-28 POST `subscriptions/listen` SSE response from the deprecated standalone GET stream.
2. Verify identical `start/get/wait/result/cancel` schemas, annotations, redaction, and auth
   behavior across clients. Do not expose internal `user_id` or the still-decision-blocked
   `account_id` shape.
3. Run a synthetic 10-30 second job from the prompt "start and wait". Record whether each client
   performs `start -> wait/get -> result` in one conversation and its actual call cadence.
4. Run work longer than 240 seconds. Prove `start` returns quickly, no request approaches the edge
   timeout, and a later user follow-up can reuse the exact `job_id` to retrieve the result.
5. Start a job, disconnect/restart the client, then retrieve status/result by `job_id`. Verify a
   typed expired outcome after TTL.
6. Lose the network response after durable acceptance, retry `start` with the same idempotency key,
   and prove that only one job exists.
7. Exercise success, failure, cooperative cancellation, repeated cancellation,
   cancel-after-terminal, malformed/unknown IDs, and partial-result recovery.
8. Verify poll pacing and bounded waits: no busy loop, server hints are respected sufficiently,
   and a client that stops polling produces a truthful "still running; check later" response.
9. Change or expire OAuth between start and poll, and prove another principal cannot read or cancel
   the job.
10. Exercise result-size limits and pagination/artifact expiry without truncation or sensitive-data
    leakage.
11. Probe native Tasks capability explicitly. Lack of advertised
    `io.modelcontextprotocol/tasks` must select ordinary tools rather than fail the workflow.
12. Repeat the suite after ChatGPT metadata refresh/published-plugin updates and material Claude
    client changes; record a compatibility matrix from observed calls, not prose assumptions.

## A-versus-C realtime and reversibility addendum - 2026-08-26 UTC

This follow-up uses **A** for separate `app.<domain>` Static Web Apps and `api.<domain>` Container
Apps hostnames, and **C** for one public hostname with Front Door path-routing to those same
origins. Front Door routes public HTTP path patterns such as `/api/*`, `/mcp/*`, and
`/oauth2/*`; these are application URL paths, not raw container filesystem paths. Front Door
matches the most-specific host and path rule and associates the route with an origin group.
[Front Door route matching](https://learn.microsoft.com/en-us/azure/frontdoor/front-door-route-matching)

### Measured

- **Browser WebSocket:** both options preserve it. Container Apps HTTP ingress explicitly
  supports WebSocket. Front Door Standard also supports WebSocket, but closes a connection after
  five idle minutes or two total hours, applies WAF inspection only during the handshake, and
  requires caching to be disabled on the route. A browser feature therefore needs heartbeat and
  reconnect behavior under C, but C does not remove browser realtime capability.
  [Container Apps ingress](https://learn.microsoft.com/en-us/azure/container-apps/ingress-overview),
  [Front Door WebSocket behavior](https://learn.microsoft.com/en-us/azure/frontdoor/standard-premium/websocket)
- **Browser SSE:** C cannot carry it because Front Door explicitly does not support SSE. A avoids
  that Front Door prohibition, but Microsoft does not explicitly list SSE as a Container Apps
  ingress capability and documents a 240-second HTTP request timeout. A therefore preserves only
  a *candidate* direct-SSE path, not evidence for an indefinitely held stream. The browser
  `EventSource` standard does define automatic reconnection and `Last-Event-ID`, so a bounded,
  resumable stream is possible in principle.
  [Container Apps ingress](https://learn.microsoft.com/en-us/azure/container-apps/ingress-overview),
  [Front Door WebSocket/SSE behavior](https://learn.microsoft.com/en-us/azure/frontdoor/standard-premium/websocket),
  [WHATWG EventSource](https://html.spec.whatwg.org/multipage/server-sent-events.html)
- **MCP progress and Tasks notifications:** neither topology can make ChatGPT or Claude *display*
  them, but the topology determines whether the standards-defined messages can arrive. In MCP
  2026-07-28, `notifications/progress` is request-scoped and travels on the request's SSE response;
  optional `notifications/tasks` travels on an SSE `subscriptions/listen` response. C blocks both
  paths at Front Door. A leaves them technically reachable subject to the ACA timeout/reconnect
  proof. The vendor evidence above establishes ordinary tool calls and stable-ID follow-ups, but
  neither hosted-client guide promises user-visible progress, `subscriptions/listen`, or native
  Tasks support today.
  [MCP progress](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/progress),
  [MCP Streamable HTTP](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http),
  [MCP Tasks](https://modelcontextprotocol.io/extensions/tasks/overview),
  [OpenAI MCP server guidance](https://developers.openai.com/plugins/build/mcp-server),
  [Claude connector limitations](https://platform.claude.com/docs/en/agents-and-tools/mcp-connector)
- **App-owned UI independence:** the React application can use its own `EventSource` or WebSocket
  endpoint without making that transport part of the ChatGPT/Claude MCP contract. Under A it can
  connect to the direct ACA hostname; under C it can use a same-host WebSocket route through Front
  Door. Browser WebSocket preserves app-owned realtime under C but cannot carry the standards-
  defined MCP Streamable HTTP SSE responses, so it does not restore MCP notification optionality.
  Ordinary JSON calls and durable job polling remain the portable assistant baseline.
  [WHATWG EventSource](https://html.spec.whatwg.org/multipage/server-sent-events.html),
  [WHATWG WebSockets](https://websockets.spec.whatwg.org/)

### Security and operational differences

**A - separate origins**

- The browser and API are cross-origin. Container Apps documents that browsers block a different
  origin by default and exposes explicit allowed-origin, method, header, exposed-header, max-age,
  and credential settings. Credentialed CORS needs explicit opt-in and careful origin handling.
  This repository already has `CORS_ALLOWED_ORIGINS` and credentialed `CORSMiddleware`, so A adds
  production policy, negative tests, and configuration discipline rather than a new application
  mechanism.
  [Container Apps CORS](https://learn.microsoft.com/en-us/azure/container-apps/cors),
  [WHATWG Fetch CORS](https://fetch.spec.whatwg.org/#http-new-header-syntax)
- Google must register the exact `https://api.<domain>/oauth2/callback` value; a later hostname
  change needs an overlap/cutover in the provider configuration. Current repository configuration
  pins `/oauth2/callback`, `SameSite=Lax`, secure HTTP-only cookies, and explicit cookie-domain
  controls, so SPM-6 must prove the selected API host, cookie scope, refresh path, CORS credentials,
  state/nonce, and CSRF behavior together.
  [Google redirect-URI validation](https://developers.google.com/identity/protocols/oauth2/web-server#uri-validation)
- Because the browser and hosted MCP clients reach ACA directly, the API origin remains publicly
  addressable and cannot be allowlisted to only the SWA service. Application authentication,
  authorization, rate limits, and exact origin validation remain the primary controls. ACA can
  enforce IPv4 ingress allow/deny rules where caller ranges are actually known.
  [Container Apps IP restrictions](https://learn.microsoft.com/en-us/azure/container-apps/ip-restrictions)
- Two managed hostnames and certificates are a small additional inventory item; the material cost
  is duplicated origin/auth policy and a second public surface, not certificate issuance itself.
  ACA supports custom domains with managed or uploaded certificates.
  [Container Apps domains and certificates](https://learn.microsoft.com/en-us/azure/container-apps/custom-domains-certificates)

**C - one public Front Door hostname**

- Browser API calls and callbacks remain on one origin, removing production CORS from the normal
  browser path and concentrating the public route, certificate, WAF, and callback policy. The cost
  is an exact public-path inventory, explicit no-cache treatment for authenticated routes, and an
  additional shared edge dependency. Microsoft's SWA integration guide calls out disabling auth
  caching and restricting the generated SWA hostname to the chosen Front Door instance.
  [SWA with Front Door](https://learn.microsoft.com/en-us/azure/static-web-apps/front-door-manual)
- The ACA origin still needs bypass protection. Microsoft recommends combining Front Door backend
  address filtering with validation of the profile-specific `X-Azure-FDID` value because address
  filtering alone also admits other Front Door customers. SPM-6 must prove the concrete
  ACA-compatible rules, header validation, forwarded host/protocol handling, and rejection of a
  direct origin request.
  [Front Door origin security](https://learn.microsoft.com/en-us/azure/frontdoor/origin-security)

### Inferred and unresolved

- **Inferred:** A materially preserves more than browser transport choice. It preserves a testable
  path for the current standard's request-scoped progress and optional task/change notifications.
  C preserves app-owned browser realtime through WebSocket and MCP correctness through polling,
  but it deliberately removes that MCP notification optionality.
- **Inferred:** A is reversible without moving either workload. Front Door can be added later in
  front of an existing SWA origin, while path routes can send the API/MCP/auth prefixes to a
  separate ACA origin. A staged change would add an alternate Front Door hostname, prove routes
  and callbacks, move DNS, then restrict the old origins. The migration cost is auth, cookie,
  callback, cache, and route revalidation, not a service rewrite.
  [SWA with Front Door](https://learn.microsoft.com/en-us/azure/static-web-apps/front-door-manual),
  [Front Door routes](https://learn.microsoft.com/en-us/azure/frontdoor/create-front-door-portal)
- **Inferred:** C also has a narrow escape hatch for an app-owned browser stream: prefer WebSocket
  through Front Door, or add a dedicated `events.<domain>` direct-ACA route for SSE. That event
  host does not restore standard MCP notifications unless the MCP endpoint itself also moves to an
  SSE-capable hostname, which reintroduces the separate public MCP origin that C was meant to avoid.
- **Unresolved:** direct ACA SSE framing, buffering, reconnect, authentication, load, revision
  rollover, `subscriptions/listen` re-establishment, notification loss, and exact 240-second
  behavior have not been tested. The current specification says listen streams are not resumable,
  so a dropped stream needs re-listen plus authoritative task polling. Neither topology has
  client-level proof that ChatGPT or Claude requests or renders protocol notifications. These
  remain SPM-6 evidence gates rather than architectural promises.
  [MCP Streamable HTTP](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http),
  [MCP subscriptions](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/subscriptions)

Additional SPM-6 scenarios:

13. From the deployed UI origin, prove credentialed preflight and actual requests for every
    browser API method under A; reject unlisted, malformed, and `null` origins. Prove that C's
    normal browser routes require no CORS exception.
14. For each topology, complete Google and Spotify callbacks and JWT refresh/logout with exact
    forwarded host/protocol, state/nonce, cookie host/domain/path, `Secure`, `HttpOnly`, and
    `SameSite` evidence.
15. Exercise an app-owned WebSocket through Front Door across more than five idle minutes using
    the selected heartbeat, across forced disconnect/reconnect, and across a Container Apps
    revision change. Disable route caching and prove direct-origin rejection.
16. If A retains SSE as an option, run a browser EventSource past 240 seconds with event IDs,
    forced disconnects, credential renewal, and duplicate/loss detection. Failure removes SSE as
    established A capability; it does not affect the ordinary MCP job contract.
17. For both hosted clients, negotiate 2026-07-28 separately for request-scoped
    `notifications/progress` and Tasks `notifications/tasks` over `subscriptions/listen`. Record
    whether the client requests, accepts, ignores, displays, reconnects, or loses each path through
    direct ACA and Front Door. Correctness must still succeed through `tasks/get` or ordinary
    durable job tools when no notification appears.
18. Rehearse A-to-C as configuration: shadow Front Door hostname, complete public-path inventory,
    callbacks and cookies, DNS transition, cache purge, and old-origin restriction. No cloud or
    provider mutation is authorized by this evidence note.

**Revised recommendation:** choose A for the current target. C remains simpler for browser
auth/CORS and fully supports the durable polling baseline, but it intentionally closes current
standards-defined MCP progress and task-notification paths, and restoring them later requires a
separate SSE-capable MCP hostname or a different edge. With notification optionality now a major
owner priority and Front Door's approximately `$35-37/month` low-traffic cost material, A's
manageable CORS/callback/public-origin work is the better trade. Keep polling authoritative because
ACA SSE and current ChatGPT/Claude notification behavior remain unproven, and keep the documented
A-to-C migration path if later evidence makes the single edge worth its recurring cost.

## Front Door Standard low-traffic cost

For clients served from Zone 7 (Middle East and Africa), the current public PAYG meters are:

- `$35/month` base fee for each Standard profile, billed until the profile is deleted;
- `$0.11/GB` from the Front Door edge to the client for the first 10 TB;
- `$0.06/GB` from the Front Door edge to the Azure origin;
- `$0.0108` per 10,000 incoming requests; and
- no Front Door charge for response bytes sent from an Azure origin to Front Door.

The bill follows the edge location serving the client, not the Israel Central origin location.
Browser traffic from Israel should normally use Zone 7, while OpenAI or Anthropic MCP calls can be
metered in the zone serving their infrastructure. Front Door caching avoids edge-to-origin traffic
on a hit, and compression reduces the billed response bytes, but neither removes the base fee or
the request meter. [Front Door pricing](https://azure.microsoft.com/en-us/pricing/details/frontdoor/),
[Front Door billing](https://learn.microsoft.com/en-us/azure/frontdoor/billing)

Illustrative monthly totals, excluding tax, negotiated discounts, diagnostic-log ingestion, and
the underlying application services:

| Scenario | Requests | Edge to origin | Edge to client | Front Door total |
|---|---:|---:|---:|---:|
| Likely light use | 100,000 | 1 GB | 10 GB | **$36.27** |
| Conservative 10 GB each direction | 100,000 | 10 GB | 10 GB | **$36.81** |
| Same data, 1 million requests | 1,000,000 | 10 GB | 10 GB | **$37.78** |
| Same data, 10 million requests | 10,000,000 | 10 GB | 10 GB | **$47.50** |

At this application's expected scale, the `$35` base fee dominates. Edge-to-client traffic alone
would need to reach about 318 GB/month, or request volume about 32.4 million/month, before either
individual variable meter equalled the base fee. A 10 GB browser ZIP upload is edge-to-origin
traffic and costs about `$0.60`; a 10 GB response/download month costs about `$1.10` in Zone 7.

Standard includes routing, caching, compression, certificate/domain management, inherent DDoS
protection, rules-engine use, and custom WAF rules without a separate feature fee. Managed WAF rule
sets and Private Link origins require Premium, whose base is `$330/month`. Premium is not justified
by current traffic or contract evidence. Selecting Standard therefore also selects a public ACA
origin protected against direct use with origin restrictions and validation of the profile-specific
`X-Azure-FDID` header; if policy later requires a fully private origin or managed WAF, the cost and
edge decision must be reopened. [Front Door security guidance](https://learn.microsoft.com/en-us/azure/frontdoor/secure-front-door),
[Front Door Private Link](https://learn.microsoft.com/en-us/azure/frontdoor/private-link)

Front Door health probes can add origin calls. With one origin, Azure permits disabling them; if
retained, use `HEAD`, a deliberately chosen interval, and a cheap health endpoint. Diagnostic logs
sent to Log Analytics are a separate ingestion/retention meter and belong in the complete Azure
cost model requested after the architecture choices are closed. [Front Door health probes](https://learn.microsoft.com/en-us/azure/frontdoor/health-probes),
[Front Door diagnostic logs](https://learn.microsoft.com/en-us/azure/frontdoor/standard-premium/how-to-logs)

## Decision implication

**Inferred recommendation:** select separate SWA and ACA hostnames. Keep JSON responses and the
portable durable-job contract as the correctness baseline, but preserve direct access to the
modern Streamable HTTP SSE forms for request progress and `subscriptions/listen`. This does not
claim current ChatGPT or Claude support, and it does not prove ACA SSE reliability; SPM-6 must test
both. It avoids paying the material Front Door base fee for a topology that would remove an owner-
valued protocol option. Retain the staged A-to-C route/callback/DNS rehearsal so a future change
remains configuration and validation work rather than a workload rewrite.

## Owner decision evidence

On 2026-08-26 UTC, after reviewing the corrected MCP 2026-07-28 transport evidence, current
ChatGPT/Claude limitations, browser realtime alternatives, Front Door cost, and the security and
operational trade-offs, Yuval Moran approved: **"A, subject to mitigation and SPM-6 gates
approved."** This selects separate Static Web Apps and Container Apps hostnames with no Front Door
in the initial target. It also binds the credentialed-CORS, callback/cookie/CSRF, public-origin,
durable-job fallback, direct-ACA SSE/reconnect, exact-client, notification-loss, and A-to-C rehearsal
gates recorded above. It does not accept ADR 0002 as a whole or authorize implementation, Azure
apply, deployment, DNS/OAuth-console mutation, credentials, production access, or public MCP/API
contract changes.
