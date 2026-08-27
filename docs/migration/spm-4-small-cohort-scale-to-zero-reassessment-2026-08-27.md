# SPM-4 small-cohort and scale-to-zero reassessment - 2026-08-27

This dated note rechecks the proposed ADR 0002 target for an initial cohort of 1-5 people and the
YAGNI principle. It focuses on whether the API and collector need warm replicas, then rechecks the
rest of the proposal for fixed cost or operating complexity that is not justified at that scale.

This is plan-only evidence. It does not amend or accept ADR 0002, authorize implementation, apply
Azure resources, access production or credentials, or change Linear cycle scope. Official sources
were retrieved on 2026-08-27 UTC. Azure behavior, availability, and prices must be refreshed before
an apply.

Owner evidence: on 2026-08-27 UTC the owner selected compute Option A (scheduled collector plus
scale-to-zero API) and PostgreSQL-networking Option A (private VNet integration). The owner also
approved the neutral organization-shared ACR and delegated responsibility for its repository
implementation and cross-repository Linear ticketing. These approvals do not authorize Azure apply
or production mutation.

## Owner-approved revision

Change the proposed compute target before accepting ADR 0002:

1. Replace the continuously warm collector Container App with one **scheduled Azure Container Apps
   Job**. Run one finite cycle every ten minutes, with `parallelism: 1` and
   `replicaCompletionCount: 1`. Keep the current ten-minute product cadence initially.
2. Start the HTTP API/MCP Container App at **`minReplicas: 0`, `maxReplicas: 1`**, using the HTTP
   scaler. A request wakes it; the normal five-minute scale-down stabilization avoids churning
   during a short session. Make `minReplicas: 1` a measured, one-line Bicep fallback rather than a
   default expense.
3. Do not add a queue, Event Grid, Service Bus, an event-driven collector, or an application
   permission to invoke Azure Resource Manager initially. The scheduled job also picks up a ZIP
   import within at most about ten minutes. Add a `Run now` path only after an observed need.
4. Use **SWA Free**, the approved organization-shared ACR, lean monitoring, and no persistent
   non-production stack. Build a disposable non-production environment for rehearsals and remove
   it afterward.
5. Use PostgreSQL Flexible Server **private VNet integration**
   instead of public-mode PostgreSQL plus a paid PostgreSQL Private Endpoint, provided the
   migration and operator-access rehearsal succeeds entirely through Azure-side jobs. This keeps
   the database off the public internet while removing about $7.30/month of fixed Private Endpoint
   cost. Keep the Blob Private Endpoint unless a separately proven, network-restricted alternative
   preserves the raw-export privacy boundary.

This is a better fit than the warm proposal. Warm compute was conservative while the target client,
SSE, and job behavior was still unresolved; it is not justified as the starting assumption for a
personal-and-friends system. The fallback remains cheap and reversible if real cold-start evidence
is poor.

## What the current code actually requires

### Collector

The collector is periodic business logic packaged as a daemon:

- `services/collector/src/collector/settings.py:20` sets a 600-second interval.
- `services/collector/src/collector/runloop.py:45-54` runs one cycle, then sleeps one second at a
  time until the interval expires.
- A cycle drains pending ZIP imports, processes active users, enriches audio features, and resolves
  local tracks. There is no continuously consumed queue or inbound server contract.
- ZIP jobs are atomically changed from `PENDING` to `PROCESSING`, but the whole collector cycle has
  no execution-wide lease. A scheduled execution can therefore overlap a previous execution unless
  the application adds a database-backed singleton guard.

The daemon lifetime is an implementation convenience, not a product requirement. Azure describes
Container Apps Jobs as finite tasks that start, run, and stop, and explicitly names scheduled batch
processing as a Job scenario. Scheduled Jobs use five-field UTC cron expressions; `*/10 * * * *`
preserves the existing cadence.

The current image cannot simply be pointed at a Job. Before release it needs a finite entry point
that executes one cycle and exits, plus the following correctness controls:

- acquire a PostgreSQL advisory lock or durable lease for the entire execution; exit successfully
  without work when another execution owns it;
- give claims a lease/heartbeat and reconcile abandoned `PROCESSING` imports after timeout;
- preserve the existing per-job checkpoints and idempotent upserts;
- return a non-zero process result for execution-level failures instead of swallowing every phase
  exception and appearing successful to Azure;
- handle SIGTERM within the configured replica timeout, close database resources, and leave work in
  a deterministically retryable state;
- pressure-test the maximum 500-MiB streaming ZIP and initial sync before setting the final replica
  timeout; and
- alert on failed, timed-out, skipped-overlap, and stale-lease executions.

Use `0.5 vCPU / 1 GiB` as the initial test size because the accepted 500-MiB path needs useful
ephemeral-space headroom. Use `replicaRetryLimit: 0` until crash recovery and claim leasing are
proven; the next scheduled execution is the simple retry mechanism. A one-hour timeout is a
candidate, not an accepted limit, and must be replaced by the pressure-test result.

### API and MCP

The API is a legitimate continuously addressable HTTP service, but that does not require one
continuously running replica:

- Azure's HTTP scaler supports `minReplicas: 0`; a new request starts a replica, and no usage charge
  applies while it is at zero.
- The MCP adapter is configured with `stateless_http=True` and `json_response=True`
  (`services/api/src/app/mcp/mcp_server.py:120-121`). Durable application state and the fallback
  cache are in PostgreSQL.
- Database connections default to `NullPool`, so a stopped replica does not retain a required
  connection pool (`services/shared/src/shared/config/database.py:12-14`).
- The API does retain process-local state: its rate limiter and short settings cache reset on a
  cold start, and the FastMCP session manager exists for the process lifespan. Starting at one
  maximum replica avoids cross-replica divergence, but SPM-6 must still prove lifecycle behavior.

Scale-to-zero adds a real cold start. Microsoft describes the work as image pull, resource
provisioning, and application startup, and publishes mitigation guidance rather than a guaranteed
duration. The first request might be an MCP initialization, a tool call, a browser API request, a
Google OAuth callback, or a large upload. All must be tested from Israel against the immutable
production-shaped image.

An active long-lived HTTP/SSE request should keep a replica active through the HTTP concurrency
signal, but that is not proof of the required MCP behavior. Container Apps still documents a
240-second HTTP ingress request timeout. SPM-6 must exercise direct ACA Streamable HTTP/SSE,
reconnect, revision change, idle notification, and error behavior in real ChatGPT and Claude
clients.

Start at `minReplicas: 0`, `maxReplicas: 1`, 0.5 vCPU/1 GiB, and HTTP concurrency 10 as a test
candidate. Release with zero only if all of the following pass:

- at least 30 cold starts of the immutable image in Israel Central, with startup/readiness probes,
  no failures, and recorded request-to-ready and request-to-first-byte percentiles;
- real ChatGPT and Claude MCP initialize/list/call/reconnect tests pass from zero, including the
  optional notification/SSE cases owned by SPM-6;
- Google login and callback, application JWT/API-token paths, and logout pass from zero;
- a maximum-size upload does not violate the 240-second ingress contract and remains safely
  resumable or retryable;
- the process flushes redacted logs and releases resources on scale-down; and
- p95 first-byte cold-start delay is at most five seconds, no observed cold start exceeds ten
  seconds, and no client/provider timeout is approached.

If any compatibility test fails, or the latency target proves annoying in actual use, change only
the API minimum to one. That is an operational fallback, not an architecture rewrite.

## Collector trigger options

| Option | Benefits | Costs and risks | Position |
|---|---|---|---|
| Warm collector Container App | Closest to today's daemon; no finite-entry-point change. | Pays for idle memory and CPU, hides execution success/failure inside a process, and preserves a daemon only because one already exists. | Reject for the 1-5-user start. |
| Scheduled Container Apps Job every ten minutes | Matches the actual periodic workload, has bounded executions and execution history, costs nothing between runs, and preserves current freshness without another Azure service. | Needs a finite entry point, global lease, abandoned-claim recovery, failure exit semantics, and overlap tests. Upload processing can wait up to one interval. | **Selected.** |
| Event-driven/manual Job on every upload plus a separate polling schedule | Near-immediate imports and discrete executions. | Adds a queue or Azure management-plane invocation, permissions, retry semantics, and two trigger paths for a once-per-user action. | Defer until a measured need. |
| One event-driven queue for all collector work | Can avoid empty scheduled starts and scale exactly to backlog. | Spotify history polling still needs a clock; queue production, poison handling, deduplication, and observability are new product machinery. | Reject initially under YAGNI. |

The only material product trade-off is import and history freshness. Ten minutes exactly preserves
the current collector interval. It is short enough that a listener cannot exceed Spotify's 50-item
recent-history response between polls under normal playback, and it avoids inventing an immediate
trigger for an upload that normally happens once per user.

## API warmth options

| Option | Benefits | Costs and risks | Position |
|---|---|---|---|
| `minReplicas: 1` | Removes cold-start delay and reduces one variable in MCP/OAuth testing. | Pays all month for a service that is usually unused; the earlier expected model attributed about $16/month of avoidable API cost to warmth. | Fallback only. |
| `minReplicas: 0`, `maxReplicas: 1` | Best fit for 1-5 intermittent users; zero idle usage charge; one replica avoids unnecessary state-distribution questions. | First request is slower; client/OAuth/upload/SSE behavior must pass from zero; no warm availability during a regional/platform start failure. | **Selected, gated by SPM-6.** |
| Time-window or synthetic pre-warming | Can make expected active hours feel warm. | Adds schedules, time-zone/DST policy, continuous synthetic traffic, and still misses unplanned use. | Defer; use only if measured cold starts are acceptable but predictable sessions need smoothing. |

## Revised Container Apps cost sensitivity

The existing cost note uses the Israel Central retail inputs of $0.000034/vCPU-second and
$0.000004/GiB-second, with subscription-wide monthly grants of 180,000 vCPU-seconds, 360,000
GiB-seconds, and two million requests. Grants might already be consumed by other applications, so
both grant-available and no-grant sensitivities matter.

Assumptions below are deliberately explicit rather than presented as measurements:

- API: 0.5 vCPU/1 GiB, active for either 10 or 50 hours/month, zero otherwise;
- collector: 0.5 vCPU/1 GiB, 4,320 scheduled executions/month, average execution duration of one
  or two minutes; and
- requests remain below two million/month.

| Sensitivity | vCPU-seconds | GiB-seconds | ACA after full grants | ACA with no grants |
|---|---:|---:|---:|---:|
| 10 API hours + one-minute collector | 147,600 | 295,200 | $0.00 | $6.20 |
| 50 API hours + one-minute collector | 219,600 | 439,200 | $1.66 | $9.22 |
| 50 API hours + two-minute collector | 349,200 | 698,400 | $7.11 | $14.67 |

A rare 30-minute 0.5-vCPU/1-GiB import execution adds $0.0378 if it falls entirely outside the
free grant. Actual startup, job, API, and import duration must replace these assumptions after 14
and 30 complete production days.

With SWA Free, no incremental registry charge for a qualifying shared ACR, lean monitoring, both
original Private Endpoints, and no persistent non-production stack, the revised production
sensitivity is approximately **$38-$53/month**. If PostgreSQL private VNet integration replaces
its $7.30/month Private Endpoint while the Blob endpoint remains, it becomes approximately
**$31-$46/month**. These are incremental app estimates before tax, support, shared-platform cost
allocation, and the one-time DigitalOcean overlap. A practical initial forecast is **about
$40/month**, with a **$60/month app budget** until measurements replace assumptions.

The former about-$105 forecast was dominated by warm ACA assumptions plus Standard SWA and a new
Basic ACR. The revised target does not need any of those three fixed starting assumptions.

## Complete 1-5-user / YAGNI pass

| Proposal item | Result | Small-cohort recommendation and reason |
|---|---|---|
| Contract-first staged replacement | Keep | Contracts make partial or full replacement reversible; the discipline is valuable even for one user. |
| Partial/full rewrite permission | Keep | Do not preserve the current implementation by inertia, but do not rewrite without comparable evidence. |
| Mandatory profiling and representative Rust comparison | Keep, bounded | A small proof prevents `later` from becoming never. Compare one representative hot path and cold start; do not build a second production backend unless a dedicated ADR selects it. |
| React replacement | Keep | It is already scoped product work. Migrate route groups incrementally and retain rollback until parity. |
| Static Web Apps tier | Adjust already selected | Start on Free; rehearse and trigger Standard before quota/SLA/features require it. |
| API/MCP compute | Adjust | Start ACA at min zero/max one. Warm only after failed compatibility or measured UX evidence. |
| Collector compute | Adjust | Scheduled ACA Job every ten minutes, not a warm Container App. |
| Immediate import trigger | Defer | Scheduled pickup is adequate for a once-per-user operation. Add `Run now` or an event only after demand. |
| PostgreSQL service/SKU | Keep | B1ms, P4 32 GiB, no HA, and 14-day PITR fit gradual growth if CPU credits, connections, IOPS, storage, and restore time are alerted and rehearsed. |
| PostgreSQL networking | Adjust, selected | Use private VNet integration for the single VNet/single-region start; it keeps no public endpoint and avoids one paid Private Endpoint. Its creation-time rigidity and Azure-side operator path remain release gates. |
| PostgreSQL identities | Keep | Separate API DML, collector DML, and migration DDL roles are low-cost least privilege, not scale-driven complexity. Keep password auth and workload-specific Key Vault secrets initially. |
| Key Vault | Keep | There is no fixed vault fee; it is already required for application secrets. Do not add a Key Vault Private Endpoint initially. |
| Valkey/managed Redis | Defer | Keep the PostgreSQL cache fallback until measured load proves a separate cache necessary. |
| ZIP handoff | Keep | A scaled-to-zero API cannot retain a local file for a later Job. Blob is the durable seam between independent lifecycles. |
| ZIP retention | Keep | Delete immediately after every terminal state; no archive, versions, soft delete, or backup. |
| Blob redundancy | Keep | Retain Hot ZRS. Moving to LRS would save negligible transient-capacity cost without simplifying the application or deletion contract. |
| Blob network boundary | Keep | Raw Spotify exports are the most sensitive transient object. Keep managed identity, no Shared Key/anonymous access, and private Blob access until a cheaper network-restricted path is proven in ACA. |
| ACR | Adjust already selected | Reference one neutral organization-owned registry; Spotify owns only its repositories/digests and must not own or delete the shared registry lifecycle. |
| Region | Keep | Israel Central remains the latency-first primary; France Central remains only an unprovisioned contingency. |
| Front Door | Defer | Separate SWA/ACA hostnames and managed certificates avoid about $35-$37/month and preserve the direct SSE test path. |
| Caddy | Retire at cutover | ACA/SWA managed ingress replaces it only after route/header/TLS/auth/MCP parity. Do not migrate certificate state. |
| Google authentication | Keep lean | Allowlist/account-link, re-login, and the accepted trusted-header-to-JWT seam are enough. Defer invitations, groups, multiple providers, and session migration. |
| Public REST/MCP contracts | Keep | Preserve `/mcp/v1`, `/mcp/tools`, `/mcp/call`, REST schemas, and auth until dedicated ADRs decide otherwise. |
| MCP SSE/notifications | Keep optional, gate | Direct ACA avoids Front Door's SSE exclusion, but real ChatGPT/Claude and the 240-second timeout still require SPM-6 evidence. |
| Direct package-scoped `uv.lock` | Keep | One dependency authority and immutable builds prevent drift; the strict root build-context denylist remains required. |
| Bicep | Keep | It matches the Azure-only target and the closer ACA precedent. Do not add Terraform state solely for this small application. |
| Observability | Simplify | Keep platform metrics and redacted logs for 30 days; begin around 1 GB/month, two or three high-value alerts, hourly public health, daily deeper auth/MCP checks, and Job failure/staleness alerts. Keep traces off. |
| Persistent non-production | Remove | Use disposable, synthetic-data Azure rehearsals created from Bicep. A stopped persistent copy had about a $20.85/month floor and is not justified for 1-5 users. |
| Budget | Adjust | Replace the $130 combined envelope with a $60 app-level budget, retaining 80%, 100%, 120%, and anomaly notifications. Reprice after 14/30 days. |
| Forward recovery after first Azure write | Keep | Data correctness does not become less important with fewer users. Do not invent reverse synchronization. |
| Seven-day DigitalOcean soak | Keep | It is a bounded, one-time safety cost of about $24.85 at the measured $108/month baseline, not permanent overengineering. |
| DigitalOcean deletion authority | Keep separate | No merge, deploy, or successful soak authorizes destructive retirement. |
| France/HA/Redis/traces/WAF/NAT/firewall | Defer | None belongs in the starting system without a measured reliability, performance, security, or policy trigger. |

## ADR changes recorded after owner approval

The root amended the ADR 0002 package to:

- replace every `continuous collector` / `minReplicas: 1` statement with the scheduled finite Job
  contract and its overlap, lease, timeout, retry, and failure gates;
- set the API proposal to `minReplicas: 0`, `maxReplicas: 1`, with the explicit SPM-6 cold-start
  gate and warm fallback;
- record SWA Free and the neutral organization-shared ACR;
- remove the persistent non-production cost assumption;
- replace the cost table and budget with the measured sensitivity above;
- select PostgreSQL private VNet integration; and
- retain Blob Hot ZRS because changing redundancy saves negligible cost and does not remove
  application complexity.

After those choices became explicit, Yuval Moran accepted ADR 0002 with "Decision 4 A" on
2026-08-27 UTC. Repository gates and independent Standards/Spec review remain required before
delivery.

## Primary sources

- [Scaling in Azure Container Apps](https://learn.microsoft.com/en-us/azure/container-apps/scale-app)
- [Reducing cold-start time on Azure Container Apps](https://learn.microsoft.com/en-us/azure/container-apps/cold-start)
- [Jobs in Azure Container Apps](https://learn.microsoft.com/en-us/azure/container-apps/jobs)
- [Container Apps ingress](https://learn.microsoft.com/en-us/azure/container-apps/ingress-overview)
- [Container Apps pricing](https://azure.microsoft.com/en-us/pricing/details/container-apps/)
- [Container Apps health probes](https://learn.microsoft.com/en-us/azure/container-apps/health-probes)
- [PostgreSQL Flexible Server private VNet integration](https://learn.microsoft.com/en-us/azure/postgresql/network/concepts-networking-private)
- [PostgreSQL Flexible Server Private Link](https://learn.microsoft.com/en-us/azure/postgresql/network/concepts-networking-private-link)
- [Networking in a Container Apps environment](https://learn.microsoft.com/en-us/azure/container-apps/networking)

**STOP 1:** local-ready architectural reassessment with the selected inputs reflected in ADR 0002.
The later owner acceptance is recorded in the ADR; this evidence note does not authorize Azure
mutation.
