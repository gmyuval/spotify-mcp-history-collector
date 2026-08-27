# SPM-4 Azure architecture evidence - 2026-08-25 UTC

This dated artifact supports the Accepted ADR for SPM-4. It records volatile repository, service,
region, and public-price evidence separately so the ADR can remain a durable decision. It grants no
Azure, deployment, production, credential, provider, migration, or deletion authority.

Evidence labels:

- **Measured** - directly observed in the named repository revision, sanitized SPM-20 capture, or
  official source.
- **Inferred** - a conclusion from measured facts; it still needs a named validation gate.
- **Unresolved** - intentionally not observed, not published, or outside the session authority.

## Repository basis

- **Measured:** repository `origin/main` was
  `137dd54f0a82b21759ce3e9bb506204314f202a8` after a fresh fetch.
- **Measured:** the sanitized production and provider capture is
  [SPM-20 live-estate baseline](spm-20-live-estate-baseline.md), commit
  `dee0139e0b397b980805aac0ecc0c4937d403a15` on its issue branch.
- **Measured:** `docker-compose.prod.yml` defines API, collector, frontend, Explorer,
  `oauth2-proxy`, and Caddy containers. API and collector mount the same `upload_data` volume;
  Caddy has replaceable data/config volumes. PostgreSQL and Valkey are external connection URLs.
- **Measured:** `deploy/Caddyfile` distinguishes public health, JWT application routes, Bearer MCP
  routes, and Google-forward-authenticated admin/Explorer routes.
- **Measured:** `services/api/src/app/main.py` mounts FastMCP at `/mcp/v1`.
  `services/api/src/app/mcp/mcp_server.py` configures stateless HTTP and JSON responses and uses
  private FastMCP internals for compatibility handlers.
- **Measured:** `services/collector/src/collector/runloop.py` is a continuous loop.
  `services/api/src/app/admin/router.py` writes upload paths and
  `services/collector/src/collector/zip_import.py` later reads those paths, creating a shared
  filesystem contract.
- **Measured:** `services/api/src/app/dependencies.py` and
  `services/shared/src/shared/cache/postgres_backend.py` provide a PostgreSQL fallback when Valkey
  is absent.
- **Measured:** the service Dockerfiles use service-scoped build contexts and requirements files;
  the repository uv workspace and `uv.lock` are outside those contexts. No `.dockerignore` exists.
- **Measured:** the current deployment stops the collector, applies Alembic upgrades, and has no
  automated database downgrade.
- **Measured:** SPM-20 recorded about 10.2 million rows, a 3.39-GB PostgreSQL database, one retained
  2.6-MB upload, and USD 108/month of recurring DigitalOcean core cost in July 2026.

## Official Azure constraints

Sources were read on 2026-08-25 UTC and the regional pricing and capability evidence was refreshed
on 2026-08-26 UTC.

| Area | Measured constraint | Primary source |
|---|---|---|
| Container Apps ingress | HTTP/1.1, HTTP/2, WebSocket, and gRPC are supported; the request timeout is 240 seconds. | [Ingress overview](https://learn.microsoft.com/en-us/azure/container-apps/ingress-overview) |
| Container Apps scaling | Default minimum is zero and maximum is ten. A minimum of one keeps an instance running; an app with no ingress, minimum replica, or scale rule cannot start. | [Set scaling rules](https://learn.microsoft.com/en-us/azure/container-apps/scale-app) |
| Revisions | Revisions are immutable. Single-revision mode supports zero-downtime replacement; multiple-revision mode supports traffic splitting and revision rollback. | [Revisions](https://learn.microsoft.com/en-us/azure/container-apps/revisions) |
| Jobs | Jobs are finite executions triggered manually, on a schedule, or by events, which does not match the current continuous collector without redesign. | [Jobs](https://learn.microsoft.com/en-us/azure/container-apps/jobs) |
| Networking | A Container Apps environment uses a dedicated subnet; the networking configuration and subnet cannot be changed after environment creation. | [Networking](https://learn.microsoft.com/en-us/azure/container-apps/networking) |
| Private ingress | A private endpoint has DNS requirements and attracts the Dedicated Plan Management meter in addition to endpoint costs. | [Private endpoints and DNS](https://learn.microsoft.com/en-us/azure/container-apps/private-endpoints-with-dns) |
| Shared storage | Container Apps can mount Azure Files; the environment storage definition uses a storage-account key and supports Azure Files shares rather than arbitrary object storage. | [Azure Files mounts](https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts-azure-files) |
| Revisions and storage | Container-local ephemeral storage is revision/replica scoped and is not a durable upload target. | [Storage](https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts) |
| PostgreSQL recovery | Flexible Server supports point-in-time restore; restore creates a new server. Backup retention is configurable from 7 to 35 days. | [Backup and restore](https://learn.microsoft.com/en-us/azure/postgresql/backup-restore/concepts-backup-restore) |
| PostgreSQL HA | Burstable compute does not support high availability; HA requires General Purpose or Memory Optimized compute and additional capacity. | [Configure HA](https://learn.microsoft.com/en-us/azure/postgresql/high-availability/how-to-configure-high-availability) |
| PostgreSQL Entra auth | Managed identities are supported, but access tokens expire; managed-identity tokens can be valid for up to 24 hours and user tokens for up to one hour. | [Microsoft Entra authentication](https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/concepts-azure-ad-authentication) |
| Image pull | Container Apps can pull from ACR with a managed identity and `AcrPull`. | [Managed-identity image pull](https://learn.microsoft.com/en-us/azure/container-apps/managed-identity-image-pull) |
| Secrets | Container Apps can reference Key Vault secrets using a managed identity and Key Vault RBAC. | [Manage secrets](https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets) |
| CI identity | GitHub Actions can exchange its OIDC token for an Azure federated identity rather than storing a client secret. | [GitHub OIDC in Azure](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-azure) |
| Static frontend | Static Web Apps supplies managed static delivery and integrated deployment environments; its auth/origin behaviour still requires application-specific validation. | [Static Web Apps overview](https://learn.microsoft.com/en-us/azure/static-web-apps/overview) |
| Cache product lifecycle | Azure Cache for Redis tiers are retiring and new-customer creation is restricted; Azure Managed Redis is the successor. | [Retirement FAQ](https://learn.microsoft.com/en-us/azure/azure-cache-for-redis/retirement-faq), [Azure Managed Redis](https://learn.microsoft.com/en-us/azure/redis/overview) |
| IaC state | Terraform's AzureRM backend stores remote state in Blob Storage and supports state locking; ownership, access, recovery, and force-unlock remain operational duties. | [AzureRM backend](https://developer.hashicorp.com/terraform/language/backend/azurerm), [state locking](https://developer.hashicorp.com/terraform/language/state/locking) |
| Bicep preview | Bicep uses Azure deployment history rather than client state. `what-if` previews can include false positives and require deployment permissions. | [Terraform and Bicep comparison](https://learn.microsoft.com/en-us/azure/developer/terraform/get-started/comparing-terraform-and-bicep), [Bicep what-if](https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/deploy-what-if) |
| uv packaging | uv supports locked/frozen container synchronization and deterministic exports. Docker recommends excluding irrelevant or sensitive build-context content. | [uv Docker guide](https://docs.astral.sh/uv/guides/integration/docker/), [uv export](https://docs.astral.sh/uv/reference/cli/), [Docker build cache/context](https://docs.docker.com/build/cache/optimize/) |
| Container Apps in Israel | The rendered Consumption-plan region selector lists and prices Israel Central: USD 0.000034 per active vCPU-second, USD 0.000004 per active GiB-second, and USD 0.40 per million requests at retrieval time. | [Container Apps pricing](https://azure.microsoft.com/en-us/pricing/details/container-apps/) |
| PostgreSQL in Israel | The rendered Flexible Server region selector lists Israel Central and displayed a B1ms compute price of USD 16.06/month at retrieval time. | [PostgreSQL Flexible Server pricing](https://azure.microsoft.com/en-us/pricing/details/postgresql/flexible-server/) |
| Israel PostgreSQL recovery | Israel Central supports zone-redundant and same-zone HA but not geo-redundant backup. | [PostgreSQL region capabilities](https://learn.microsoft.com/en-us/azure/postgresql/overview) |
| Israel regional resilience | Israel Central has availability zones but is not region-paired. A France contingency is not automatic replication or failover. | [Availability zones](https://learn.microsoft.com/en-us/azure/reliability/availability-zones-overview), [Azure region pairs](https://learn.microsoft.com/en-us/azure/reliability/regions-paired) |

## Region and public list-price snapshot

### 2026-08-26 Israel Central decision evidence

The current rendered official pricing selectors resolve an ambiguity in the earlier provider
capture: ordinary Azure Container Apps Consumption and PostgreSQL Flexible Server are both listed
and priced in Israel Central. The earlier West/North comparison remains useful historical option
evidence, but it no longer excludes Israel Central.

A local, interleaved TCP-connect probe from the current Israeli access path used 20 observations
per Azure regional monitoring endpoint and discarded the two highest and lowest values. It measured
an Israel Central median of about 3.8 ms and trimmed average of 4.1 ms, compared with Italy North at
48.4/48.7 ms and France Central at 52.8/52.8 ms. This is a point-in-time network observation, not an
application latency SLO or substitute for pre-apply and pre-cutover testing.

Using the same warm API/collector workload assumptions below, Israel Central's displayed Container
Apps rates produce USD 75.222/month of backend compute after the published grant. Adding the
displayed B1ms compute price of USD 16.06/month, the dated USD 5.067 ACR Basic planning assumption,
and USD 9 Static Web Apps yields an incomplete floor of about USD 105.35/month. PostgreSQL storage,
backups, Azure Files, traffic, DNS, private endpoints, monitoring ingestion, support, HA, taxes,
discounts, and contingency-region resources are excluded. This is not a quote or a production
sizing recommendation.

Israel Central is therefore the selected primary. France Central is an unprovisioned contingency,
chosen for target-service coverage, Bicep precedent, and recovery maturity rather than its small
latency difference from Italy North. Because Israel Central has no PostgreSQL geo-redundant backup,
the contingency does not establish cross-region data recovery; that requires a separate accepted
plan.

### 2026-08-25 West/North alternative snapshot

SPM-20's sanitized subscription capture found viable compute, Container Apps, and PostgreSQL
inventory in West Europe and North Europe. It did not find the required PostgreSQL tiers in Germany
West Central. No authenticated provider re-query was authorized for SPM-4, so current quota,
allocation, discounts, reservations, agreement, and invoice currency remain **Unresolved**.

The unauthenticated
[Azure Retail Prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices)
was queried on 2026-08-25 UTC. Values below are USD consumption list prices, use 730 hours/month,
and exclude tax, support, bandwidth, DNS, private endpoints, backups, Log Analytics ingestion,
availability-equivalent redundancy, and customer discounts.

Reproduce the queries against
`https://prices.azure.com/api/retail/prices?api-version=2023-01-01-preview&currencyCode=USD`.
URL-encode each exact `$filter` below and follow `NextPageLink` until empty. Select the named meter;
similar product families in the broader result are not interchangeable.

| Purpose | Exact `$filter` in addition to `priceType eq 'Consumption'` | Selected meter and rate |
|---|---|---|
| West Europe VM | `serviceName eq 'Virtual Machines' and armRegionName eq 'westeurope' and armSkuName eq 'Standard_B2s'` | `Virtual Machines BS Series` / `B2s`, USD 0.048 per hour, effective 2025-10-01. |
| North Europe VM | `serviceName eq 'Virtual Machines' and armRegionName eq 'northeurope' and armSkuName eq 'Standard_B2s'` | `Virtual Machines BS Series` / `B2s`, USD 0.045 per hour, effective 2025-10-01. |
| West Europe PostgreSQL compute | `serviceName eq 'Azure Database for PostgreSQL' and armRegionName eq 'westeurope' and armSkuName eq 'B1MS'` | `Flexible Server Burstable BS Series Compute` / `B1MS`, USD 0.0199 per hour, effective 2021-12-01. |
| North Europe PostgreSQL compute | `serviceName eq 'Azure Database for PostgreSQL' and armRegionName eq 'northeurope' and armSkuName eq 'B1MS'` | Same product/meter, USD 0.018 per hour, effective 2021-12-01. |
| West Europe PostgreSQL storage | `serviceName eq 'Azure Database for PostgreSQL' and armRegionName eq 'westeurope' and productName eq 'Azure Database for PostgreSQL Flex Server Storage' and skuName eq 'Storage'` | `Storage Data Stored`, USD 0.1369 per GB/month, effective 2021-06-01. |
| North Europe PostgreSQL storage | `serviceName eq 'Azure Database for PostgreSQL' and armRegionName eq 'northeurope' and productName eq 'Azure Database for PostgreSQL Flex Server Storage' and skuName eq 'Storage'` | `Storage Data Stored`, USD 0.1265 per GB/month, effective 2021-06-01. |
| Managed disk, each region | `serviceName eq 'Storage' and armRegionName eq '<region>' and skuName eq 'E6 LRS' and meterName eq 'E6 LRS Disk'` | `Standard SSD Managed Disks` / `E6 LRS Disk`, USD 4.80 per month, effective 2019-01-01. Exclude mount and operation meters. |
| ACR, each region | `serviceName eq 'Container Registry' and armRegionName eq '<region>' and skuName eq 'Basic'` | `Container Registry` / `Basic Registry Unit`, USD 0.1666 per day, effective 2018-01-01. |
| Container Apps, each region | `serviceName eq 'Azure Container Apps' and armRegionName eq '<region>' and skuName eq 'Standard'` | `Standard vCPU Active Usage` and `Standard Memory Active Usage`, effective 2022-06-01. West: USD 0.000034/vCPU-second and USD 0.000004/GiB-second. North: USD 0.000024 and USD 0.000003. |
| Static Web Apps | `productName eq 'Static Web Apps' and armRegionName eq 'westeurope' and skuName eq 'Standard' and meterName eq 'Standard App'` | `Standard App`, USD 9 per month, effective 2021-05-01. |

| Component | West Europe | North Europe | Notes |
|---|---:|---:|---|
| Linux Standard B2s | USD 0.048/hour | USD 0.045/hour | VM compute only. |
| Standard SSD E6 | USD 4.80/month | USD 4.80/month | Representative 64-GiB OS/data disk meter. |
| PostgreSQL Flexible B1ms | USD 0.0199/hour | USD 0.018/hour | Burstable, no HA; storage separate. |
| PostgreSQL, B1ms plus 60 GB | about USD 22.74/month | about USD 20.73/month | Planning floor, not availability-equivalent production sizing. |
| ACR Basic | USD 0.1666/day | USD 0.1666/day | About USD 5.07/month before excess storage/egress. |
| Container Apps active vCPU | USD 0.000034/vCPU-second | USD 0.000024/vCPU-second | Public active-use meter. |
| Container Apps active memory | USD 0.000004/GiB-second | USD 0.000003/GiB-second | Public active-use meter. |

### Comparable planning floors

The [Container Apps pricing page](https://azure.microsoft.com/en-us/pricing/details/container-apps/)
published a monthly Consumption-plan grant of 180,000 vCPU-seconds, 360,000 GiB-seconds, and two
million requests at retrieval time. Request charges are omitted because no request count is
assumed. The calculation optimistically assigns the full subscription grant to this application;
a shared or already-consumed grant raises the total. The calculations are:

```text
month_seconds = 730 * 3,600 = 2,628,000

warm_backend_vcpu_seconds = (0.5 API + 0.25 collector) * month_seconds = 1,971,000
warm_backend_memory_seconds = (1.0 API + 0.5 collector) * month_seconds = 3,942,000
billable_vcpu_seconds = 1,971,000 - 180,000 = 1,791,000
billable_memory_seconds = 3,942,000 - 360,000 = 3,582,000

West backend compute = 1,791,000 * 0.000034 + 3,582,000 * 0.000004 = USD 75.222
North backend compute = 1,791,000 * 0.000024 + 3,582,000 * 0.000003 = USD 53.730

West PostgreSQL = 730 * 0.0199 + 60 * 0.1369 = USD 22.741
North PostgreSQL = 730 * 0.0180 + 60 * 0.1265 = USD 20.730
ACR = (730 / 24) * 0.1666 = USD 5.067

West ACA-backed hybrid = 75.222 + 22.741 + 5.067 + 9 = USD 112.030
North ACA-backed hybrid = 53.730 + 20.730 + 5.067 + 9 = USD 88.527

West warm web increment = 0.25 * month_seconds * 0.000034
                           + 0.5 * month_seconds * 0.000004 = USD 27.594
North warm web increment = 0.25 * month_seconds * 0.000024
                            + 0.5 * month_seconds * 0.000003 = USD 19.710

West all-ACA warm web = 112.030 - 9 + 27.594 = USD 130.624
North all-ACA warm web = 88.527 - 9 + 19.710 = USD 99.237

West VM landing = 730 * 0.048 + 4.80 + 22.741 + 5.067 = USD 67.648
North VM landing = 730 * 0.045 + 4.80 + 20.730 + 5.067 = USD 63.447
```

| Topology | West Europe | North Europe | What is included and omitted |
|---|---:|---:|---|
| Compose VM landing | about USD 67.65/month | about USD 63.45/month | B2s, E6, B1ms PostgreSQL/60 GB, Basic ACR. Excludes backup, traffic, logs, support, and HA. |
| ACA-backed hybrid | about USD 112.03/month | about USD 88.53/month | Always-active API (0.5 vCPU/1 GiB) and collector (0.25 vCPU/0.5 GiB), B1ms PostgreSQL, ACR, and USD 9 Static Web Apps; applies published compute grants. Excludes current auth/edge migration, shared storage, logs, and HA. |
| All-ACA control, warm web | about USD 130.62/month | about USD 99.24/month | Adds a 0.25-vCPU/0.5-GiB React static-server container with `minReplicas: 1` and removes Static Web Apps. Still excludes the auth/edge implementation, shared storage, logs, and HA. |
| All-ACA control, scale-to-zero web | Load-dependent; no fixed floor claimed | Load-dependent; no fixed floor claimed | React container at `minReplicas: 0` adds request cold starts and cannot be priced without request/duty-cycle evidence. API and collector remain warm. |
| Hybrid with VM backend and static React | about USD 76.65/month | about USD 72.45/month | Compose VM landing plus Standard Static Web Apps. Preserves current auth/edge/worker/upload topology. |
| Hybrid with ACA backend and static React | Same as ACA-backed hybrid row | Same as ACA-backed hybrid row | The API and collector remain warm, so no scale-to-zero saving is assumed. |

The ACA figures are workload assumptions, not measured utilization. API and collector minimum
replicas eliminate their cold-start path but also eliminate scale-to-zero savings. Static Web Apps
does not have an application-container cold start. An all-ACA web container either remains warm at
the modeled cost or introduces unmeasured request cold starts. A VM remains warm and
operator-managed. Container Apps reduces host operations but adds environment, identity, ingress,
storage-mount, revision, and observability operations. The hybrid retains more simultaneous
topology during migration.

## Option-specific evidence conclusions

- **Inferred - VM:** lowest behavioural change, but retains single-host availability and
  patch/backup/capacity work and creates a strong risk that the managed split is postponed. The
  owner rejected it as a standing target or fallback.
- **Accepted - Container Apps:** the API/MCP Container App starts at `minReplicas: 0` and
  `maxReplicas: 1`; the collector runs one finite scheduled Container Apps Job every ten minutes.
  Revision rollback and managed identity improve application operations. The 240-second ingress
  timeout, cold starts, auth edge, transient Blob handoff, and finite-job lifecycle remain release
  gates; a failed gate blocks or triggers an ADR amendment rather than silently switching to a VM.
- **Accepted - hybrid product shape:** Static Web Apps separates React delivery from backend
  compute, while API/MCP and collector use workload-specific Container Apps. It costs more topology
  and origin/auth validation but supports contract-first staged replacement.
- **Accepted - packaging:** direct package-scoped synchronization from the root `uv.lock` is the
  production dependency boundary after a strict root `.dockerignore`, context tests, immutable uv
  0.12.3 and base-image pins, and multi-stage production-only installation are implemented.
- **Inferred - cache:** PostgreSQL fallback should be benchmarked before adding a managed cache,
  especially because the legacy Azure Cache product is retiring.

## Local Bicep and backend-language evidence

- **Measured:** the sibling LARP Store checkout was clean at
  `89feabb9d096157365fc0a799d1793057d512189`. It contains 18 Bicep/Bicep-parameter files covering
  subscription bootstrap, networking, ACR, Key Vault, PostgreSQL Flexible Server, observability,
  Container Apps, migration jobs, application workloads, and shared DNS.
- **Measured:** its workflows separate read/preview and apply identities, use OIDC, run pull-request
  `what-if`, deploy immutable application revisions, verify the serving commit, and require typed
  confirmation for DNS writes.
- **Measured:** its operating documents record ARM incremental non-deletion, imperative Entra/OIDC
  reconciliation, a provider-noise baseline, targeted guards beyond `what-if`, application traffic
  rollback, prior-template reapplication, and database restore. No Terraform source or historical
  Terraform precedent was found in the examined local repository history.
- **Inferred:** Bicep is the lower-complexity fit for this deliberately Azure-only target only when
  those controls are adopted; native tooling does not remove imperative or destructive-operation
  ownership.
- **Measured:** the current Python backend has broad functional tests but no dedicated profiling or
  benchmark harness. Spotify latency/rate limiting, PostgreSQL query and connection behaviour,
  sequential ORM work, ZIP parsing/normalization, and current resource limits are candidate costs;
  none is established as the dominant bottleneck.
- **Accepted evidence rule:** profile the API/MCP, collector, database, and import paths with a
  production-shaped synthetic or sanitized workload, then compare a representative Rust
  proof-of-value under the same semantic and failure-recovery contract. Missing or incomparable
  evidence blocks a language choice rather than defaulting to Python.

## Unresolved evidence

1. Current subscription policy, discount, quota, approved SKUs, allocation, and provider invoice.
2. Final residency, budget, uptime, maintenance, RPO, and RTO requirements and target-subscription
   availability for the selected Israel Central SKUs.
3. Maximum real MCP/SSE connection duration and supported-client reconnect behaviour.
4. DNS registrar, Google OAuth, and Spotify OAuth ownership and parallel-callback capability.
5. Upload retention, deletion, checksum, backup, legal, and privacy requirements.
6. Production load and cost of the PostgreSQL fallback without Valkey.
7. Log/trace PII policy, retention, ingestion volume, alerts, and synthetic-check budget.
8. The exact Spotify Bicep module design, least-privilege assignments, provider-noise baseline,
   imperative Entra reconciliation, and recovery runbooks. The LARP precedent informs but does not
   implement those controls here.
9. A tested post-first-write reverse synchronization path. The Accepted ADR deliberately selects
   forward recovery in Azure rather than pretending this path exists.
10. Comparable profiling and Rust proof-of-value results, and the dedicated accepted language ADR.
