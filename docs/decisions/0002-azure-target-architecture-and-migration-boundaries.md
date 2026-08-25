# ADR 0002 - Choose the Azure target architecture and migration boundaries

Date: 2026-08-25 (UTC)
Status: Proposed
Decision owners: Yuval Moran
Linear issue: [SPM-4](https://linear.app/stratex/issue/SPM-4/record-the-product-and-azure-target-architecture-and-migration-boundaries)

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
list-price calculations for this proposal are pinned in the
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

This record is a decision package. While its status is **Proposed**, it changes no architecture and
grants no implementation, Azure, migration, deployment, production, credential, DNS, OAuth, or
deletion authority.

## Decision drivers

- Preserve existing API, MCP, authentication, collection, and data contracts during the platform
  move; replace the Python UIs only under their separately approved work.
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
| Split API, worker, and web into Azure Container Apps | Immutable revisions, traffic-controlled revision rollback, managed ingress/TLS, managed identities, per-service scaling, and internal service routing. React is served by its own static-server container. | The 240-second ingress timeout is unproven for current MCP clients. API and continuous collector need at least one replica. A web minimum of one adds the dated warm-container cost; zero permits unmeasured request cold starts. Shared uploads need Azure Files or application changes. Auth/cookie/routing behaviour changes when Caddy or `oauth2-proxy` moves. | Application revisions can roll back quickly; data rollback remains separate. This control is less attractive than Static Web Apps and must still pass MCP, upload, web cold-start, and auth gates. |
| Conditional hybrid | React on Static Web Apps; managed PostgreSQL; API, collector, and the current auth/edge either on Container Apps or retained together on a VM. Static delivery has no application-container cold start; API and collector remain warm. | Carries more topology during transition and requires explicit same-origin, CORS, cookie, callback, routing, storage, and observability validation. The dated evidence models both VM-backed and ACA-backed hybrid costs. | Each tier can move independently. The VM path remains a fallback if Container Apps gates fail. |
| In-place modernization | Keeps the Python API, collector, auth, and MCP contracts while changing packaging and infrastructure. | Retains known FastMCP private-internal coupling and the current UIs until their own tickets change them. | Narrow diffs and existing contract tests provide the best application rollback. |
| Partial rewrite | Replaces only the already-scoped Python UIs with React while preserving backend contracts. | Requires an explicit browser/API origin and authentication design plus a complete frontend API inventory. | Frontend can revert independently if the existing API contract is preserved. |
| Full rewrite | Could theoretically simplify every layer at once. | Simultaneously changes UI, MCP, auth, worker, storage, packaging, and migration contracts without evidence that this breadth is necessary. It has the weakest review and rollback posture. | Not acceptable under this proposal. A separate accepted plan and evidence that narrower options cannot meet requirements would be required. |

### Infrastructure as code

| Option | Benefits | Costs and risks |
|---|---|---|
| Terraform | Portable workflow and a mature plan/apply model. Azure Blob remote state provides locking and consistency. | Requires bootstrap, sensitive-state access control, recovery, drift, and force-unlock ownership. The claimed organization default has not been verified. |
| Bicep | Azure-native deployments, no stored client state, deployment history, and `what-if` previews. | `what-if` can produce false positives and requires deployment permissions. SPM-4 names a product-repository precedent, but no Bicep file or visible Git-history precedent was found in this repository. |

Select Terraform, subject to owner confirmation of the organization-wide Terraform default before
acceptance. The product-repository Bicep precedent named by SPM-4 was not found and remains a
required evidence gap, but an unlocated precedent does not outweigh the stated organization
default. Store state in a dedicated, access-controlled Azure Storage account and container outside
the application resource groups. Root owns plan review and drift reconciliation; a separately
authorized root apply uses an environment-constrained federated identity. State recovery and any
force-unlock require a named human owner. If the claimed convention is disproved before acceptance,
revise this proposal rather than silently switching tools.

### Production dependency packaging

| Option | Benefits | Costs and risks |
|---|---|---|
| Direct `uv.lock` synchronization in container builds | Strongest single-source dependency model. | Current service-scoped contexts lack the root workspace files. A broader context needs a reviewed root `.dockerignore`, explicit workspace packaging, and a privacy/provenance assessment. |
| Hashed, service-scoped pip-compatible exports generated from `uv.lock` | Preserves narrow contexts while making `uv.lock` authoritative; provides a low-change transition from current images. | Generated files can drift unless CI regenerates them and fails on a diff. |

## Decision

If accepted, adopt the following target and boundaries.

### Product and compute target

1. Modernize the API, collector, authentication boundary, and MCP implementation in place. Do not
   combine the platform move with a full rewrite.
2. Replace only the already-scoped Python UIs with React. Host React on Azure Static Web Apps only
   after the browser/API origin, CORS, cookie, OAuth callback, and rollback contracts are accepted
   and tested.
3. Use Azure Database for PostgreSQL Flexible Server as the durable database target. Do not add a
   managed Redis dependency initially; benchmark the existing PostgreSQL fallback first. If a
   dedicated cache later becomes necessary, evaluate Azure Managed Redis against the service
   guidance current at that later decision.
4. Store immutable application images in Azure Container Registry. Pin uv, base-image digests, and
   application-image digests, and retain build provenance.
5. Make the backend compute target conditional on SPM-6 evidence:
   - Prefer Azure Container Apps for the API and continuous collector, each with a minimum of one
     replica, only if MCP session/reconnect behaviour passes behind the documented 240-second
     ingress timeout and the upload and authentication gates pass.
   - Otherwise use one Azure VM running the current Compose topology as the reversible landing
     zone. Keep the Container Apps split as a later migration rather than forcing a protocol or
     storage rewrite into the initial move.

The conditional target is intentional. Acceptance chooses the decision rule and gates; it does not
pretend the missing MCP evidence already exists.

### Target surface map

| Current deployable or durable surface | Target and boundary |
|---|---|
| FastAPI API and `/mcp/v1` | Modernize in place. Run on Container Apps with `minReplicas: 1` after the MCP, auth, and upload gates pass; otherwise run unchanged in the Compose VM landing zone. |
| Continuous collector | Modernize in place. Run as a continuously available Container App with `minReplicas: 1`, not as an event job, after worker and storage rehearsal; otherwise retain it in Compose. |
| Admin and Explorer Python UIs | Replace, in their own SPM-10 slices, with one strict TypeScript + React application. Keep the Python UIs available until route-by-route parity and rollback are proven. |
| React application | Prefer Static Web Apps after the origin/auth decision. Pin an immutable artifact and keep its deployment independently reversible from API and cloud cutover. |
| `oauth2-proxy` and application auth | Preserve the split and current Google/Spotify flows during migration. Keep `oauth2-proxy` with Caddy on the VM path; prove or separately design its equivalent before an ACA edge replaces it. |
| Caddy reverse proxy and ingress | Retain on the VM path. On the ACA path, replace only after exact route, header, TLS, callback, auth, health, and MCP conformance. |
| PostgreSQL | Move to Flexible Server through rehearsed backup/restore or logical migration selected under SPM-25/26. Keep schema and Alembic history; separate runtime DML from migration DDL. |
| Valkey | Omit initially and use the existing PostgreSQL fallback after load proof. If a dedicated cache is later required, evaluate Azure Managed Redis in a separate cost/operations slice. |
| Uploaded export ZIPs | Mount a shared Azure Files target for the lowest-change path after retention/privacy acceptance, or introduce a separately planned Blob abstraction before migration. Never leave the API and collector with different path authorities. |
| Caddy TLS/config volumes | Treat as replaceable configuration, not migrated business data. Re-issue certificates and preserve reviewed routing configuration through IaC or immutable deployment assets. |
| Database-backed product/admin logs | Retain initially with redaction and retention review. Add redacted structured stdout and Azure Monitor alerts without copying unrestricted PII into a second store. |
| Container images | Build once, record provenance, publish to ACR, and deploy by immutable digest. Do not rebuild during rollback. |
| Alembic migrations | Run as one explicitly invoked, monitored migration process with its own identity before application traffic is admitted. Stop on failure; do not assume an automatic downgrade. |

### Region, availability, and cost boundary

Select West Europe as the proposed primary region because it was viable in the sanitized
subscription capture and is the nearer general candidate for the current owner/user geography.
North Europe is the explicit fallback if current subscription quota, SKU allocation, policy,
residency, measured latency, or an accepted budget makes West Europe unsuitable. Germany West
Central is not a candidate on the current evidence. Re-query the subscription and obtain the owner
requirements before acceptance and again before apply.

Create separate production and non-production application resource groups. Production owns its own
VNet, Container Apps environment or VM, PostgreSQL server, durable storage, Key Vault, identities,
and monitoring boundary. ACR may be shared only for immutable, environment-neutral images and
least-privilege pulls. Keep the Terraform state account in a separate bootstrap boundary. Keep DNS
outside the application resource group. The product owner owns DNS authorization and delegates only
the exact application records to a separately reviewed Terraform plan; the existing zone and
registrar are never imported or deleted implicitly. Acceptance must confirm who can execute that
authorization and its recovery boundary.

Use a cost-conscious single-zone PostgreSQL baseline with 14-day point-in-time restore and no HA,
matching rather than overstating the current estate's availability. This is the recommendation,
not permission to accept an unstated RPO/RTO. Require weekly automated backup evidence and a
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
- Keep Caddy and `oauth2-proxy` together with the backend on the VM landing path. Do not consolidate
  or replace authentication in the platform migration without a separate accepted decision.
- For the Container Apps path, prove custom-domain certificate issuance, callback URLs, headers,
  cookie scope, same-origin/CORS behaviour, Google forward-auth routes, JWT routes, Bearer MCP
  routes, WebSocket/HTTP behaviour, and the 240-second timeout before cutover.
- Retain the database-backed product/admin log path initially. Emit redacted structured stdout to
  Azure Monitor/Log Analytics with a proposed 30-day retention. Alert on health, error rate,
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

Use reproducible, hashed, production-only service exports generated from `uv.lock` as the initial
production transition. CI must regenerate the exports with the repository-pinned uv and fail if
the committed artifacts drift. Production images must not install development dependency groups.

Direct workspace synchronization can supersede the exports after a reviewed build-context design
adds a strict root `.dockerignore`, proves that credentials, personal data, local caches, and other
repository-only files cannot enter the context, and preserves service-level cache locality.

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
   traffic to the still-authoritative DigitalOcean estate. After it, this proposal selects forward
   recovery in Azure: fence Azure writes, roll the application to a qualified image revision or
   restore PostgreSQL to a new Flexible Server, reconcile uploads/jobs, and resume only after the
   same gates pass. DigitalOcean becomes a write-fenced archive, not an automatic traffic fallback.
   Returning writes to DigitalOcean after that point is allowed only under a new accepted
   reverse-migration plan, or with explicit owner acceptance that every Azure-window write will be
   lost. No untested reverse synchronization is assumed.
7. **Soak.** Keep DigitalOcean powered, write-fenced, monitored, and recoverable for an
   owner-selected duration. Exit only on explicit error-rate, data-reconciliation, RPO, RTO, auth,
   and MCP thresholds.
8. **Retire separately.** DigitalOcean deletion is a distinct destructive operation requiring
   owner authorization after reconciliation, restore proof, retention expiry, DNS/callback
   cleanup, and proof that shared project, VPC, firewall, DNS, or backup resources are not being
   deleted. A merge or successful cutover never authorizes retirement.

### Action and authority classification

| Class | Examples | Required authority |
|---|---|---|
| Plan-only | ADRs, IaC source, dependency exports, runbooks, synthetic contract tests, cost models, and non-production rehearsal design. | Repository authority and every applicable accepted plan-first decision. No cloud mutation. |
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
- No broad Python backend rewrite or collector replacement is selected.
- No promise is made that Container Apps, scale-to-zero, Entra PostgreSQL authentication, Azure
  Files, managed Redis, HA, or a specific region is suitable before its named evidence gate.
- No merge or successful Azure soak authorizes DigitalOcean decommissioning.

## Consequences

- The platform can move without combining infrastructure, frontend, MCP, authentication, storage,
  and data rewrites into one irreversible event.
- Container Apps remains the preferred managed target only if observable protocol and storage
  gates pass; the VM landing path is a deliberate fallback, not a failure to decide.
- API and collector retain warm capacity, so the design does not assume scale-to-zero savings.
- Managed PostgreSQL improves service ownership and recovery tooling, but production HA materially
  increases cost and remains an owner RPO/RTO choice.
- Omitting managed Redis reduces migration dependencies but requires measured PostgreSQL-fallback
  capacity before cutover.
- Service-scoped dependency exports temporarily duplicate generated metadata in exchange for a
  narrow, auditable Docker build context.
- Azure Files minimizes application change but does not meet a managed-identity-only ideal; Blob
  Storage remains a future, separately planned abstraction.
- The proposal preserves the current authentication and public MCP/API boundaries; it therefore
  does not silently solve or widen their known modernization work.
- Cost projections remain ranges until subscription, availability, utilization, data, recovery,
  and monitoring requirements are measured.

## Validation and owner decision package

The recommendation is cohesive: West Europe; Terraform; in-place backend modernization; React on
Static Web Apps; managed PostgreSQL without HA initially; PostgreSQL cache fallback; immutable ACR
images; generated service-scoped dependency exports; and Container Apps only after its named gates,
otherwise the Compose VM landing path. Owner acceptance requires the following visible choices and
evidence:

| Choice | Recommendation and trade-off | Evidence required before acceptance |
|---|---|---|
| Compute | Accept the ACA-after-gates/VM-fallback rule and reject the all-ACA web control in favor of Static Web Apps. ACA reduces host operations and adds revision rollback; VM minimizes behavioural change and preserves the simplest fallback. | SPM-6 long-lived MCP/reconnect soak, upload mount proof, auth/route parity, worker liveness, web cold-start pressure test, and refreshed complete cost. |
| Region | West Europe primary; North Europe fallback. West Europe is recommended for expected geography, while North Europe's dated list-price floor is lower. | Residency and policy, measured latency, live subscription quote/quota/SKU availability, and approved budget. |
| Recovery and HA | Single-zone PostgreSQL, 14-day PITR, weekly backup evidence, quarterly restore rehearsal; pay for zone HA only if required RTO demands it. | Owner RPO/RTO/uptime/downtime, successful timed restore, and HA cost acceptance if triggered. |
| Storage | Azure Files for the lowest-change initial shared-path contract; Blob only through a separately planned abstraction. | Upload retention, deletion, checksum, backup, privacy/legal policy, access review, and cross-service path test. |
| Edge and auth | Preserve Caddy/`oauth2-proxy` on VM; reproduce exact routes before ACA replaces them. Preserve existing Google/Spotify auth. Product owner authorizes only exact application DNS records; the zone stays outside application-resource lifecycle. | Named DNS executor and OAuth-console owners, recovery boundary, parallel callback/certificate proof, headers/cookies/CORS/health/MCP conformance. |
| IaC | Terraform with isolated Blob state, OIDC plan/apply separation, root-owned plan/drift review, and human-owned recovery/force-unlock. | Confirm the organization convention; locate and compare the Bicep precedent; approve state owner and deterministic plan evidence. |
| Database identity | Runtime DML and migration DDL roles; begin with Key Vault password. Defer Entra DB auth until pooled-token renewal is tested. | Least-privilege review, migration-process test, secret-rotation runbook, or an accepted Entra renewal plan. |
| Frontend contract | Static Web Apps, versioned REST, generated OpenAPI TypeScript types, thin auth/transport layer, route-group migration. | Deterministic generation/drift gate, complete route/schema inventory, origin/cookie/CORS decision, parity and rollback tests. |
| Packaging | Hashed production-only service exports generated from `uv.lock`; direct workspace sync later after context review. | Pinned uv/base/app digests, export drift test, provenance/SBOM evidence, strict sensitive-context exclusion. |
| Post-write rollback | Forward recovery in Azure; DigitalOcean is not a writable fallback after the first Azure write. | Restore and application-revision rehearsal, upload/job reconciliation, explicit first-write go/no-go, owner-approved loss policy for any exceptional return to DigitalOcean. |
| Soak and deletion | Keep DigitalOcean powered and write-fenced through an owner-set soak. Delete only in a separately authorized operation. | Error/data/auth/MCP/RPO/RTO thresholds, retention expiry, restore proof, dependency inventory, and named deletion approver. |
| Observability | Redacted logs and metrics with 30-day retention; traces only after PII/cost approval. | Accepted field policy, ingestion estimate, alert thresholds, and synthetic-check evidence. |

Ticket-specific repository validation for this Proposed record includes link validation, ADR
number/index/status checks, `git diff --check`, and the canonical agent-contract suite. Passing
those checks validates the decision package's structure; it does not validate Azure or production.

## Rollback / revisit trigger

While Proposed, rollback is deletion or revision of this record before owner acceptance; no
architecture should have changed. After acceptance, amend or supersede this ADR when any of these
occur:

- MCP clients cannot operate correctly behind the 240-second Container Apps limit.
- Required RPO/RTO, availability, residency, quota, or budget makes the chosen target infeasible.
- Upload privacy/retention requirements rule out Azure Files or require a Blob abstraction first.
- The accepted authentication, frontend-origin, public MCP/API, or data contract changes.
- Measured load invalidates the PostgreSQL fallback, compute sizing, or cost model.
- The organization IaC convention or the missing Bicep precedent changes the IaC choice.
- Azure service retirement, regional availability, pricing, or security guidance changes
  materially.

Revisit does not authorize production mutation. Implement a superseding accepted decision and a
separately approved migration/rollback plan.

## Related decisions

- [ADR 0001 - Use merge commits by default for pull requests](0001-pull-request-merge-method-policy.md)
- SPM-20 supplies the dated estate baseline.
- SPM-6 must provide MCP compatibility evidence before the Container Apps compute path is selected.
- SPM-10 owns the scoped React replacement.
- SPM-21 owns the accepted architecture implementation plan and infrastructure delivery.
- SPM-25 owns upload retention and storage decisions.
- SPM-26 owns production backup, restore, RPO, and RTO evidence.
- SPM-30 preserves the separation between repository delivery and manual production deployment.
- SPM-34 owns provider-account audit evidence without broadening this record's access authority.
