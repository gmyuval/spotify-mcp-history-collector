# ADR 0002 - Choose the Azure target architecture and migration boundaries

Date: 2026-08-26 (UTC)
Status: Accepted
Decision owners: Yuval Moran
Linear issue: [SPM-4](https://linear.app/stratex/issue/SPM-4/record-the-product-and-azure-target-architecture-and-migration-boundaries)
Owner evidence: accepted through the owner decision session completed on 2026-08-26 UTC

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

This accepted record fixes the target architecture and implementation boundaries. It grants no
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
- Keep durable data private, expose one deliberate public edge, and preserve a no-production-data
  development and rehearsal path.
- Base region, availability, recovery, and cost choices on owner requirements and measured
  subscription facts rather than list-price optimism.
- Make every irreversible action, especially production cutover and DigitalOcean deletion, a
  separately authorized operation with explicit evidence and stop conditions.

## Options considered

### Compute and product shape

| Option | Benefits | Costs and risks | Rollback posture |
|---|---|---|---|
| Azure VM with Docker Compose | Lowest behavioural change; preserves Caddy, `oauth2-proxy`, shared local uploads, continuous collector, and current streaming topology. | Retains single-host failure exposure and operator-owned OS, Docker, patching, backup, and capacity work. A single VM is not zone-highly-available. | Strongest reversible landing zone when images are immutable and the managed database/data boundaries are kept separate. |
| Split workload-specific Azure Container Apps | Immutable revisions, traffic-controlled rollback, managed ingress/TLS, managed identities, per-service scaling, and internal routing. The API/MCP and continuous collector have distinct lifecycle and scaling boundaries. | The 240-second ingress timeout, shared uploads, auth/cookie/routing parity, and continuous-worker liveness require proof. API and collector begin warm. | Selected target. Roll back each application workload by immutable revision; data rollback remains separate. A VM is not the standing fallback. |
| Hybrid managed target | React on Static Web Apps; API/MCP and collector on separate Container Apps; managed PostgreSQL and storage. Static delivery has no application-container cold start while backend workloads retain independent scaling and revisions. | Requires explicit same-origin, CORS, cookie, callback, routing, storage, and observability validation across services. | Selected product shape. Each tier can be replaced and rolled back independently behind fixed contracts. |
| In-place modernization | Keeps the Python API and collector implementation while changing packaging and infrastructure. | Risks preserving accidental coupling and postponing evidence-driven replacement indefinitely. | Permitted only as one measured implementation candidate, not the default outcome. |
| Partial rewrite | Replaces one bounded workload or route group behind the fixed contracts. | Requires dual-operation, compatibility, data, and observability discipline during coexistence. | Selected delivery method when profiling or maintainability evidence justifies replacement. |
| Full rewrite | Can simplify a workload whose existing design cannot meet the measured contract, operability, or performance target. | Highest simultaneous compatibility, migration, and rollback risk; weak evidence can turn it into an expensive reimplementation. | Explicitly permitted as a candidate, but only after profiling, a representative comparison, and a dedicated accepted language/rewrite decision. |

### Infrastructure as code

| Option | Benefits | Costs and risks |
|---|---|---|
| Terraform | Portable workflow and a mature plan/apply model. Azure Blob remote state provides locking and consistency. | Introduces a state bootstrap, sensitive-state access control, recovery, drift, and force-unlock boundary. No Terraform source or operating precedent was found in either this repository or the examined LARP Store history. |
| Bicep | Azure-native resource-group and subscription deployments, no separate client-state backend, deployment history, and `what-if` previews. LARP Store provides a substantive local precedent for Container Apps, ACR, PostgreSQL Flexible Server, Key Vault, observability, OIDC-separated identities, and deployment verification. | ARM incremental deployment does not delete omitted resources, Entra/OIDC bootstrap still needs imperative reconciliation, and `what-if` can miss defects or produce noise. These limitations require explicit guards, tests, and runbooks. |

Select Bicep for the Azure-only target. Adopt the demonstrated LARP controls rather than citing the
precedent by name alone: separate subscription/bootstrap and application layers; separate
preview/read and apply identities; use environment-constrained OIDC; review deterministic
`what-if` output against a documented provider-noise baseline; test invariants that `what-if`
cannot prove; treat Entra federation and destructive reconciliation as explicit imperative
operations; and document drift correction, application revision rollback, infrastructure
reapplication, and database recovery. Root owns preview and drift review. A separately authorized
root operation owns apply. No Terraform state account or force-unlock process is introduced.

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

## Decision

Adopt the following target and boundaries.

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
4. Store immutable application images in Azure Container Registry. Pin uv, base-image digests, and
   application-image digests, and retain build provenance.
5. Use workload-specific Azure Container Apps for the API/MCP service and continuous collector,
   each beginning with at least one replica. Do not use a standing VM/Compose fallback. Failure of
   an MCP, upload, authentication, worker, quota, or regional preflight gate blocks the Azure
   release until the target is corrected or this ADR is amended; it does not silently switch the
   architecture.
6. Complete the mandatory Python profiling and representative Rust comparison before selecting the
   backend language or rewrite extent in a dedicated ADR. Infrastructure preparation may proceed
   against versioned contracts, but it must not encode Python as the permanent backend boundary.

### Target surface map

| Current deployable or durable surface | Target and boundary |
|---|---|
| FastAPI API and `/mcp/v1` | Preserve the versioned REST/MCP contract while the implementation remains Python or is replaced under the language ADR. Run as its own Container App with `minReplicas: 1` initially. Gate release on MCP, auth, and upload proof; do not fall back silently to a VM. |
| Continuous collector | Preserve collection, checkpoint, job, and data semantics while the implementation remains Python or is replaced. Run as a separate continuously available Container App with `minReplicas: 1`, not as an event job, after worker and storage rehearsal. |
| Admin and Explorer Python UIs | Replace, in their own SPM-10 slices, with one strict TypeScript + React application. Keep the Python UIs available until route-by-route parity and rollback are proven. |
| React application | Prefer Static Web Apps after the origin/auth decision. Pin an immutable artifact and keep its deployment independently reversible from API and cloud cutover. |
| `oauth2-proxy` and application auth | Preserve the current Google/Spotify flows and route protections during coexistence. Run `oauth2-proxy` as a dedicated Container Apps edge workload for routes that still require forward auth, then retire it only when an accepted frontend/auth contract has explicit ownership and rollback. |
| Caddy reverse proxy and ingress | Replace with Container Apps managed ingress and the accepted static-web/API edge only after exact route, header, TLS, callback, auth, health, and MCP conformance. Preserve reviewed Caddy behaviour as migration evidence; do not migrate its certificate state. |
| PostgreSQL | Move to Flexible Server through rehearsed backup/restore or logical migration selected under SPM-25/26. Keep schema and Alembic history; separate runtime DML from migration DDL. |
| Valkey | Omit initially and use the existing PostgreSQL fallback after load proof. If a dedicated cache is later required, evaluate Azure Managed Redis in a separate cost/operations slice. |
| Uploaded export ZIPs | Mount a shared Azure Files target for the lowest-change path after retention/privacy acceptance, or introduce a separately planned Blob abstraction before migration. Never leave the API and collector with different path authorities. |
| Caddy TLS/config volumes | Treat as replaceable configuration, not migrated business data. Re-issue certificates and preserve reviewed routing configuration through IaC or immutable deployment assets. |
| Database-backed product/admin logs | Retain initially with redaction and retention review. Add redacted structured stdout and Azure Monitor alerts without copying unrestricted PII into a second store. |
| Container images | Build once, record provenance, publish to ACR, and deploy by immutable digest. Do not rebuild during rollback. |
| Alembic migrations | Run as one explicitly invoked, monitored migration process with its own identity before application traffic is admitted. Stop on failure; do not assume an automatic downgrade. |

### Region, availability, and cost boundary

Select Israel Central as the primary region. The owner reports the system is currently used in
Israel; Azure's rendered Container Apps pricing selector and PostgreSQL Flexible Server pricing
selector both list Israel Central, and the session's interleaved regional TCP-connect probe from
Israel measured an approximately 4 ms median versus approximately 49 ms for Italy North and 53 ms
for France Central. These public and network observations do not replace a subscription preflight.

Select France Central as the documented contingency region because it combines complete target
service coverage, the LARP Bicep precedent, and a stronger recovery posture than the marginally
lower-latency Italy North alternative. No France resources, replication, failover, or standby cost
are selected initially. Israel Central is not region-paired, and PostgreSQL Flexible Server does
not offer geo-redundant backup there. A later recovery plan must therefore define authorized
cross-region data movement rather than implying that this contingency creates automatic recovery.
Before any apply, verify provider registration, policy, quota, selected SKUs, availability-zone
capacity, Container Apps environment creation, PostgreSQL configuration, ACR, Key Vault, Storage,
Log Analytics, Application Insights, residency, latency, and budget in the target subscription.

Create separate production and non-production application resource groups. Production owns its own
VNet, Container Apps environment or VM, PostgreSQL server, durable storage, Key Vault, identities,
and monitoring boundary. ACR may be shared only for immutable, environment-neutral images and
least-privilege pulls. Keep Bicep's subscription bootstrap separate from application resource
groups and application apply identity. Keep DNS
outside the application resource group. The product owner owns DNS authorization and delegates only
the exact application records to a separately reviewed Bicep deployment; the existing zone and
registrar are never imported or deleted implicitly. Before apply, confirm who can execute that
authorization and the recovery boundary.

Use a cost-conscious single-zone PostgreSQL baseline with 14-day point-in-time restore and no HA,
matching rather than overstating the current estate's availability. This accepted baseline does
not fill in an unstated RPO/RTO. Require weekly automated backup evidence and a
quarterly restore rehearsal; select zone-redundant General Purpose HA instead if the owner requires
an RTO that the restore rehearsal cannot meet.

The dated evidence artifact records public list-price floors and omissions for VM, ACA, and both
hybrid forms. Do not treat those floors as a quote or an availability-equivalent comparison. A
Container Apps private endpoint also adds a material management meter; do not add it without a
policy requirement and a refreshed complete cost model.

### Networking, edge, and observability

- Expose one public edge. Keep the collector private. Keep PostgreSQL and durable storage on private
  endpoints with explicitly owned private DNS.
- For Container Apps, create the final VNet integration intentionally because the environment
  subnet cannot be changed after environment creation. Prefer public application ingress in an
  injected VNet with private backend endpoints unless policy explicitly requires private ingress.
- Preserve `oauth2-proxy` as its own Container Apps edge workload while forward-authenticated
  routes depend on it. Do not consolidate or replace authentication in the platform migration
  without a separate accepted decision.
- Prove custom-domain certificate issuance, callback URLs, headers,
  cookie scope, same-origin/CORS behaviour, Google forward-auth routes, JWT routes, Bearer MCP
  routes, WebSocket/HTTP behaviour, and the 240-second timeout before cutover.
- Retain the database-backed product/admin log path initially. Emit redacted structured stdout to
  Azure Monitor/Log Analytics with 30-day retention. Alert on health, error rate,
  collector liveness, failed imports/migrations, database capacity, and synthetic MCP/auth checks.
  Do not add application traces or identifier fields until the owner accepts the PII field policy
  and a refreshed ingestion-cost estimate. Managed agents do not create traces without application
  instrumentation; see the dated evidence pin.

### Storage and data

- Treat PostgreSQL and uploaded ZIPs as durable migration surfaces. Treat Caddy state as
  replaceable and Valkey as disposable.
- Use Azure Files as the lowest-code-change shared upload target only after upload retention,
  deletion, checksum, backup, access, and privacy rules are accepted. Azure Files preserves the
  current shared-path contract but Container Apps mounts use a storage-account key.
- Prefer a future Blob Storage abstraction if managed-identity/RBAC access or stronger object
  lifecycle controls justify changing the `Path` contract. That is a separate application and
  data-migration slice, not an implicit part of infrastructure provisioning.
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
- Separate PostgreSQL migration/DDL authority from runtime DML roles.
- Begin with a PostgreSQL password referenced from Key Vault unless Entra authentication receives
  an accepted implementation plan and tests token renewal with SQLAlchemy connection pools.
  Managed-identity database tokens expire, so this is not a connection-string-only substitution.
- Preserve the existing Google and Spotify authentication boundary until separate owner-approved
  work changes it.

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
2. **Rehearse.** Restore a production-shaped, authorized capture and upload manifest into a
   non-production environment. Verify Alembic head, row counts/checksums, token-decryption workflow,
   pending-job handling, auth callbacks, MCP conformance/reconnect, backup restore time, and the
   documented rollback procedure. No production credentials or data are implied by this ADR.
3. **Prepare the cutover.** Confirm DNS and both OAuth-console owners, parallel callback support,
   TTL, monitoring, immutable digests, database/upload final-copy procedure, RPO/RTO thresholds,
   and a named rollback decision maker.
4. **Fence writes.** Stop the collector, drain or safely preserve import jobs, block API/MCP
   mutations, prove no remaining writer, and capture final database and upload checkpoints.
5. **Cut traffic without writing.** Validate health, read-only data parity, callbacks, MCP clients,
   and synthetic journeys against Azure before allowing the first Azure mutation.
6. **Record the first Azure write as the irreversible boundary.** Before it, rollback returns
   traffic to the still-authoritative DigitalOcean estate. After it, this decision selects forward
   recovery in Azure: fence Azure writes, roll the application to a qualified image revision or
   restore PostgreSQL to a new Flexible Server, reconcile uploads/jobs, and resume only after the
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
  database-schema change, data migration, retention policy, or privacy policy is selected here.
- No Python, targeted Rust, or full Rust implementation is authorized until mandatory profiling,
  the representative Rust comparison, and a dedicated language ADR are accepted.
- No promise is made that scale-to-zero, Entra PostgreSQL authentication, Azure Files, managed
  Redis, HA, or any specific SKU is suitable before its named evidence gate.
- No merge or successful Azure soak authorizes DigitalOcean decommissioning.

## Consequences

- Contract-first staged replacement prevents infrastructure, frontend, MCP, authentication,
  storage, language, and data changes from becoming one irreversible event while still allowing
  partial or full rewrites when evidence supports them.
- Workload-specific Container Apps is the selected target. Failed protocol, storage, auth, worker,
  quota, or regional gates block release or trigger an ADR amendment; there is no standing VM
  fallback that can postpone the target indefinitely.
- API and collector retain warm capacity, so the design does not assume scale-to-zero savings.
- Managed PostgreSQL improves service ownership and recovery tooling, but production HA materially
  increases cost and remains an owner RPO/RTO choice.
- Omitting managed Redis reduces migration dependencies but requires measured PostgreSQL-fallback
  capacity before cutover.
- Direct package-scoped `uv.lock` synchronization keeps one dependency authority, at the cost of a
  broader root build context that must be fail-closed and continuously tested.
- Azure Files minimizes application change but does not meet a managed-identity-only ideal; Blob
  Storage remains a future, separately planned abstraction.
- The decision preserves the current authentication and public MCP/API boundaries; it therefore
  does not silently solve or widen their known modernization work.
- Cost projections remain ranges until subscription, availability, utilization, data, recovery,
  and monitoring requirements are measured.

## Validation and owner decision evidence

The owner accepted the following cohesive architecture on 2026-08-26 UTC after reviewing visible
alternatives, benefits, costs, risks, and recommendations. Each implementation gate remains
evidence required before the affected build, apply, or cutover; it is not a condition that reverts
the accepted architecture silently.

| Choice | Accepted decision | Evidence required before implementation or release |
|---|---|---|
| Compute | Separate warm API/MCP and collector Container Apps; React on Static Web Apps; no standing VM fallback. | SPM-6 long-lived MCP/reconnect soak, upload proof, auth/route parity, worker liveness, and refreshed complete cost. |
| Replacement and language | Contract-first staged replacement; partial and full rewrites remain valid candidates; mandatory profiling and a representative Rust comparison precede a dedicated language ADR. | Comparable workload, profiler, parity, resource, failure-recovery, build, and operations evidence. Missing evidence blocks selection. |
| Region | Israel Central primary; France Central is a documented, unprovisioned contingency. | Live subscription provider/SKU/quota/policy checks, residency, refreshed latency and pricing, and a separately accepted cross-region data-recovery design. |
| Database and HA | PostgreSQL Flexible Server; single-zone, 14-day PITR baseline without HA initially; weekly backup evidence and quarterly restore rehearsal; add zone HA if the accepted RTO requires it. | Owner RPO/RTO/uptime/downtime, successful timed restore, capacity proof, and HA cost acceptance if triggered. Israel Central has no PostgreSQL geo-redundant backup. |
| Storage | Azure Files for the lowest-change initial shared-path contract; Blob only through a separately planned abstraction. | Upload retention, deletion, checksum, backup, privacy/legal policy, access review, and cross-service path test. |
| Edge and auth | Container Apps managed ingress with a dedicated `oauth2-proxy` workload while forward auth remains; preserve Google/Spotify auth and exact route contracts. DNS stays outside application-resource lifecycle. | Named DNS executor and OAuth-console owners, recovery boundary, parallel callback/certificate proof, headers/cookies/CORS/health/MCP conformance. |
| IaC | Bicep with separate bootstrap/application layers, OIDC-separated preview/apply identities, reviewed `what-if`, drift/rollback runbooks, and tests beyond preview. | Exact module/resource design, least-privilege role review, deterministic preview, imperative Entra/destructive-operation controls, and no-apply verification. |
| Database identity | Runtime DML and migration DDL roles; begin with a Key Vault-referenced password. Defer Entra DB auth until pooled-token renewal is tested. | Least-privilege review, migration-process test, secret-rotation runbook, or an accepted Entra renewal plan. |
| Frontend contract | Static Web Apps, versioned REST, generated OpenAPI TypeScript types, thin auth/transport layer, and route-group migration. | Deterministic generation/drift gate, complete route/schema inventory, origin/cookie/CORS decision, parity and rollback tests. |
| Packaging | Direct package-scoped root `uv.lock` synchronization in a multi-stage build. | Pinned uv/base/app digests, locked production-only closure, strict root `.dockerignore`, build-context tests, provenance/SBOM evidence, and cache-locality proof. |
| Post-write rollback | Forward recovery in Azure; DigitalOcean is not a writable fallback after the first Azure write. | Restore and application-revision rehearsal, upload/job reconciliation, explicit first-write go/no-go, owner-approved loss policy for any exceptional return to DigitalOcean. |
| Soak and deletion | Seven full days after Azure serves production traffic and writes, with DigitalOcean powered and write-fenced. Deletion remains a separately authorized operation. | Seven consecutive passing 24-hour periods, error/data/auth/MCP/collector/RPO/RTO thresholds, retention expiry, restore proof, dependency inventory, soak-exit approval, and named deletion approver. |
| Observability | Redacted logs and metrics with 30-day retention; traces only after PII/cost approval. | Accepted field policy, ingestion estimate, alert thresholds, and synthetic-check evidence. |

Ticket-specific repository validation for this Accepted record includes link validation, ADR
number/index/status checks, `git diff --check`, and the canonical agent-contract suite. Passing
those checks validates the decision package's structure; it does not validate Azure or production.

## Rollback / revisit trigger

Amend or supersede this ADR when any of these occur:

- MCP clients cannot operate correctly behind the 240-second Container Apps limit.
- Required RPO/RTO, availability, residency, quota, or budget makes the chosen target infeasible.
- Upload privacy/retention requirements rule out Azure Files or require a Blob abstraction first.
- The accepted authentication, frontend-origin, public MCP/API, or data contract changes.
- Measured load invalidates the PostgreSQL fallback, compute sizing, or cost model.
- The Azure-only target, LARP Bicep precedent, or Bicep operational controls change materially.
- Comparable profiling and Rust proof evidence selects a backend language and rewrite boundary.
- Azure service retirement, regional availability, pricing, or security guidance changes
  materially.

Revisit does not authorize production mutation. Implement a superseding accepted decision and a
separately approved migration/rollback plan.

## Related decisions

- [ADR 0001 - Use merge commits by default for pull requests](0001-pull-request-merge-method-policy.md)
- SPM-20 supplies the dated estate baseline.
- SPM-6 must provide MCP compatibility evidence before the Container Apps API/MCP release.
- SPM-10 owns the scoped React replacement.
- SPM-21 owns the accepted architecture implementation plan and infrastructure delivery.
- SPM-25 owns upload retention and storage decisions.
- SPM-26 owns production backup, restore, RPO, and RTO evidence.
- SPM-30 preserves the separation between repository delivery and manual production deployment.
- SPM-34 owns provider-account audit evidence without broadening this record's access authority.
