# ADR 0002 - Choose the Azure target architecture and migration boundaries

Date: 2026-08-27 (UTC)
Status: Accepted
Decision owners: Yuval Moran
Linear issue: [SPM-4](https://linear.app/stratex/issue/SPM-4/record-the-product-and-azure-target-architecture-and-migration-boundaries)
Owner evidence: constituent choices recorded during the owner decision sessions on 2026-08-26
and 2026-08-27 UTC; Yuval Moran accepted the cohesive decision with "Decision 4 A" on
2026-08-27 UTC

## Context

The current production system is a working DigitalOcean-hosted Docker Compose deployment. Its six
containers are the API, a continuously running collector, two Python user interfaces,
`oauth2-proxy`, and Caddy. PostgreSQL is the durable system of record. The API and collector share
uploaded ZIP files by local filesystem path. Valkey is optional because the application already
has a PostgreSQL fallback. Caddy owns the current public routing, TLS termination, Google forward
authentication, and JSON access logs.

The dated, sanitized estate evidence is recorded in the
[SPM-20 live-estate baseline](../migration/spm-20-live-estate-baseline.md). At that capture the
database was about 3.39 GB with about 10.2 million rows, one retained upload was 2.6 MB, and the
recurring DigitalOcean core cost was USD 108 per month. Those measurements are evidence, not a
current production inspection or an authorization to inspect production.

The verified repository constraints, official Azure sources, dated regional inventory, and public
list-price calculations for this decision are pinned in the
[SPM-4 Azure architecture evidence](../migration/spm-4-azure-architecture-evidence-2026-08-25.md).
Service limits and prices are volatile; recheck that dated evidence before implementation.
The public-edge, current MCP transport, client async/polling, and Front Door cost evidence is
recorded separately in the
[SPM-4 MCP edge and asynchronous-work evidence](../migration/spm-4-mcp-edge-async-evidence-2026-08-26.md).
The current Google-to-application-JWT seam, Azure authentication alternatives, Static Web Apps
limits, and the approved small-cohort/YAGNI rollout are recorded in the
[SPM-4 authentication coexistence evidence](../migration/spm-4-auth-coexistence-evidence-2026-08-26.md).
The current SQLAlchemy/asyncpg/Alembic connection seam and the Key Vault password versus Entra
managed-identity comparison are recorded in the
[SPM-4 PostgreSQL identity evidence](../migration/spm-4-postgresql-identity-evidence-2026-08-26.md).
The verified LARP Bicep and live-Azure Agrisense Terraform precedents are compared in the
[SPM-4 IaC precedent evidence](../migration/spm-4-iac-precedent-evidence-2026-08-27.md). The
refreshed Israel Central retail inputs, workload scenarios, monitoring allowances, transition
overlap, and budget controls are recorded in the
[SPM-4 Azure cost estimate](../migration/spm-4-azure-cost-estimate-2026-08-27.md).
The approved small-cohort compute and networking reassessment, finite collector-job boundary,
scale-to-zero gates, and revised cost sensitivity are recorded in the
[SPM-4 small-cohort scale-to-zero reassessment](../migration/spm-4-small-cohort-scale-to-zero-reassessment-2026-08-27.md).

The product exposes FastMCP at `/mcp/v1` using stateless HTTP with JSON responses. It also retains
compatibility endpoints at `/mcp/tools` and `/mcp/call`. Azure Container Apps ingress has a
documented 240-second request timeout, so compatibility with real MCP client reconnect and session
behaviour is a gating fact, not an assumption. The collector is a continuous process, not a finite
Container Apps Job. Upload imports currently require a filesystem visible to both the API and the
collector.

The current production images are built from service-scoped contexts and service-specific
requirements files. The root uv workspace and `uv.lock` are the development dependency authority,
but the service Docker contexts do not contain them. Widening a Docker build context without a
strict root `.dockerignore` would introduce privacy, provenance, and cache risks.

This proposed record collects owner-approved constituent choices and the remaining proposed cost
posture. It grants no
Azure apply, migration execution, deployment, production, credential, DNS, OAuth-console, or
deletion authority. Each such action still requires its separately reviewed plan and authority.

## Decision drivers

- Preserve existing API, MCP, authentication, collection, and data contracts during staged
  replacement. Existing implementations are evidence and rollback assets, not components that
  must be retained at any cost.
- Keep DigitalOcean authoritative until a rehearsed, explicitly authorized cutover.
- Make application rollback independent from database and data rollback, and identify the first
  Azure write as the point after which simple traffic reversal is no longer sufficient.
- Prefer managed services where they remove undifferentiated operations without forcing a broad
  rewrite or weakening privacy and security boundaries.
- Use immutable, reproducible artifacts built from the repository's uv dependency authority.
- Separate CI planning, infrastructure apply, image publication, deployment, runtime, and database
  migration authorities.
- Keep durable data private, expose only the deliberate frontend and backend public origins, and
  preserve a no-production-data development and rehearsal path.
- Base region, availability, recovery, and cost choices on owner requirements and measured
  subscription facts rather than list-price optimism.
- Make every irreversible action, especially production cutover and DigitalOcean deletion, a
  separately authorized operation with explicit evidence and stop conditions.

## Options considered

### Compute and product shape

| Option | Benefits | Costs and risks | Rollback posture |
|---|---|---|---|
| Azure VM with Docker Compose | Lowest behavioural change; preserves Caddy, `oauth2-proxy`, shared local uploads, continuous collector, and current streaming topology. | Retains single-host failure exposure and operator-owned OS, Docker, patching, backup, and capacity work. A single VM is not zone-highly-available. | Strongest reversible landing zone when images are immutable and the managed database/data boundaries are kept separate. |
| Split workload-specific Azure Container Apps | Immutable revisions, traffic-controlled rollback, managed ingress/TLS, managed identities, HTTP scale-to-zero for the API, and finite execution history for the scheduled collector Job. | The 240-second ingress timeout, cold starts, transient upload handoff, auth/cookie/routing parity, collector overlap, lease recovery, and finite-exit semantics require proof. | Selected target. Roll back the API by immutable revision and the Job by immutable image/configuration; data rollback remains separate. A VM is not the standing fallback. |
| Hybrid managed target | React on Static Web Apps; API/MCP and collector on separate Container Apps; managed PostgreSQL and storage. Static delivery has no application-container cold start while backend workloads retain independent scaling and revisions. | Requires explicit same-origin, CORS, cookie, callback, routing, storage, and observability validation across services. | Selected product shape. Each tier can be replaced and rolled back independently behind fixed contracts. |
| In-place modernization | Keeps the Python API and collector implementation while changing packaging and infrastructure. | Risks preserving accidental coupling and postponing evidence-driven replacement indefinitely. | Permitted only as one measured implementation candidate, not the default outcome. |
| Partial rewrite | Replaces one bounded workload or route group behind the fixed contracts. | Requires dual-operation, compatibility, data, and observability discipline during coexistence. | Selected delivery method when profiling or maintainability evidence justifies replacement. |
| Full rewrite | Can simplify a workload whose existing design cannot meet the measured contract, operability, or performance target. | Highest simultaneous compatibility, migration, and rollback risk; weak evidence can turn it into an expensive reimplementation. | Explicitly permitted as a candidate, but only after profiling, a representative comparison, and a dedicated accepted language/rewrite decision. |

### Infrastructure as code

| Option | Benefits | Costs and risks |
|---|---|---|
| Terraform | Portable workflow, state-aware plan/apply semantics, and a production-exercised owner precedent. The verified Agrisense stack is live in Azure and directly covers B1ms/P4, Blob, Key Vault, ACR, private DNS, monitoring, and Azure Blob remote state. | Introduces a state bootstrap, sensitive-state access control, recovery, drift, provider-version, and force-unlock boundary. Agrisense currently uses a local/manual control plane and does not supply Spotify's required CI plan/apply separation, environment isolation, scheduled drift, state-recovery rehearsals, or ACA/SWA modules. |
| Bicep | Azure-native resource-group and subscription deployments, no separate client-state backend, deployment history, and `what-if` previews. LARP Store provides a substantive local precedent for Container Apps, ACR, PostgreSQL Flexible Server, Key Vault, observability, OIDC-separated identities, and deployment verification. | ARM incremental deployment does not delete omitted resources, Entra/OIDC bootstrap still needs imperative reconciliation, and `what-if` can miss defects or produce noise. These limitations require explicit guards, tests, and runbooks. |

Select Bicep for this Azure-only target after read-only inspection of both `larp-store` and the
live `stratexil/agrisense` Azure precedent. Terraform is a credible, production-exercised option,
not a hypothetical fallback, but LARP is closer to the selected Container Apps topology and its
preview/apply identity split is stronger than Agrisense's current local Terraform control plane.
At the initial 1-5-user scale, a separate Terraform state, recovery, provider, and drift lifecycle
is fixed operational work without a selected multi-provider benefit. Owner approval: "approved"
on 2026-08-26 UTC after reviewing both options, risks, mitigations, and downstream effects.

### Production dependency packaging

| Option | Benefits | Costs and risks |
|---|---|---|
| Direct `uv.lock` synchronization in container builds | Strongest single-source dependency model. | Current service-scoped contexts lack the root workspace files. A broader context needs a reviewed root `.dockerignore`, explicit workspace packaging, and a privacy/provenance assessment. |
| Hashed, service-scoped pip-compatible exports generated from `uv.lock` | Preserves narrow contexts while making `uv.lock` authoritative; provides a low-change transition from current images. | Generated files can drift unless CI regenerates them and fails on a diff. |

Select direct package-scoped synchronization from the root `uv.lock`. Container builds use the
repository root as context only after a strict root `.dockerignore` denies credentials, personal
data, caches, VCS metadata, local state, and unrelated artifacts. Use a multi-stage build with uv
0.12.3 pinned by immutable artifact digest and an immutable Python base image. The install step is
equivalent to `uv sync --locked --package <service> --no-dev --no-editable`; the runtime stage
receives only the resulting environment and application files. Preserve service-specific cache
layers and add CI checks for the lock, build context, and production-only dependency closure.

### Backend language selection

| Option | Benefits | Costs and risks |
|---|---|---|
| Keep or optimize Python | Reuses broad functional coverage and avoids protocol migration while SQL, connection, batching, HTTP, and cache behaviour are measured. | Can become an indefinite default if measurement and comparison are optional. |
| Targeted Rust component or collector rewrite | Can improve CPU-bound parsing, normalization, memory density, or cold-start behaviour when a profiler attributes material cost there. | Adds a toolchain and cross-language boundary; does not fix Spotify latency, rate limits, database round trips, or poor query plans. |
| Full Rust backend replacement | Offers one coherent runtime if representative evidence shows the full Python backend cannot meet the target. | Must reproduce API/MCP, authentication, jobs, schema, migration, error, and rollback semantics; it is the highest-risk comparison. |

Do not select a backend language by inertia. Before implementation chooses Python, targeted Rust,
or a full Rust replacement, run mandatory profiling for API/MCP, collector, PostgreSQL/query and
connection behaviour, and ZIP import using production-shaped synthetic or sanitized workloads.
Then implement a representative Rust proof-of-value against the same contract and workload. Record
the baseline, p50/p95/p99 latency, throughput, CPU, peak RSS, database statements, external wait,
errors/retries, build/operations burden, and semantic parity. A dedicated accepted ADR selects the
language and rewrite extent. Missing or non-comparable evidence blocks selection; it does not
silently default to Python.

### Public endpoint topology

| Option | Benefits | Costs and risks | Revisit posture |
|---|---|---|---|
| Separate Static Web Apps and Container Apps hostnames | Avoids a fixed Front Door fee; lets Static Web Apps and Container Apps own their respective managed TLS/ingress; preserves a testable path for modern Streamable HTTP request-scoped SSE progress and `subscriptions/listen` task notifications. | Adds credentialed CORS, exact callback and cookie policy, CSRF/origin validation, and a directly public authenticated Container Apps surface. Container Apps SSE behavior under its 240-second request timeout remains unproven. | Selected. Add Front Door later only through a staged route, callback, DNS, cache, origin-restriction, and MCP regression rehearsal. |
| One hostname through Azure Front Door Standard | Simplifies same-origin browser auth and centralizes path routing, edge policy, WAF controls, and origin-bypass protection. Supports browser WebSocket. | Adds an approximately USD 35-37 low-traffic monthly charge and explicitly does not support SSE, closing current standards-defined MCP progress and optional task-notification paths. A later SSE-capable MCP endpoint would reintroduce a separate hostname or require a different edge. | Rejected for the initial target; reconsider if security, single-origin auth, traffic, or operational evidence justifies the cost and protocol restriction. |

## Decision

The following owner-approved choices and cost posture define the accepted target. Implementation
remains subject to the named evidence gates and does not authorize Azure apply, deployment,
production access, cutover, or resource deletion.

### Product and compute target

1. Use contract-first staged replacement. Freeze and test externally observable API, MCP,
   authentication, collection, migration, and data semantics before replacing a workload. Partial
   and full rewrites are both allowed when the mandatory profile and comparison support them; the
   current implementation is not preserved at any cost.
2. Replace only the already-scoped Python UIs with React. Host React on Azure Static Web Apps only
   after the browser/API origin, CORS, cookie, OAuth callback, and rollback contracts are accepted
   and tested.
3. Use Azure Database for PostgreSQL Flexible Server as the durable database target. Do not add a
   managed Redis dependency initially; benchmark the existing PostgreSQL fallback first. If a
   dedicated cache later becomes necessary, evaluate Azure Managed Redis against the service
   guidance current at that later decision.
4. Store immutable application images in one neutral organization-shared Azure Container Registry.
   Spotify owns its repositories, digests, publication identity, and pull assignments, not the
   registry resource lifecycle. Pin uv, base-image digests, and application-image digests, and
   retain build provenance. Use a Spotify-owned registry only after a separately accepted
   incompatibility decision.
5. Run the API/MCP service as a public HTTP Container App beginning at `minReplicas: 0`,
   `maxReplicas: 1`. Run the collector as one private scheduled Container Apps Job every ten
   minutes with `parallelism: 1` and `replicaCompletionCount: 1`; do not keep a sleeping collector
   replica warm. Do not add a queue, event trigger, or application permission to invoke Azure
   Resource Manager initially. Failure of an MCP, cold-start, upload, authentication, worker,
   lease/recovery, quota, or regional preflight gate blocks the Azure release or changes only the
   API minimum to one through reviewed Bicep; it does not silently switch to a VM/Compose target.
6. Complete the mandatory Python profiling and representative Rust comparison before selecting the
   backend language or rewrite extent in a dedicated ADR. Infrastructure preparation may proceed
   against versioned contracts, but it must not encode Python as the permanent backend boundary.

### Target surface map

| Current deployable or durable surface | Target and boundary |
|---|---|
| FastAPI API and `/mcp/v1` | Preserve the versioned REST/MCP contract while the implementation remains Python or is replaced under the language ADR. Run as its own HTTP Container App with `minReplicas: 0`, `maxReplicas: 1` initially. Release from zero only after the SPM-6 cold-start, real-client MCP, auth, upload, graceful-shutdown, and direct-SSE gates pass; use `minReplicas: 1` as the bounded fallback. |
| Continuous collector | Preserve collection, checkpoint, job, and data semantics while adding a finite one-cycle entry point. Run a scheduled Container Apps Job every ten minutes, with one replica, an execution-wide PostgreSQL advisory lock or durable lease, abandoned-claim reconciliation, deterministic non-zero failure exits, bounded timeout, SIGTERM handling, and execution alerts. Defer event/manual triggers until observed demand justifies them. |
| Admin and Explorer Python UIs | Replace, in their own SPM-10 slices, with one strict TypeScript + React application. Keep the Python UIs available until route-by-route parity and rollback are proven. |
| React application | Prefer Static Web Apps after the origin/auth decision. Pin an immutable artifact and keep its deployment independently reversible from API and cloud cutover. |
| `oauth2-proxy` and application auth | Keep the working Caddy/`oauth2-proxy` Google flow authoritative on DigitalOcean until cutover, but do not deploy it to Azure by default. Introduce minimum viable Container Apps Google authentication gradually on a non-production Azure hostname. A narrow trusted-header bridge enforces the accepted allowlist/account link and issues the existing application JWTs; Spotify OAuth, JWT/RBAC, API-token, admin, and MCP bearer authorization remain application contracts. Build an Azure `oauth2-proxy` edge only if the native design fails a concrete gate and an amendment activates the fallback. |
| Caddy reverse proxy and ingress | Replace with Container Apps managed ingress and the accepted static-web/API edge only after exact route, header, TLS, callback, auth, health, and MCP conformance. Preserve reviewed Caddy behaviour as migration evidence; do not migrate its certificate state. |
| PostgreSQL | Move to Flexible Server through rehearsed backup/restore or logical migration selected under SPM-25/26. Keep schema and Alembic history; separate runtime DML from migration DDL. |
| Valkey | Omit initially and use the existing PostgreSQL fallback after load proof. If a dedicated cache is later required, evaluate Azure Managed Redis in a separate cost/operations slice. |
| Uploaded export ZIPs | Use dedicated Blob Hot ZRS only as a transient durable API-to-collector handoff. Keep an object while its job is pending, processing, or retryable; schedule deletion immediately after any terminal state. Use managed identities, opaque keys, SHA-256, private Blob access, and deterministic cleanup/reconciliation. Do not archive source ZIPs. |
| Caddy TLS/config volumes | Treat as replaceable configuration, not migrated business data. Re-issue certificates and preserve reviewed routing configuration through IaC or immutable deployment assets. |
| Database-backed product/admin logs | Retain initially with redaction and retention review. Add redacted structured stdout and Azure Monitor alerts without copying unrestricted PII into a second store. |
| Container images | Build once, record provenance, publish to ACR, and deploy by immutable digest. Do not rebuild during rollback. |
| Alembic migrations | Run as one explicitly invoked, monitored migration process with its own identity before application traffic is admitted. Stop on failure; do not assume an automatic downgrade. |

### Infrastructure as code

Use Bicep for separate subscription/bootstrap and environment application layers. Adapt LARP's
control-plane patterns rather than copying its product configuration or importing its deployment
authority. Keep one IaC owner for each Spotify resource lifecycle; do not mix Terraform-managed and
Bicep-managed resources in the same lifecycle.

The organization-shared ACR is an external platform dependency to Spotify's Bicep lifecycle, not a
resource created, moved, or deleted by Spotify templates. A neutral platform owner must control its
resource group, authoritative IaC, SKU, region, repository-scoped ABAC/RBAC, retention, monitoring,
cost allocation, recovery, and destructive actions. Spotify Bicep may declare only its workload
identities, permitted repository conditions, and pull references after that platform contract is
available. Cross-repository migration and eventual product-registry retirement are separately
tracked and do not authorize a cloud apply or deletion.

Pin Azure CLI, Bicep, action SHAs, resource API versions, and environment inputs. Separate owner
bootstrap, read-only pull-request preview, infrastructure apply, image push, application deploy,
runtime, and migration identities. Keep apply manual and environment-constrained. Prove that
`what-if` output cannot disclose secrets or personal data, maintain measured provider-noise and
drift baselines, and add focused end-state guards for identity/RBAC, deletion inventory, private
DNS, ACR pulls, Key Vault access, PostgreSQL role denial, migration completion, and the serving
revision. Rehearse prior-template reapplication and application/database recovery before cutover.
Resource deletion, DNS/callback changes, the first production write, and DigitalOcean retirement
retain their separate owner gates.

### Region, availability, and cost boundary

Select Israel Central as the primary region. The owner reports the system is currently used in
Israel; Azure's rendered Container Apps pricing selector and PostgreSQL Flexible Server pricing
selector both list Israel Central, and the session's interleaved regional TCP-connect probe from
Israel measured an approximately 4 ms median versus approximately 49 ms for Italy North and 53 ms
for France Central. These public and network observations do not replace a subscription preflight.

Select France Central as the documented contingency region because it combines complete target
service coverage, the verified LARP Azure precedent, and a stronger recovery posture than the marginally
lower-latency Italy North alternative. No France resources, replication, failover, or standby cost
are selected initially. Israel Central is not region-paired, and PostgreSQL Flexible Server does
not offer geo-redundant backup there. A later recovery plan must therefore define authorized
cross-region data movement rather than implying that this contingency creates automatic recovery.
Before any apply, verify provider registration, policy, quota, selected SKUs, availability-zone
capacity, Container Apps environment creation, PostgreSQL configuration, ACR, Key Vault, Storage,
Log Analytics, Application Insights, residency, latency, and budget in the target subscription.

Create a production application resource group and create disposable, synthetic-data
non-production resource groups only for bounded rehearsals. Do not retain a standing non-production
PostgreSQL/network floor for the 1-5-user start. Production owns its own VNet, Container Apps
environment, PostgreSQL server, durable storage, Key Vault, identities, and monitoring boundary.
The neutral organization-shared ACR is outside the application resource groups and holds only
immutable, environment-neutral images with least-privilege repository pulls. Keep the selected
IaC tool's subscription/bootstrap layer separate from application resource groups and the
application apply identity. Keep DNS
outside the application resource group. The product owner owns DNS authorization and delegates only
the exact application records to a separately reviewed IaC deployment; the existing zone and
registrar are never imported or deleted implicitly. Before apply, confirm who can execute that
authorization and the recovery boundary.

Use Azure Database for PostgreSQL Flexible Server `Standard_B1ms` with 32 GiB P4 managed-disk
storage, no HA, and 14-day point-in-time retention initially. The owner accepts a restore-based,
hours-scale recovery posture and no automatic zone continuity at this stage; do not convert
Azure's provider recovery observations into a fixed application RTO. Before cutover, restore a
production-shaped sanitized or synthetic dataset and measure the complete database, networking,
identity, connection-switch, application-health, reconciliation, and rollback path. Rehearse PITR
and application reconnection quarterly and after material database, network, identity, or schema
changes. Review backup/storage usage and capacity monthly.

SPM-6 must exercise concurrent API/MCP queries, the scheduled collector Job, ZIP import, analytics,
and the PostgreSQL cache fallback on this SKU. It must measure CPU credits, memory, storage
latency/IOPS, connection counts, p50/p95/p99 latency, backup usage, and restore timing. Bound total
connections across every application replica below the 35-user-connection service limit with
explicit headroom. Increase storage to 64 GiB if capacity, baseline IOPS, or backup allowance is
insufficient; move to B2s or General Purpose if CPU credits, memory, connections, latency, or
support requirements fail. Either change requires a reviewed scaling window and application retry
proof; changing from the small Burstable sizes does not receive Azure's near-zero-downtime scaling.
Reconfirm subscription allocation immediately before apply.

With the API at zero when idle, the collector as a ten-minute scheduled Job, Static Web Apps Free,
no incremental registry charge for a qualifying shared ACR, lean monitoring, no persistent
non-production stack, PostgreSQL private VNet integration, and one Blob Private Endpoint, the
revised production sensitivity is approximately **USD 31-46/month**. Use approximately **USD
40/month** as the initial production forecast and **USD 60/month** as the app-level budget while
usage is measured. These are PAYG USD list-price estimates before tax, support, shared-platform
cost allocation, agreement pricing, currency conversion, and cutover overlap—not a quote.
Reproduce the pricing queries, obtain the subscription-specific quote, and measure API cold starts,
Job execution time, grants, logs, backup, traffic, and Private Link use before apply and after 14
and 30 complete days. Keep 80%, 100%, 120%, and anomaly notifications. No persistent
non-production cost is assumed; each rehearsal estimates and records its bounded temporary cost.

### Networking, edge, and observability

- Use separate public hostnames: Static Web Apps serves the React frontend and Container Apps
  managed ingress serves the backend REST, MCP, and accepted authentication routes. Do not put
  Azure Front Door in the initial target. Keep the collector Job private. Create PostgreSQL with
  private VNet integration in its own delegated subnet and an explicitly owned Private DNS zone;
  it has no public database endpoint. Keep Blob behind its private endpoint and Private DNS zone.
- Keep durable JSON job state and bounded status/result/cancel calls as the correctness baseline.
  Preserve modern Streamable HTTP request-scoped SSE progress and `subscriptions/listen` as
  optional capabilities only after SPM-6 proves direct Container Apps behavior and exact
  ChatGPT/Claude support. Streaming failure must not lose work or make results unrecoverable.
- For Container Apps, create the final VNet integration intentionally because the environment
  subnet cannot be changed after environment creation. Prefer public application ingress in an
  injected VNet with private backend endpoints unless policy explicitly requires private ingress.
- Keep the current DigitalOcean `oauth2-proxy` unchanged as the pre-cutover rollback asset. For
  Azure, use the minimum viable Container Apps Google authentication adapter: server-directed
  login, trusted identity-header parsing, one secret-backed allowlist, existing-user match,
  existing application JWT issuance, and logout. Set platform authorization to allow
  unauthenticated requests so health, Spotify callback, JWT/API-token, and MCP bearer paths reach
  application authorization. Do not add provider-token storage, invitations, self-service
  provisioning, multiple providers, group synchronization, session migration, or SWA-linked API
  routing initially.
- Do not deploy `oauth2-proxy` in Azure merely as a transition. Activate that fallback only after
  a concrete native-auth gate failure and an accepted amendment. A 1-5-user cohort may sign in
  again; do not build cross-system session migration.
- Prove custom-domain certificate issuance, callback URLs, headers,
  exact credentialed CORS allowlists, rejection of malformed and unapproved origins, CSRF controls,
  cookie host/domain/path and `Secure`/`HttpOnly`/`SameSite` behavior, ACA Google login/callback,
  allowlist/account-link rejection, JWT routes, Bearer MCP routes, WebSocket/HTTP/SSE behavior,
  reconnect and notification-loss recovery, and the 240-second timeout before cutover.
- Retain the database-backed product/admin log path initially. Emit redacted structured stdout to
  Azure Monitor/Log Analytics with 30-day retention. Begin with lean platform metrics, about 1 GB
  of logs, two or three high-value alerts, hourly public health, daily deeper auth/MCP checks, and
  collector execution-failure, timeout, skipped-overlap, and stale-lease alerts. Alert on database
  capacity and failed imports/migrations.
  Do not add application traces or identifier fields until the owner accepts the PII field policy
  and a refreshed ingestion-cost estimate. Managed agents do not create traces without application
  instrumentation; see the dated evidence pin.

### Storage and data

- Treat PostgreSQL as the durable migration surface. Treat uploaded ZIPs as transient workflow
  payloads that must be drained or reconciled at cutover, not archives to migrate after processing.
  Treat Caddy state as replaceable and Valkey as disposable.
- Use a dedicated general-purpose v2 Blob Hot ZRS account with a private Blob endpoint. Disable
  public/anonymous and Shared Key access; authorize API and collector through narrowly scoped
  managed identities. Use opaque object keys, create-without-overwrite, size and SHA-256 checks,
  and explicit database storage locators rather than raw container paths.
- Keep each object only while its database job is pending, processing, or within bounded automated
  retry. After a terminal state commits, use an outbox or `source_delete_pending` state to delete
  the object immediately and retry cleanup deterministically. Delete unreferenced objects after a
  24-hour reconciliation grace period. Disable Blob/container soft delete, versioning, and Blob
  Backup so source ZIPs do not remain as hidden recoverable copies after processing.
- Download a claimed object to unique collector ephemeral storage, verify it, run the unchanged
  seekable streaming ZIP parser, and delete the local file in `finally`. SPM-25 owns the separately
  reviewed schema, abstraction, migration, failure-injection, privacy, and deletion implementation.
- Select PostgreSQL backup retention, zone HA, and geo-backup from explicit owner RPO/RTO. Flexible
  Server point-in-time restore creates a new server; application traffic and connection strings
  must be deliberately switched after restore.

### Identity and authority

- Use GitHub Actions OIDC with environment-constrained workload identity federation; do not store
  long-lived Azure client secrets in GitHub.
- Separate CI plan/read, infrastructure apply, image-push, and deployment identities. A successful
  plan, image build, merge, or repository delivery does not authorize apply or deployment.
- Give each runtime surface a separate user-assigned managed identity with only its required Key
  Vault, ACR pull, storage, and service permissions.
- Begin with PostgreSQL password authentication only. Create separate non-administrator login
  roles and app-specific Key Vault secrets for API DML, collector DML, and migration DDL; each
  workload identity may read only its own secret. No administrator or object-owner credential is
  available to a runtime or migration container.
- Rehearse a bounded, write-fenced password rotation and revision restart before cutover. Do not
  treat Key Vault latest-version refresh as an atomic PostgreSQL password change.
- Reconsider Entra database authentication only through a dedicated accepted plan when policy,
  rotation, workload attribution/revocation, connection-lifecycle work, operator scale, or threat
  evidence triggers it. Managed-identity database tokens require a tested token-producing async
  connection factory and Alembic equivalent; this is not a connection-string-only substitution.
- Preserve the existing Spotify OAuth, application JWT/RBAC, API-token, admin, and MCP bearer
  boundaries. The approved Azure Google adapter changes the trusted identity-header source, not
  those authorization contracts. Its exact allowlist/account-link behavior, including disabling
  or explicitly accepting the current single-user fallback, remains plan-first implementation
  work.

### Packaging

Use direct, package-scoped synchronization from the root `uv.lock` in multi-stage production
builds. Build from the repository root only after the strict root `.dockerignore` and context tests
prove that credentials, personal data, local caches, VCS metadata, local infrastructure state, and
unrelated artifacts cannot enter the context. Pin uv 0.12.3 and the base image by immutable digest;
install with locked, production-only, non-editable semantics for the selected workspace package;
copy only the built environment and required application files into the runtime image. Do not
commit a second pip-compatible dependency authority.

### React/API and MCP compatibility contracts

- Inventory the routes, schemas, errors, pagination, authorization, and user journeys consumed by
  both Python UIs before migrating a route group.
- Generate strict TypeScript client types from the versioned FastAPI OpenAPI document with pinned,
  deterministic tooling and a CI drift check. Keep a thin hand-written transport/auth layer; do not
  expose database models directly to the browser.
- Introduce the React application beside the Python UIs, migrate one independently testable route
  group at a time, and preserve a traffic switch back to the old UI until parity and soak pass.
  Retire the two Python UIs only after every owned route has an explicit successor or deletion
  decision. Do not couple UI retirement to Azure DNS cutover.
- Keep REST as the browser and operations contract. Keep remote MCP and assistant workflows as the
  primary assistant boundary. Neither boundary may be silently versioned by infrastructure work.
- Replace FastMCP private `_mcp_server` calls only under SPM-6 with public-library or locally owned
  adapter seams and contract tests. Preserve `/mcp/v1`, `/mcp/tools`, and `/mcp/call` until a
  separately accepted compatibility decision says otherwise.
- The current bearer-token MCP authentication is not a completed remote MCP OAuth design. Any
  OAuth discovery, authorization-server, client-registration, scope, or token-audience change is a
  separate plan-first authentication/public-contract decision.
- Prove long-lived HTTP/SSE and reconnect behaviour with each supported client through the intended
  edge, including the 240-second ACA ingress timeout, idle periods, revision changes, and transient
  disconnects. Do not interpret stateless HTTP configuration as proof of client compatibility.

### Migration and rollback

1. **Build in isolation.** DigitalOcean remains authoritative. Provision and validate Azure with
   synthetic or sanitized data; do not dual-write.
2. **Rehearse.** Restore a production-shaped, authorized capture and exercise the transient Blob
   handoff in a non-production environment. Verify Alembic head, row counts/checksums,
   token-decryption workflow, upload hashing/staging/terminal deletion/orphan reconciliation,
   pending-job handling, auth callbacks, MCP conformance/reconnect, backup restore time, and the
   documented rollback procedure. No production credentials or data are implied by this ADR.
3. **Prepare the cutover.** Confirm DNS and both OAuth-console owners, parallel callback support,
   TTL, monitoring, immutable digests, database copy and active-upload drain procedure, RPO/RTO thresholds,
   and a named rollback decision maker.
4. **Fence writes.** Stop the collector, drain or safely preserve import jobs, block API/MCP
   mutations, prove no remaining writer, and capture the final database plus any referenced active-upload state.
5. **Cut traffic without writing.** Validate health, read-only data parity, callbacks, MCP clients,
   and synthetic journeys against Azure before allowing the first Azure mutation.
6. **Record the first Azure write as the irreversible boundary.** Before it, rollback returns
   traffic to the still-authoritative DigitalOcean estate. After it, this decision selects forward
   recovery in Azure: fence Azure writes, roll the application to a qualified image revision or
   restore PostgreSQL to a new Flexible Server, reconcile transient Blob objects/jobs, and resume only after the
   same gates pass. DigitalOcean becomes a write-fenced archive, not an automatic traffic fallback.
   Returning writes to DigitalOcean after that point is allowed only under a new accepted
   reverse-migration plan, or with explicit owner acceptance that every Azure-window write will be
   lost. No untested reverse synchronization is assumed.
7. **Soak for seven full days.** Start the clock only after Azure is serving production traffic and
   production writes are enabled. Keep DigitalOcean powered, write-fenced, monitored, and
   recoverable for seven consecutive 24-hour periods. Restart or extend the clock after any
   threshold breach or recovery-affecting change. Exit only after explicit error-rate,
   data-reconciliation, RPO, RTO, auth, MCP, collector, and restore thresholds pass and the owner
   approves the soak exit.
8. **Retire separately.** DigitalOcean deletion is a distinct destructive operation requiring
   owner authorization after reconciliation, restore proof, retention expiry, DNS/callback
   cleanup, and proof that shared project, VPC, firewall, DNS, or backup resources are not being
   deleted. A merge or successful cutover never authorizes retirement.

### Action and authority classification

| Class | Examples | Required authority |
|---|---|---|
| Plan-only | ADRs, IaC source, container build-context changes, runbooks, synthetic contract tests, cost models, and non-production rehearsal design. | Repository authority and every applicable accepted plan-first decision. No cloud mutation. |
| Apply | Create or change Azure resources, identities, role assignments, secrets references, DNS records, callbacks, monitoring, or environments. | A separately authorized, exact reviewed plan; named root operator; monitored terminal result. Merge is insufficient. |
| Human go/no-go | Production restore rehearsal acceptance, write fence, DNS/callback switch, first Azure write, rollback invocation, and soak exit. | Explicit owner-approved criteria and a named decision maker at each gate. |
| Irreversible or difficult to roll back | First Azure write without reverse synchronization, old callback removal, production data disposal, and DigitalOcean/resource deletion. | Separate owner authorization after evidence, retention, dependency, and recovery checks. Never implied by this ADR or deployment success. |

### Non-goals

- No Azure resource, IaC apply, production deployment, credential, DNS, OAuth-console, or provider
  mutation is authorized by this record.
- No production or personal Spotify data is inspected, copied, transformed, or deleted by this
  decision package.
- No authentication consolidation, remote MCP OAuth rollout, public MCP/API compatibility break,
  unrelated database-schema change, broader data migration, or privacy policy is selected here.
  The transient ZIP deletion contract is the only source-object retention choice in this record.
- No Python, targeted Rust, or full Rust implementation is authorized until mandatory profiling,
  the representative Rust comparison, and a dedicated language ADR are accepted.
- No promise is made that scale-to-zero, Entra PostgreSQL authentication, managed
  Redis, HA, or any specific SKU is suitable before its named evidence gate.
- No merge or successful Azure soak authorizes DigitalOcean decommissioning.

## Consequences

- Contract-first staged replacement prevents infrastructure, frontend, MCP, authentication,
  storage, language, and data changes from becoming one irreversible event while still allowing
  partial or full rewrites when evidence supports them.
- Workload-specific Container Apps is the selected target. Failed protocol, storage, auth, worker,
  quota, or regional gates block release or trigger an ADR amendment; there is no standing VM
  fallback that can postpone the target indefinitely.
- The API scales to zero and the collector runs only as a scheduled finite Job. This lowers idle
  cost but makes measured cold starts, execution leases, claim recovery, and failure exits release
  gates. Changing only the API minimum to one is the accepted fallback when those gates fail.
- Managed PostgreSQL improves service ownership and recovery tooling, but production HA materially
  increases cost and remains an owner RPO/RTO choice.
- Omitting managed Redis reduces migration dependencies but requires measured PostgreSQL-fallback
  capacity before cutover.
- Direct package-scoped `uv.lock` synchronization keeps one dependency authority, at the cost of a
  broader root build context that must be fail-closed and continuously tested.
- Transient Blob staging adds a bounded application/schema seam and collector download step, but
  removes the shared account-key filesystem, supports least-privilege managed identities, and avoids
  retaining raw Spotify exports after processing.
- The decision preserves the current authentication and public MCP/API boundaries; it therefore
  does not silently solve or widen their known modernization work.
- Cost projections remain ranges until subscription, availability, utilization, data, recovery,
  and monitoring requirements are measured.

## Validation and owner decision evidence

The owner reviewed visible alternatives, benefits, costs, risks, and recommendations on 2026-08-26
and 2026-08-27 UTC. "Approved" below records an explicit constituent choice. Yuval Moran accepted
the cohesive ADR with "Decision 4 A" on 2026-08-27 UTC. Every implementation gate remains evidence
required before the affected build, apply, or cutover.

| Choice | State | Current decision or position | Evidence required before implementation or release |
|---|---|---|---|
| Compute | Approved | API/MCP Container App starts at `minReplicas: 0`, `maxReplicas: 1`; collector becomes a ten-minute scheduled Container Apps Job with one replica; React stays on Static Web Apps; no standing VM fallback. | Thirty Israel Central cold starts; real ChatGPT/Claude MCP and direct-SSE/reconnect tests; auth/upload/graceful-shutdown proof; finite Job entry point, singleton lease, abandoned-claim reconciliation, timeout/SIGTERM/failure-exit pressure tests, and execution alerts. Owner approval: "Decision 1 - A" on 2026-08-27 UTC. |
| Registry | Approved | Use one neutral organization-shared ACR. Spotify owns repository/digest publication and pull assignments, not the registry resource lifecycle. Migrate sibling consumers through separately approved repository tickets; retire redundant registries only after every consumer proves publish, pull, rollback, and recovery. | Named neutral platform owner/resource group/IaC; repository-scoped ABAC/RBAC; immutable release protection; capacity/rate/retention/monitoring/cost allocation; platform recovery; Agrisense/LARP/Spotify migration plans; deletion inventory and separate apply/deletion authority. Owner approval and implementation responsibility granted on 2026-08-27 UTC. |
| Static Web Apps | Approved | Begin the 1-5-user production pilot on Free, then upgrade the same resource to Standard before a quota, SLA, or feature gate requires it. | Subscription-wide bandwidth inventory and month-to-date aggregation; `BytesSent` proof; early warning thresholds; rehearsed in-place plan change; named upgrade authority. Owner approval: "Option B sounds good in terms of the SWA" on 2026-08-27 UTC. |
| Replacement and language | Approved | Contract-first staged replacement; partial and full rewrites remain valid candidates; mandatory profiling and a representative Rust comparison precede a dedicated language ADR. | Comparable workload, profiler, parity, resource, failure-recovery, build, and operations evidence. Missing evidence blocks selection. |
| Region | Approved | Israel Central primary; France Central is a documented, unprovisioned contingency. | Live subscription provider/SKU/quota/policy checks, residency, refreshed latency and pricing, and a separately accepted cross-region data-recovery design. |
| Database service | Approved | Azure Database for PostgreSQL Flexible Server is the initial database service. | Subscription/SKU availability, capacity, version/extension compatibility, connection, migration, and cost proof. |
| Database availability and recovery | Approved | Start with `Standard_B1ms`, 32 GiB P4 storage, no HA, and 14-day PITR. Accept restore-based, hours-scale recovery and no automatic zone continuity initially. A read-only 2026-08-26 probe of the signed-in Azure subscription advertises B1ms, 32/64-GiB storage, and zones 1-3 in Israel Central. | Successful timed restore and SPM-6 mixed-workload proof; explicit connection headroom; CPU-credit, memory, IOPS, latency, storage, backup, and recovery monitoring; quarterly restore rehearsal; scale to 64 GiB/B2s/General Purpose when gates fail. Reconfirm allocation capacity immediately before apply. Israel Central has no PostgreSQL geo-redundant backup. Owner approval: "approved" on 2026-08-26 UTC after reviewing the complete B1ms/32-GiB/no-HA/14-day-PITR mitigation package. |
| Database networking | Approved | Create PostgreSQL with private VNet integration, a dedicated delegated subnet, private DNS, and no public database endpoint; do not add a PostgreSQL Private Endpoint. Run migrations and break-glass access through an Azure-side private path. | Creation-time network-mode proof; ACA/API/Job/Alembic connectivity; DNS and TLS; restore-to-new-server reconnection; Azure-side migration/operator access; fail-closed public-access assertion; rollback rehearsal. Owner approval: "Decision 2 - A" on 2026-08-27 UTC. |
| Storage | Approved | Dedicated Blob Hot ZRS is a transient durable API-to-collector handoff, not an archive. Retain only pending/processing/retryable objects; schedule immediate deletion after every terminal state; delete unreferenced objects after a 24-hour grace period; disable soft delete, versioning, and Blob Backup. | SPM-25 `UploadStore`/schema plan; managed-identity RBAC and private-access proof; SHA-256, create-without-overwrite, compensation, outbox/deletion, orphan, staging, retry, cancellation, privacy, and 500-MiB pressure tests. Owner approval: "option B approved" on 2026-08-26 UTC after the transient-durability comparison. |
| Public topology | Approved | Separate Static Web Apps and Container Apps hostnames; no Front Door initially; durable polling remains authoritative while standards-defined MCP SSE progress/notifications stay optional. | SPM-6 direct-ACA SSE/timeout/reconnect/client matrix, exact CORS/CSRF/cookie/callback tests, direct-origin security, and an A-to-C rehearsal. Owner approval: "A, subject to mitigation and SPM-6 gates approved" on 2026-08-26 UTC. |
| Auth coexistence | Approved | Introduce minimum viable ACA Google authentication gradually while DigitalOcean Caddy/`oauth2-proxy` remains authoritative. The trusted-header bridge keeps the existing application JWT/RBAC, Spotify OAuth, API-token, admin, and MCP bearer contracts. Do not deploy Azure `oauth2-proxy` unless the native path fails a concrete gate and an amendment activates it. For 1-5 users, require re-login rather than session migration and defer invitations, self-service provisioning, multiple providers, group sync, token storage, and SWA-linked API routing. | Dedicated accepted auth plan; named DNS/Google-console owners; separate parallel Azure callback/client; deny-by-default route matrix; allowlist/account-link and single-user-fallback decision; identity-header spoof rejection; exact CORS/cookie/CSRF/logout proof; SPM-6/SPM-10 client and route parity; Azure revision/config rollback. Owner approval: "approved" on 2026-08-26 UTC after reviewing the refined B-YAGNI package. |
| IaC | Approved | Use Bicep with separate bootstrap/application layers, OIDC-separated preview/apply identities, reviewed `what-if`, measured drift/noise handling, explicit omission/deletion inventory, imperative Entra reconciliation, focused end-state guards, and recovery rehearsal. Terraform remains a verified production precedent but is not selected; do not mix tool ownership within one resource lifecycle. | Exact module/resource design; pinned tool/action/API versions; least-privilege identity review; secret-safe deterministic preview; drift baseline; omission/deletion inventory; imperative Entra controls; prior-template reapplication and recovery rehearsal; no-apply verification. Owner approval: "approved" on 2026-08-26 UTC after the verified LARP/Agrisense comparison. |
| Database identity | Approved | Use PostgreSQL password authentication only initially, with separate API DML, collector DML, and migration DDL login roles and app-specific Key Vault secrets. Each workload identity reads only its own secret. Use a bounded write-fenced rotation/restart; revisit Entra only on objective policy, rotation, attribution/revocation, connection-lifecycle, operator-scale, or threat triggers. | Exact least-privilege grants and public/default-privilege revocation; runtime DDL-denial proof; break-glass administrator ownership; secret non-disclosure; timed rotation/restart/rollback; private DNS/TLS proof; SPM-6 connection/failure evidence; Alembic-only migration identity. Owner approval: "In that case, option a is good and accepted" on 2026-08-26 UTC after confirming that Key Vault is a new app-specific managed Azure resource already needed for other application secrets. |
| Frontend contract | Approved | Static Web Apps, versioned REST, generated OpenAPI TypeScript types, thin auth/transport layer, and route-group migration. | Deterministic generation/drift gate, complete route/schema inventory, origin/cookie/CORS proof, parity, and rollback tests. |
| Packaging | Approved | Direct package-scoped root `uv.lock` synchronization in a multi-stage build. | Pinned uv/base/app digests, locked production-only closure, strict root `.dockerignore`, build-context tests, provenance/SBOM evidence, and cache-locality proof. |
| Post-write rollback | Approved | Forward recovery in Azure; DigitalOcean is not a writable fallback after the first Azure write. | Restore and application-revision rehearsal, upload/job reconciliation, explicit first-write go/no-go, owner-approved loss policy for any exceptional return to DigitalOcean. |
| Soak and deletion | Approved | Seven full days after Azure serves production traffic and writes, with DigitalOcean powered and write-fenced. Deletion remains separately authorized. | Seven consecutive passing 24-hour periods, error/data/auth/MCP/collector/RPO/RTO thresholds, retention expiry, restore proof, dependency inventory, soak-exit approval, and named deletion approver. |
| Observability | Approved | Redacted logs and metrics with 30-day retention; traces only after PII/cost approval. | Accepted field policy, ingestion estimate, alert thresholds, and synthetic-check evidence. |
| Cost posture | Approved | With SWA Free, shared ACR, API scale-to-zero, scheduled collector Job, lean monitoring, disposable non-production, PostgreSQL private VNet integration, and one Blob Private Endpoint, forecast about USD 40/month within a USD 31-46 sensitivity and use a USD 60 app budget. Front Door, HA, Redis, traces, premium support, and France resources remain excluded. | Fresh subscription quote and shared grants; 80%/100%/120% budget and anomaly alerts; measured API cold starts, Job duration, logs, tests, backup, Blob byte-days, Private Link bytes, and egress; re-estimate after 14 and 30 complete days. Owner accepted the cohesive cost posture with "Decision 4 A" on 2026-08-27 UTC. |

Ticket-specific repository validation for this Accepted record includes link validation, ADR
number/index/status checks, `git diff --check`, and the canonical agent-contract suite. Passing
those checks validates the decision package's structure; it does not validate Azure or production.

## Rollback / revisit trigger

Amend or supersede this decision when any of these occur:

- MCP clients cannot operate correctly behind the 240-second Container Apps limit.
- Direct Container Apps ingress cannot pass the selected MCP SSE/reconnect tests, or exact clients
  cannot use the notification optionality that justified separate hostnames.
- A managed WAF, private origin, single-origin browser-auth requirement, or measured traffic makes
  Front Door or another edge worth its recurring cost and transport restrictions.
- Required RPO/RTO, availability, residency, quota, or budget makes the chosen target infeasible.
- Upload privacy, retry, threat-model, or deletion requirements invalidate the transient Blob
  handoff or require recoverable retention.
- The accepted authentication, frontend-origin, public MCP/API, or data contract changes.
- Measured load invalidates the PostgreSQL fallback, compute sizing, or cost model.
- The Azure-only target or the verified Bicep/Terraform precedents and operational controls change
  materially.
- Comparable profiling and Rust proof evidence selects a backend language and rewrite boundary.
- Azure service retirement, regional availability, pricing, or security guidance changes
  materially.

Revisit does not authorize production mutation. Implement a superseding accepted decision and a
separately approved migration/rollback plan.

## Related decisions

- [ADR 0004](0004-separate-provider-identities-and-minimize-profile-retention.md) resolves ADR
  0002's deferred Google account-link and single-user-fallback policy: use a verified stable
  provider subject, never email equality, and keep provider-token storage disabled.

- [ADR 0001 - Use merge commits by default for pull requests](0001-pull-request-merge-method-policy.md)
- SPM-20 supplies the dated estate baseline.
- SPM-6 must provide MCP compatibility evidence before the Container Apps API/MCP release.
- SPM-10 owns the scoped React replacement.
- SPM-21 owns the accepted architecture implementation plan and infrastructure delivery.
- SPM-23 owns Spotify image publication and managed-identity pulls from the shared registry.
- SPM-25 owns implementation of the approved transient Blob and deletion contract and any future
  upload-retention change.
- SPM-26 owns production backup, restore, RPO, and RTO evidence.
- SPM-30 preserves the separation between repository delivery and manual production deployment.
- SPM-34 owns provider-account audit evidence without broadening this record's access authority.
- [OPS-54](https://linear.app/stratex/issue/OPS-54/define-the-neutral-organization-shared-acr-control-plane)
  owns the neutral shared-registry platform contract.
- [OPS-55](https://linear.app/stratex/issue/OPS-55/rehome-the-agrisense-acr-and-reconcile-its-delivery-and-runtime)
  combines registry rehoming with Agrisense publication and runtime reconciliation.
- [OPS-56](https://linear.app/stratex/issue/OPS-56/migrate-larp-store-delivery-and-runtime-to-the-shared-acr)
  owns LARP Store migration to the shared registry.
- [OPS-57](https://linear.app/stratex/issue/OPS-57/retire-redundant-product-registries-after-cross-product-soak)
  owns the separately authorized contraction after every consumer completes its gates and soak.
