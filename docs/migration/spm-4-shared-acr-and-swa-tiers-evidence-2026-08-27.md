# SPM-4 shared ACR and Static Web Apps tier evidence - 2026-08-27

This dated note supports the remaining cost posture in
[ADR 0002](../decisions/0002-azure-target-architecture-and-migration-boundaries.md). It answers two
bounded questions:

1. should Spotify MCP use an already-paid organization registry or own a registry; and
2. should the production frontend begin on Azure Static Web Apps Free or Standard?

It is plan-only evidence. The selections recorded below do not accept ADR 0002, change a
subscription, inspect Azure state, or authorize a deployment. Public Microsoft sources were retrieved at
`2026-08-27T08:02:25Z`. Sibling repositories were read locally at their pinned revisions; their
credentials, state, production data, and cloud resources were not accessed.

Owner evidence added after the comparison: on 2026-08-27 UTC the owner approved the neutral
organization-shared ACR recommendation, delegated responsibility for its implementation and
cross-repository ticketing to the root orchestrator, and selected Static Web Apps Free for the
initial pilot. This approval authorizes repository planning and delivery under each repository's
accepted gates; it does not authorize an Azure apply, production mutation, registry move, role
assignment, or registry deletion.

## Executive recommendation

### Container registry

Use **one organization-shared ACR as the target**, with one exception rule for a genuinely
incompatible tenant, residency, network-isolation, region-recovery, or scale boundary. At the
current three-product scale, a separate Spotify registry would add cost and operating surface
without enough isolation benefit to justify it. The shared registry must first be made a neutral
platform resource with an explicit owner, neutral resource group and IaC lifecycle,
repository-scoped ABAC, per-product monitoring, deletion separation, and a tested recovery
procedure. Neither inspected sibling supplies that ownership model today: Agrisense owns one
product-scoped Premium registry in its production resource group, while LARP owns a Basic registry
per product environment. Spotify therefore must not merely publish into the current Agrisense
resource lifecycle; adopting that already-paid registry requires a planned transfer to neutral
platform ownership and an ABAC migration.

A qualifying shared registry saves exactly the new Basic registry's fixed meter:
`(730 / 24) * $0.1666 = $5.0674/month`. The incremental Spotify registry cost is then `$0` while
the shared registry's included storage and throughput have headroom. Excess storage remains
`$0.10/GB-month`, so it is not automatically eliminated by sharing.

### Static Web Apps

Begin with **Free for the owner-approved 1-5-user production pilot**, then change the same resource
to Standard before an objective trigger is reached. This saves `$9.90/app-month` while the selected
separate ACA backend/authentication design does not need Standard-only SWA features. The pilot
accepts no SWA SLA and Free's hard service stop when the subscription-wide 100-GB allowance is
exhausted.

This is safe only with an SPM-6 gate because Azure does not document a native Static Web Apps
month-to-date subscription quota counter or an exact proactive quota alert. The per-resource
`BytesSent` metric can be observed and alerted, but it must be aggregated across all Free apps in
the subscription to approximate the shared monthly allowance. The official docs also do not
promise a zero-downtime Free-to-Standard change. Subscription inventory, static-only metric proof,
an early threshold, a rehearsed in-place plan change, and pre-authorized upgrade ownership are
therefore release conditions, not follow-up ideas.

## Evidence labels and pinned sources

- **Configured** means source code or workflow configuration expresses the behavior.
- **Exercised** means the repository's accepted current-state evidence records a live run or
  deployment. It is not fresh cloud verification.
- **Calculated** means arithmetic over quoted retail inputs.
- **Inferred** means a design conclusion from configured or official facts.
- **Unresolved** means the inspected primary sources do not establish the claim.

| Repository | Branch / upstream | Full HEAD | Status at revalidation |
|---|---|---|---|
| Spotify MCP SPM-4 worktree | `codex/spm-4-architecture-decision` / `origin/main` | `271b009cf3cb837f95dacab9d6db8d477b7da3ce` | Ahead 2, behind 0; pre-existing root-owned ADR/current-state/index modifications plus `.local-data` and dated untracked evidence preserved. |
| Agrisense | `main` / `origin/main` | `82e78a0f57ee84f2cc03094d9e8c9019916ff02b` | Clean; ahead 0, behind 0. |
| LARP Store | `main` / `origin/main` | `89feabb9d096157365fc0a799d1793057d512189` | Clean; ahead 0, behind 0. |

Only remote names were inspected (`origin` in each repository), not remote URLs. The current ADR
allows ACR sharing only for immutable, environment-neutral images and least-privilege pulls
(`docs/decisions/0002-azure-target-architecture-and-migration-boundaries.md:231-234`).

## Actual sibling registry topology

| Evidence source | What is configured | What is exercised | Portability and limitation |
|---|---|---|---|
| Agrisense | One Premium ACR is created inside the product's Azure Terraform data layer. Admin auth is disabled; public RBAC-gated push is retained for GitHub-hosted OIDC runners and a private endpoint serves VM pulls (`D:\projects\agrisense\infra\azure\data.tf:157-205`). A main-branch federated CD identity has registry-scoped `AcrPush` (`identity.tf:22-55`), while the VM identity has registry-scoped `AcrPull` (`compute.tf:106-110`). The workflow builds four product repositories and writes both a commit-derived tag and `latest` (`.github\workflows\cd-azure.yml:55-140`). | The accepted repository snapshot records a live Israel Central Azure deployment and a single product registry, with OIDC push and managed-identity pull (`docs\agent\current-state.md:3,50-63`; `docs\agent\memory\deployment-infra.md:58-69`). | Strong auth and same-region precedent. It is product-owned, Premium because of private networking, uses broad registry roles, and still publishes a mutable tag. It is not a neutral shared-registry precedent. |
| LARP Store | A Basic ACR is named per environment, has admin and anonymous pull disabled, and remains publicly reachable because Basic has no private endpoint (`D:\projects\larp-store\infra\modules\registry.bicep:1-52`). The main template uses repository `larp-store/store` and a commit-SHA tag for both app and migration job (`infra\main.bicep:36-42,81-84,112-121`). The deploy identity holds resource-group `Contributor` plus `AcrPush`; runtime and migrator identities have `AcrPull` (`.github\workflows\deploy-nonprod.yml:1-18,102-145,223-261`; `infra\bootstrap\runtime-identity.bicep:1-44`). | The accepted repository snapshot records the France Central non-production environment as live since 2026-07-21 and records credentialless managed-identity pulls (`docs\agent\current-state.md:991-1029`). | Strong immutable-tag and deployment-gate precedent. Registry and role scopes are product/environment-wide, not repository-isolated; it is in the wrong target region for Spotify. |

The repositories therefore show **two product-scoped ownership models**. The selected shared
organization registry is a new platform boundary, not a routine reuse of either implementation.

## ACR option comparison

### Option A - Spotify-owned Basic registry (fallback)

**Benefits**

- Spotify owns its release, retention, outage, role, deletion, and IaC lifecycle.
- Failures, throttling, accidental deletes, storage pressure, and policy changes are isolated from
  other products.
- Israel Central placement follows Microsoft's guidance to place a registry near deployments, and
  avoids cross-region image pulls.
- The fixed initial cost is small and reproducible: `$5.0674/month` using 730 hours.

**Costs and risks**

- Adds one platform object, a separate RBAC surface, monitoring, and a recovery runbook.
- Basic includes 10 GiB rather than Standard's 100 GiB or Premium's 500 GiB; image cleanup still
  requires care.
- A separate registry duplicates a fixed cost that an already-paid shared registry might absorb.

**Downstream effects**

- Create it in the Spotify production/application infrastructure boundary, with non-production
  permitted to pull the same immutable environment-neutral digests.
- Configure fixed Spotify repositories, digest-based deployment, protected release manifests, and
  explicit deletion authority before publication.

### Option B - organization-shared registry (recommended target)

**Benefits**

- Avoids the new Basic fixed meter if the registry is already paid for and has headroom.
- Centralizes image policy, vulnerability scanning, provenance, retention, and platform operations.
- Multiple products can reuse one governed artifact store without duplicate registry units or
  storage; region-specific copies remain an evidence-triggered exception.

**Costs and risks**

- Registry API limits, storage, policy changes, maintenance, and an outage become a shared blast
  radius. Microsoft defines rate limits across all clients of a registry and returns HTTP 429 with
  `Retry-After` when exceeded.
- A registry-wide writer, catalog lister, or delete role exposes unrelated products. A shared
  deployment identity also weakens audit ownership.
- Deleting a repository removes all of its artifacts; deleting a manifest by digest removes every
  tag that points to it. ARM resource locks do not protect registry data-plane content.
- Cross-region pulls add avoidable latency and transfer exposure. Container Apps pulls an image
  whenever a container starts, so a registry problem can block scale-out, restart, rollback, or a
  new revision even while an already-running replica continues.
- Using Agrisense's registry in place couples Spotify to the Agrisense product resource group,
  Terraform state, Premium/private-network posture, and recovery authority. Its existing product
  owner is not an organization platform owner.

**Required implementation rule**

Implement the selected shared target only when **all** of the following are true; otherwise hold
the shared-registry migration rather than silently creating an application-owned substitute:

1. the registry is an explicitly shared platform resource with a named operator, neutral resource
   group, one authoritative IaC owner, change/review gate, budget owner, and recovery runbook;
2. Israel Central is the primary location for the two Israel workloads; the initially rare LARP
   pulls from France are measured and accepted, with Premium geo-replication or a separately
   approved registry boundary activated only if pull latency, availability, residency, or transfer
   evidence justifies it;
3. it uses `RBAC Registry + ABAC Repository Permissions`, with Spotify identities constrained to
   `spotify-mcp/*` and no cross-product catalog or delete authority;
4. the tenant/subscription identity relationship and role-assignment authority are proven before
   apply; cross-tenant managed-identity pull is not assumed;
5. current storage, API-rate, webhook, and operational headroom are measured and per-product
   alerts/budgets are possible;
6. immutable digests, protected release tags/manifests, cleanup policy, restore/mirror procedure,
   and ownership during registry or region outage are rehearsed; and
7. a registry move or product exit can be completed without rebuilding images.

The current Agrisense registry should not become the shared target merely because it is already
paid for. It first needs an explicit cross-repository migration to neutral platform ownership; its
existing Premium/private-endpoint posture can then serve the organization without making
Agrisense's application lifecycle the owner of every product's release artifacts.

## ACR permission and repository design

For a qualifying shared registry, use repositories such as:

```text
spotify-mcp/api
spotify-mcp/collector
spotify-mcp/migration
```

The exact repository names become contract inputs to IaC and CI. Build once, push a content-addressed
artifact, record its digest and provenance, and deploy Container Apps and jobs by digest. Do not
use `latest` as a release or rollback identifier.

| Principal | Recommended ABAC data role | Scope/condition | Deliberately absent |
|---|---|---|---|
| GitHub image publisher | Container Registry Repository Writer | Registry scope with condition matching `spotify-mcp/*` | Delete and unrelated catalog listing. |
| API/collector/migration runtime identities | Container Registry Repository Reader | Exact repository or `spotify-mcp/*` condition, preferably separate per workload | Push, delete, and Catalog Lister. Container Apps should use user-assigned identity for pull. |
| Cleanup identity | Container Registry Repository Contributor | `spotify-mcp/*`, separate identity and manual reviewed workflow | Registry management and unrelated repository delete. |
| Platform registry manager | Container Registry Configuration Contributor plus only the management roles required by the platform | Registry resource | Routine application image push/delete. |

Microsoft's ABAC documentation says legacy `AcrPull`, `AcrPush`, and `AcrDelete` are not honored
after a registry changes to the ABAC role-assignment mode. The approximate migration is Repository
Reader, Repository Writer, and Repository Contributor respectively. Catalog Lister is separate and
cannot be repository-conditioned, so fixed-path runtimes should not receive it. Changing an
existing registry's role-assignment mode can disrupt clients while permissions propagate; assign
and test the replacement roles first.

Managed identities can be assigned data roles on a registry. A same-tenant identity in a different
subscription is **operationally plausible but not established by the inspected ACR page as an
automatic cross-subscription feature**: the registry owner still needs role-assignment authority at
the registry scope and must resolve the identity's principal. This must be proven read-only in the
target tenant before apply. Cross-tenant pulls remain unresolved and are outside the initial target.

Primary sources:

- [ACR ABAC repository permissions](https://learn.microsoft.com/en-us/azure/container-registry/container-registry-rbac-abac-repository-permissions)
- [ACR built-in data roles](https://learn.microsoft.com/en-us/azure/container-registry/container-registry-rbac-built-in-roles-overview)
- [ACR managed-identity authentication](https://learn.microsoft.com/en-us/azure/container-registry/container-registry-authentication-managed-identity)
- [Container Apps managed-identity image pull](https://learn.microsoft.com/en-us/azure/container-apps/managed-identity-image-pull)

## ACR limits, retention, outage, and SKU triggers

| Concern | Official evidence | Spotify/shared-registry consequence |
|---|---|---|
| Included storage | Basic 10 GiB, Standard 100 GiB, Premium 500 GiB; maximum registry storage is 40 TiB for Basic/Standard and 100 TiB for Premium. | Track shared total and Spotify attribution. Excess is `$0.10/GB-month`; shared storage is not free merely because the registry exists. |
| API rates | Basic/Standard registry limits include 10,000 reads, 2,000 writes, and 1,000 deletes per minute; per-identity limits are lower. Limits are shared across clients and are best effort rather than SLA. | At 1-5 Spotify users, Spotify alone is negligible; concurrent CI across products, cleanup, and scale events are the reason to monitor. Honor 429 `Retry-After`. |
| Feature boundary | Repository-scoped Entra permissions are available on all SKUs. Private endpoints and geo-replication require Premium. | ABAC does not force Premium, but an organization registry adopted from Agrisense must retain Premium while Agrisense requires its private endpoint. Spotify's marginal registry-unit cost can still be zero. |
| Zone/region recovery | Zone redundancy is available by default in supported regions and protects the data plane from a zone failure. Premium geo-replication provides additional regional copies; it does not follow merely from a shared registry. | A single-region Basic/Standard registry still needs an outage procedure. Keep locally reproducible build inputs and record digests; consider an authorized secondary mirror only when RTO evidence justifies Premium or a second registry. |
| Image locking | Tags are mutable by default. Repository/image write and delete attributes can be locked, but an ARM management lock does not protect data-plane deletes. | Protect released manifests/tags and separate cleanup credentials. A digest is immutable addressing, not deletion protection. |
| Deletion/retention | Deleting a repository removes all artifacts. Deleting a digest removes its manifest and every tag pointing to it. Premium's untagged-manifest retention is preview and can delete digests used directly. | Never run broad automatic deletion on the shared namespace. Retain all live and rollback digests explicitly; do not combine digest deployment with an unreviewed untagged-retention policy. |
| Usage visibility | `az acr show-usage`, Portal Overview, and the registry usage REST endpoint show quotas; `StorageUsed` is more current, although recent operations can lag the snapshot. | Alert on registry totals and maintain a repository-attribution report because one product can consume shared headroom. |

Primary sources:

- [ACR service tiers and limits](https://learn.microsoft.com/en-us/azure/container-registry/container-registry-skus)
- [ACR zone redundancy](https://learn.microsoft.com/en-us/azure/container-registry/zone-redundancy)
- [ACR image locking](https://learn.microsoft.com/en-us/azure/container-registry/container-registry-image-lock)
- [ACR image and repository deletion](https://learn.microsoft.com/en-us/azure/container-registry/container-registry-delete)
- [ACR untagged-manifest retention](https://learn.microsoft.com/en-us/azure/container-registry/container-registry-retention-policy)
- [ACR overview and same-region guidance](https://learn.microsoft.com/en-us/azure/container-registry/container-registry-intro)

### Upgrade triggers

- **Basic -> Standard:** use Standard when included storage, webhook count, or measured registry
  throughput/parallel CI makes Basic's smaller included envelope operationally material. The current
  Israel Central Standard fixed meter is `$0.6666/day`, or `$20.2758/month`; this is
  `$15.2084/month` above Basic. Microsoft supports changing SKU when the target tier's storage limit
  can contain current use.
- **Standard/Basic -> Premium:** use Premium only when a private endpoint, geo-replication, customer-
  managed key, higher throughput, or another Premium feature is approved. Israel Central's fixed
  Premium meter is `$1.6666/day`, or `$50.6924/month`, before replication/storage. Sharing the
  current Agrisense Premium registry does not make its premium operating model free; it only makes
  the Spotify **marginal fixed meter** zero while that registry remains funded.

The rates above came from Microsoft's unauthenticated
[Retail Prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices)
with the exact filter:

```text
serviceName eq 'Container Registry' and armRegionName eq 'israelcentral' and priceType eq 'Consumption'
```

The selected current meters were Basic Registry Unit `$0.1666/1 day`, Standard Registry Unit
`$0.6666/1 day`, Premium Registry Unit `$1.6666/1 day`, and Data Stored `$0.10/GB-month`.

## Superseded warm-topology ACR monthly cost adjustment

The existing cost note includes ACR Basic at `$5.0674/month` in low and expected cases, and
`$6.0674/month` in the conservative case because that case adds 10 GiB excess storage
(`docs/migration/spm-4-azure-cost-estimate-2026-08-27.md:204-205,275-286`).

| Registry decision | Exact line-item adjustment | Approximate production total from the displayed baseline |
|---|---:|---:|
| Spotify-owned Basic | `$0` | Unchanged: low `$74.91-$79.84`; expected `$96.29-$101.69`; conservative `$341.50`. |
| Already-paid shared registry, included storage has headroom | `-$5.0674/month`; conservative case `-$6.0674` if all additional 10 GiB also fits included shared storage | Low `$69.84-$74.77`; expected `$91.22-$96.62`; conservative `$335.43` if excess is absorbed. |
| Already-paid shared registry, but Spotify's conservative 10 GiB is excess | `-$5.0674/month`; retain `$1.00/month` excess storage | Low `$69.84-$74.77`; expected `$91.22-$96.62`; conservative `$336.43`. |

These preserved adjusted totals subtract exact line items from the cost note's superseded warm
topology, so they are historical scenario sensitivities, not a new subscription quote or the
approved budget. The later owner-approved small-cohort model replaces them with an approximately
`$40/month` forecast, a `$31-$46/month` sensitivity, and a `$60/month` app budget; see the
[current cost estimate](spm-4-azure-cost-estimate-2026-08-27.md#owner-approved-small-cohort-revision---2026-08-27).

## Static Web Apps Free versus Standard

| Dimension | Free | Standard | Spotify relevance |
|---|---|---|---|
| Intended use | Microsoft describes Free for hobbies/personal projects. | Microsoft describes Standard for general-purpose production apps. | The target is production even at 1-5 users; size alone does not create an SLA. |
| Israel Central retail meter | `$0`. | `$9.90/app-month`, metered hourly/per second by the pricing page. | Exact fixed saving from Free is `$9.90/month`. |
| SLA | None. | SLA available. | Current official feature pages do not state the current legal percentage; verify the then-current SLA before apply. |
| Included bandwidth | 100 GB/month across Static Web Apps in the subscription. | 100 GB/month across Static Web Apps in the subscription. | It is not 100 GB per app. Other apps can consume the same allowance. |
| Beyond included bandwidth | Overage unavailable; the pricing page says the site is not served after the quota is exceeded. | Service continues and Israel Central overage is `$0.22/GB` above 100 GB. | Free converts an unexpected traffic event or shared-subscription use into outage rather than cost. Reset timing and the response seen by clients are not documented in the inspected sources. |
| Apps per subscription | 10. | 100. | Subscription-wide capacity, not an initial Spotify constraint. |
| Preview environments | 3. | 10. | Three is adequate for a lean pilot only if PR-preview concurrency is controlled. Preview environments cannot have custom domains. |
| Total storage across environments | 500 MB. | 2 GB. | Build artifacts and previews share the envelope. |
| Maximum deployment/app size | 250 MB per environment. | 500 MB per environment. | Add a build-size/file-count gate; the React frontend should fit, but must be measured. |
| File count | 15,000 per environment. | 15,000 per environment. | Same on both tiers. |
| Request size | 30 MB. | 30 MB. | Same on both tiers; uploads go directly to Blob/ACA, not through SWA. |
| Custom domains | 2 in current plans/pricing. | 5 in current plans/pricing. The older quota page says 6. | Spotify initially needs fewer. Treat 5 as the supported planning limit until subscription/API preflight resolves the official inconsistency. |
| TLS certificates | Free auto-renewing certificates. | Free auto-renewing certificates. | No certificate line-item cost for either tier. |
| API integration | Managed Azure Functions API. | Managed or bring-your-own Azure Functions API. | Spotify's selected backend is ACA on a separate hostname, so this does not block Free. |
| Authentication | Preconfigured provider registrations; no custom registrations. | Custom provider registrations supported. | The ADR uses the existing Google-to-application-JWT seam through ACA, not SWA auth; SPM-6 must still prove cross-origin auth. |
| Custom roles | Up to 25 users via invitations on both; function-assigned custom roles unavailable. | Up to 25 via invitations and function-defined roles available without that Free limitation. | Not part of the selected auth model. |
| Private endpoint | None. | One. | No SWA private endpoint is selected initially; direct public frontend is intended. |
| Allowed IP ranges | None. | Up to 25 configured ranges. | Not selected initially. Standard preserves this future restriction option. |

Primary sources:

- [Static Web Apps plans](https://learn.microsoft.com/en-us/azure/static-web-apps/plans)
- [Static Web Apps quotas](https://learn.microsoft.com/en-us/azure/static-web-apps/quotas)
- [Static Web Apps pricing](https://azure.microsoft.com/en-us/pricing/details/app-service/static/)
- [Static Web Apps FAQ](https://learn.microsoft.com/en-us/azure/static-web-apps/faq)
- [Static Web Apps custom domains](https://learn.microsoft.com/en-us/azure/static-web-apps/custom-domain)

The Israel Central meters were reproduced from the unauthenticated Retail Prices API with:

```text
productName eq 'Static Web Apps' and armRegionName eq 'israelcentral' and priceType eq 'Consumption'
```

The current records returned Standard App `$9.90/1 month`, Standard Bandwidth Usage `$0` from tier
0 and `$0.22/GB` from `tierMinimumUnits = 100`, plus an optional managed Front Door add-on that is
not part of the selected architecture. The response had no next page.

## SWA quota visibility, monitoring, and alerts

Microsoft exposes Azure Monitor platform metrics for resource type `Microsoft.Web/staticSites`.
The relevant meter is:

| Property | Official value |
|---|---|
| Display / REST name | Data Out / `BytesSent` |
| Unit and aggregation | Bytes; `Total` / sum |
| Time grains | `PT5M`, `PT1H`, `P1D` |
| Dimensions | None |
| Diagnostic settings export | No |

It can be viewed in the resource's Portal Metrics blade, read using the authenticated Azure Monitor
Metrics REST API, or queried with `az monitor metrics list` against the Static Web App resource.
Azure Monitor retains platform metrics for 93 days; the Portal chart directly displays at most 30
days. Recent metric points can be partial, and Microsoft says processing latency is often a couple
of minutes depending on the service.

Primary sources:

- [Static Web Apps supported metrics](https://learn.microsoft.com/en-us/azure/azure-monitor/reference/supported-metrics/microsoft-web-staticsites-metrics)
- [Static Web Apps metrics](https://learn.microsoft.com/en-us/azure/static-web-apps/metrics)
- [Azure Monitor metrics platform and retention](https://learn.microsoft.com/en-us/azure/azure-monitor/metrics/data-platform-metrics)
- [Azure Monitor Metrics REST list](https://learn.microsoft.com/en-us/rest/api/monitor/metrics/list)
- [`az monitor metrics list`](https://learn.microsoft.com/en-us/cli/azure/monitor/metrics?view=azure-cli-latest#az-monitor-metrics-list)
- [Metric processing-delay guidance](https://learn.microsoft.com/en-us/azure/azure-monitor/metrics/metrics-troubleshoot)

### What can be alerted directly

A normal Azure Monitor metric alert can use `BytesSent` with sum aggregation and notify an action
group. Metric-alert evaluation windows are at most one day. This supports per-app daily-rate alerts
or a small-window traffic-spike alert.

### What is not established

The 100-GB allowance is subscription-wide across Static Web Apps, while `BytesSent` is a
per-resource metric with no dimensions and no diagnostic-settings export. The inspected official
sources do not document:

- a Static Web Apps quota-remaining metric or API;
- a native calendar-month, cross-resource metric-alert expression;
- the enforcement metric's delay relative to `BytesSent`;
- Free's exact stop/resume time, HTTP response, or monthly reset behavior; or
- whether a static-only app with no managed API always emits `BytesSent`. The resource metric
  reference lists it, but the product metrics page frames collection around adding a managed API.

Therefore a production Free pilot needs two layers:

1. a conservative per-resource `BytesSent` spike/daily-rate metric alert; and
2. a scheduled authenticated read of month-to-date `BytesSent` for **every** Static Web App in the
   subscription, summing the values and alerting well below 100 GB.

The second layer is a recommendation, not a native quota counter. It requires its own identity,
calendar-month arithmetic, late-data tolerance, and tests. Azure Advisor has an official
recommendation to upgrade when combined bandwidth for Free apps in a subscription exceeds 100 GB,
but Microsoft does not document it as a configurable early-warning threshold or give a lead time;
it is not a substitute for the proactive monitor.

Sources:

- [Azure Monitor metric alert ARM schema and window sizes](https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/resource-manager-alerts-metric)
- [Azure Advisor reliability recommendation for Static Web Apps bandwidth](https://learn.microsoft.com/en-us/azure/advisor/advisor-reference-reliability-recommendations)

## Free-to-Standard upgrade behavior

Microsoft documents changing a Static Web App's hosting plan in the Portal by selecting the plan
on the same resource and saving it. The FAQ says an app can upgrade from Free to Standard at any
time and may downgrade if it is not using Standard-only features. The ARM/Bicep and REST schemas
also expose the SKU on the existing `Microsoft.Web/staticSites` resource. The plans page separately
says migration to the Dedicated plan requires redeployment, which supports the conclusion that a
Free-to-Standard change is an in-place SKU update rather than a new app deployment.

Sources:

- [Change Static Web Apps plan](https://learn.microsoft.com/en-us/azure/static-web-apps/plans#change-hosting-plan)
- [Static Web Apps FAQ](https://learn.microsoft.com/en-us/azure/static-web-apps/faq)
- [Bicep/ARM Static Sites resource](https://learn.microsoft.com/en-us/azure/templates/microsoft.web/staticsites)
- [Static Sites create-or-update REST operation](https://learn.microsoft.com/en-us/rest/api/appservice/static-sites/create-or-update-static-site)

However, the inspected sources provide **no explicit zero-downtime SLA, propagation time, or
guarantee that active preview/domain behavior is uninterrupted during the plan change**. Before a
Free production pilot relies on emergency upgrade, rehearse Free -> Standard -> Free in
non-production while probing the custom domain, TLS, frontend assets, auth callback, ACA API calls,
and all preview environments. Pre-authorize who may perform the production upgrade; do not make
the outage response depend on a new owner decision.

## SWA options and monthly cost effects

### Option A - Standard production

**Pros:** production positioning, SLA, paid overage instead of a hard quota stop, more previews and
storage, and future custom auth/private endpoint/IP-range capabilities.

**Cons:** `$9.90/month` even at near-zero use; features beyond the SLA and overage behavior are
mostly YAGNI for the selected separate-hostname architecture.

**Downstream if activated:** change the production SKU to Standard in Bicep and the cost model. Add
`BytesSent`, error, latency, budget, and anomaly monitoring regardless of tier.

### Option B - Free production pilot, then in-place Standard upgrade (selected)

**Pros:** saves exactly `$9.90/month`; likely ample for 1-5 users; same resource can change to
Standard; selected ACA auth/backend means several Standard-only SWA features are unnecessary.

**Cons:** no SLA, hard stop at a subscription-shared quota, incomplete native month-to-date alert
support, fewer previews/storage/domains, and no documented zero-downtime upgrade guarantee.

**Required gates:** measured deployed size/file count; subscription-wide app/bandwidth inventory;
static-only `BytesSent` proof; month-to-date aggregator and alerts; rehearsed plan change; an
automatic or pre-authorized upgrade threshold; and owner acceptance of the no-SLA/hard-stop pilot
window. A practical owner threshold should be chosen below 100 GB after measuring other apps and
telemetry delay.

### Superseded warm-topology cost sensitivity

| Decision | Exact line-item adjustment | Approximate production total from the displayed baseline |
|---|---:|---:|
| Standard production | `$0` | Unchanged: low `$74.91-$79.84`; expected `$96.29-$101.69`; conservative `$341.50`. |
| Free production | `-$9.90/month` | Low `$65.01-$69.94`; expected `$86.39-$91.79`; conservative `$331.60`. |
| Free plus already-paid shared ACR, included storage headroom | `-$14.9674/month` in low/expected; `-$15.9674` in the conservative case if its 10 GiB excess also fits | Low `$59.94-$64.87`; expected `$81.32-$86.72`; conservative `$325.53` if excess is absorbed. |
| Free plus shared ACR, conservative excess retained | `-$14.9674/month` | Low `$59.94-$64.87`; expected `$81.32-$86.72`; conservative `$326.53`. |

In the superseded warm model, Free alone moved the approximately `$105` production forecast to
about `$95`, while Free plus the fixed shared-registry saving moved it to about `$90`. These values
and the old `$130` envelope are retained only as historical sensitivity evidence. The approved
small-cohort target instead uses an approximately `$40/month` forecast, a `$31-$46/month`
sensitivity, and a `$60/month` app budget, with re-estimation after 14 and 30 complete days. The
user's stated current-cost benchmark remains user-provided context and is not re-queried here.

## Measured, inferred, and unresolved summary

| Classification | Conclusion |
|---|---|
| Configured | Agrisense and LARP each configure product-scoped registries; neither configures an organization-level shared registry. |
| Exercised | Their accepted repository snapshots record the respective Azure deployments as live. No current Azure state was independently inspected. |
| Measured | Israel Central retail meters are Basic ACR `$0.1666/day`, Standard ACR `$0.6666/day`, Premium ACR `$1.6666/day`, ACR excess storage `$0.10/GB-month`, SWA Standard `$9.90/month`, and SWA Standard bandwidth `$0.22/GB` above the 100-GB tier. |
| Calculated | Qualifying shared ACR saves `$5.0674/month` fixed; SWA Free saves `$9.90/month`; both save `$14.9674/month` before storage differences. |
| Selected | One neutral organization-shared registry with ABAC is the target; directly reusing the Agrisense product lifecycle is not operationally neutral. |
| Selected | Free is the initial 1-5-user SWA production pilot, gated by telemetry and an early in-place Standard upgrade path; Standard remains the safer steady-state tier because of SLA and quota-overage behavior. |
| Unresolved | Exact current legal Standard SLA percentage; current docs only say an SLA is available. |
| Unresolved | Current custom-domain docs conflict: Standard is 5 in plans/pricing and 6 in the older quotas page. Plan on 5. |
| Unresolved | Native subscription month-to-date bandwidth remaining/alert, enforcement delay, Free stop/resume mechanics, and guaranteed `BytesSent` emission for a static-only app. |
| Unresolved | Explicit zero-downtime and propagation guarantee for Free-to-Standard. |
| Unresolved | Cross-tenant managed-identity pull; it is excluded. Same-tenant cross-subscription role assignment still needs target-tenant proof. |

## Implementation gates for the eventual accepted plan

Before any Azure apply:

1. the organization-shared ACR satisfies every implementation rule above, including neutral
   ownership and the cross-repository ABAC migration plan;
2. IaC declares the registry owner, region, SKU, role-assignment mode, repository conditions,
   immutable release protection, cleanup identity, monitoring, and recovery boundary;
3. subscription preflight verifies resource providers, Israel Central allocation, identity tenant,
   ACR role mode, rate/storage headroom, and current retail quote without inspecting image content;
4. SPM-6 proves managed-identity pulls for API, collector, and migration job by digest, including
   registry-unavailable/restart behavior and rollback;
5. the selected gated Free pilot has an accepted early Standard-upgrade threshold and named
   authority;
6. the deployed frontend's compressed/uncompressed size, file count, preview concurrency, custom
   domains, authentication path, and monthly bandwidth are measured;
7. Free pilot monitoring, subscription-wide aggregation, action group, upgrade identity, threshold,
   and non-production plan-change rehearsal pass before public traffic; and
8. cost and quota are re-estimated after 14 and 30 complete days.

**STOP 1:** local-ready evidence for root verification. The registry and tier are owner-selected;
Yuval Moran later accepted ADR 0002 with "Decision 4 A" and approved the combined
registry-rehome/Agrisense ticket shape with "Decision 3 - B" on 2026-08-27 UTC. Every cloud
mutation, Azure login, production access, state inspection, workflow run, deployment, registry
move, role assignment, and resource deletion remains separately gated.
