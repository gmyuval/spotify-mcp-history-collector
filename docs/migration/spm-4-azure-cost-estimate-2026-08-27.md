# SPM-4 Azure monthly cost estimate - 2026-08-27

This dated estimate supports the cost gate in
[ADR 0002](../decisions/0002-azure-target-architecture-and-migration-boundaries.md). It preserves
the original warm-workload calculation and records the owner-approved 2026-08-27 small-cohort
revision: API scale-to-zero, a ten-minute scheduled collector Job, Static Web Apps Free, a neutral
organization-shared ACR, PostgreSQL private VNet integration, lean monitoring, and no persistent
non-production stack. It is planning evidence, not a quote, invoice forecast, deployment plan, or
authorization to access or change an Azure subscription.

No Azure login, subscription, credential, production system, ignored/local secret file, pricing
calculator, deployment, resource, tracker, GitHub object, branch, or Git index was accessed or
changed. Current rates came from Microsoft's unauthenticated Retail Prices API and official Azure
documentation. The API queries completed in one retrieval session ending
`2026-08-26T23:39:27Z`.

Evidence labels:

- **Retail input** - current USD Consumption meter returned by Microsoft's public API.
- **Published grant or limit** - official service pricing or billing documentation, not a promise
  that this subscription has unused grant capacity.
- **Calculated estimate** - arithmetic from stated quantities and retail inputs.
- **Planning allowance** - an explicit assumption where the exact quantity or regional meter is
  not yet known.
- **Excluded or optional** - not in the approved initial production topology or not a recurring
  Azure service charge.

## Owner-approved small-cohort revision - 2026-08-27

The detailed runtime evidence, correctness gates, complete YAGNI pass, and arithmetic are recorded
in the
[SPM-4 small-cohort scale-to-zero reassessment](spm-4-small-cohort-scale-to-zero-reassessment-2026-08-27.md).
The following replaces the warm-workload forecast below for the proposed ADR:

| Selected sensitivity | Estimated USD/month | Interpretation |
|---|---:|---|
| Lean production with both original Private Endpoints | **$38-$53** | SWA Free, no incremental shared-ACR charge, API at zero when idle, ten-minute scheduled collector Job, lean monitoring, no persistent non-production stack, PostgreSQL and Blob Private Endpoints. |
| Lean production with PostgreSQL private VNet integration | **$31-$46** | Selected target. Removes the PostgreSQL Private Endpoint while retaining a private database with no public endpoint; Blob keeps its Private Endpoint. |

Use approximately **$40/month** as the initial production forecast and **$60/month** as the
app-level budget while measured use replaces assumptions. Keep 80%, 100%, 120%, and anomaly
notifications. The selected target assumes no recurring non-production floor; disposable
synthetic-data rehearsals record their bounded temporary cost separately.

The Container Apps sensitivity is $0-$14.67/month under the explicit assumptions in the linked
reassessment. The lower values require unused subscription-wide grants; the upper value assumes no
grant. A qualifying organization registry has no incremental Spotify fixed registry meter, but
shared-platform allocation remains outside this app estimate.

## Superseded warm-topology comparison

Using 730 hours, or 2,628,000 seconds, per month:

| Production scenario | Estimated USD/month | Interpretation |
|---|---:|---|
| Low, warm and mostly idle | **$74.91-$79.84** | Both approved workloads remain warm. API is 0.25 vCPU/0.5 GiB at 5% active time; collector is 0.5 vCPU/1 GiB at 10% active time. Published ACA and Log Analytics grants are assumed available. |
| Expected, warm and lightly active | **$96.29-$101.69** | API and collector are each 0.5 vCPU/1 GiB; modeled at 10% and 25% active time. Standard SWA, useful synthetic monitoring, two private endpoints, and the published grants are included. |
| Conservative pressure case | **$341.50** | API is 1 vCPU/2 GiB and collector 0.5 vCPU/1 GiB, both active all month; no shared free grant is assumed; 20 GB logs, frequent tests/alerts, 5 million ACA requests, 250 GB Internet egress, and excess PostgreSQL backup are included. This is a budget-pressure case, not the expected 1-5-user bill. |

The superseded warm-topology recommendation was to use **about $105/month as the initial production run-rate forecast**, and a
**$130/month app-level budget envelope** while usage is being measured. The latter provides about
27% headroom over the high end of the expected case. If a persistent stopped-down non-production
environment is also kept, its modeled fixed floor is about **$20.85/month**, so a combined
production plus lean-nonproduction planning envelope of **about $130/month** is reasonable before
support, tax, or agreement-specific pricing.

The result is not the earlier approximately $105.35 incomplete floor. The refreshed model adds
private endpoints and DNS, monitoring, Key Vault and Blob operations, and uses the actual Israel
Central Static Web Apps Standard meter of **$9.90**, rather than the earlier **$9 West Europe
meter**. It also recognizes that warm minimum replicas can receive idle billing when they meet all
of Microsoft's idle conditions.

## Warm topology represented in the original comparison

The following list describes the preserved warm comparison, not the owner-selected 2026-08-27
target above.

Included:

- one public API/MCP Container App;
- one private continuous-collector Container App;
- both starting with `minReplicas: 1` as ADR 0002 currently requires;
- finite migration/rehearsal Container Apps Jobs only while executing;
- PostgreSQL Flexible Server `Standard_B1ms`, 32 GiB P4 storage, no HA, 14-day PITR;
- ACR Basic;
- one Standard Static Web App;
- one Standard Key Vault using secrets, not premium HSM keys;
- one dedicated GPv2 Blob Hot ZRS account with immediate terminal-object deletion;
- one PostgreSQL and one Blob private endpoint plus two Private DNS zones;
- one VNet-integrated Container Apps consumption environment with public API ingress;
- Log Analytics/Application Insights, 30-day retention, alerts, and synthetic checks;
- separate SWA and ACA custom hostnames with free managed certificates; and
- ordinary Internet egress and service request/operation meters.

Excluded from the initial target:

- Azure Front Door;
- PostgreSQL HA, geo-redundant backup, General Purpose compute, and 64-GiB storage;
- managed Redis;
- Blob soft delete, versioning, Blob Backup, or source-ZIP archival retention;
- private ACA ingress or an ACA environment private endpoint and its Dedicated Plan Management
  meter;
- NAT Gateway, Azure Firewall, VPN, Bastion, DDoS Network Protection, and DNS Private Resolver;
- application tracing, Defender for Storage malware scanning, Microsoft Sentinel, and Azure
  Support;
- any provisioned France Central contingency resource; and
- taxes, negotiated discounts, reservations, savings-plan commitments, and currency conversion.

## Retail inputs and grants

The [Azure Retail Prices API documentation](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices)
says the API is unauthenticated, USD results are Microsoft retail prices without discounts, filter
values are case-sensitive, and `tierMinimumUnits` defines meter tiers. Every query used
`api-version=2023-01-01-preview`, `currencyCode=USD`, and `priceType eq 'Consumption'`; every
response used here had an empty `NextPageLink`.

| Component | Selected current input | Grant, tier, or quantity rule | Primary source |
|---|---:|---|---|
| ACA active vCPU | $0.000034/vCPU-second | First 180,000 vCPU-seconds/month per subscription are free across ACA consumption usage. | [ACA pricing](https://azure.microsoft.com/en-us/pricing/details/container-apps/), [ACA billing](https://learn.microsoft.com/en-us/azure/container-apps/billing) |
| ACA idle vCPU | $0.000004/vCPU-second | Idle only when a minimum replica is at its configured minimum, has no request, uses less than 0.01 vCPU, and receives less than 1,000 bytes/s. | [ACA billing](https://learn.microsoft.com/en-us/azure/container-apps/billing) |
| ACA memory, active or idle | $0.000004/GiB-second | First 360,000 GiB-seconds/month per subscription are free. | [ACA pricing](https://azure.microsoft.com/en-us/pricing/details/container-apps/) |
| ACA external requests | $0.40/million | First 2 million/month per subscription are free; environment-internal requests are not charged. | [ACA billing](https://learn.microsoft.com/en-us/azure/container-apps/billing) |
| PostgreSQL B1MS | $0.022/hour | 730 hours; no HA duplicate. | [PostgreSQL pricing](https://azure.microsoft.com/en-us/pricing/details/postgresql/flexible-server/) |
| PostgreSQL storage | $0.164/GB-month | 32-GiB selected P4 size is modeled as 32 billable units, matching the existing dated evidence. | [PostgreSQL storage](https://learn.microsoft.com/en-us/azure/postgresql/compute-storage/concepts-storage) |
| PostgreSQL excess backup LRS | $0.105/GB-month | Backup up to 100% of provisioned server storage is included; only excess is charged. | [PostgreSQL backup pricing rule](https://learn.microsoft.com/en-us/azure/postgresql/backup-restore/concepts-backup-restore) |
| ACR Basic | $0.1666/day | 10 GB storage included; API also returned $0.10/GB-month beyond the included amount. | [ACR pricing](https://azure.microsoft.com/en-us/pricing/details/container-registry/) |
| Blob Hot ZRS capacity | $0.025/GB-month for the first tier | Delete after terminal processing, so billed average retained capacity should be far below uploaded bytes/month. | [Blob pricing](https://azure.microsoft.com/en-us/pricing/details/storage/blobs/) |
| Blob other operations | $0.0044/10,000 | The exact non-HNS write/read meters were not returned under the narrow product filter; scenarios therefore use a small explicit operation allowance rather than substituting another storage product. | [Blob pricing](https://azure.microsoft.com/en-us/pricing/details/storage/blobs/) |
| Private endpoint | $0.01/hour each | Two endpoints for 730 hours. | [Private Link pricing](https://azure.microsoft.com/en-us/pricing/details/private-link/) |
| Private Link data | $0.01/GB each direction in the first tier | Reads and writes are counted by direction; scenario traffic is stated below. | [Private Link pricing](https://azure.microsoft.com/en-us/pricing/details/private-link/) |
| Private DNS zone | $0.50/month for the first tier | Two zones; private queries are $0.40/million in the first tier. | [Azure DNS pricing](https://azure.microsoft.com/en-us/pricing/details/dns/) |
| Static Web Apps Standard | $9.90/app-month in `israelcentral` | 100 GB bandwidth/subscription included; overage meter begins at 100 GB and is $0.22/GB. | [SWA pricing](https://azure.microsoft.com/en-us/pricing/details/app-service/static/) |
| Key Vault Standard operations | $0.0396/10,000 | No setup or fixed vault fee; every successfully authenticated REST call is an operation. | [Key Vault pricing](https://azure.microsoft.com/en-us/pricing/details/key-vault/) |
| Log Analytics ingestion | $3.29/GB | First 5 GB/month per billing account in PAYG is free; 30-day retention stays inside the published 31 included days. | [Azure Monitor pricing](https://azure.microsoft.com/en-us/pricing/details/monitor/) |
| Log alert monitored at 15 minutes | $0.50/signal-month | Five-minute form is $1.50/signal-month in the conservative case. | [Azure Monitor pricing](https://azure.microsoft.com/en-us/pricing/details/monitor/) |
| Standard web-test execution | $0.000645/execution | Ping tests are free, but they do not substitute for authenticated/MCP synthetic checks. | [Azure Monitor pricing](https://azure.microsoft.com/en-us/pricing/details/monitor/) |
| Internet egress from Israel/MEA | First 100 GB/month free, then $0.12/GB through 10 TB | The free quantity is shared at the applicable customer/account boundary and may already be consumed. | [Bandwidth pricing](https://azure.microsoft.com/en-us/pricing/details/bandwidth/) |
| ACA managed certificate | $0 | Public ingress and certificate/DNS requirements must remain satisfied. | [ACA custom domains and certificates](https://learn.microsoft.com/en-us/azure/container-apps/custom-domains-certificates) |
| SWA certificate | $0 | Free and Standard both include free SSL certificates. | [SWA pricing](https://azure.microsoft.com/en-us/pricing/details/app-service/static/) |

The Retail API returned both zero- and paid-tier records for some services. The calculation uses
the published free threshold first and the first paid tier only after that threshold. It does not
mistake a zero-tier record for unlimited free service.

## Container Apps arithmetic

Common constants:

```text
month_seconds = 730 * 3,600 = 2,628,000
active CPU rate = $0.000034/vCPU-second
idle CPU rate = $0.000004/vCPU-second
memory rate = $0.000004/GiB-second
```

ACA free grants are subscription-wide. Microsoft publishes the total vCPU and memory grants but
does not document which priced CPU meter consumes the mixed active/idle grant first. The low and
expected values therefore show bounds: the lower number applies the vCPU grant to active seconds
first; the upper number applies it to idle seconds first. Memory has one price in Israel Central,
so its grant allocation does not change the result.

### Low warm case

```text
API:       0.25 vCPU, 0.5 GiB, 5% active, 95% idle
collector: 0.50 vCPU, 1.0 GiB, 10% active, 90% idle

active_vcpu_seconds = 164,250
idle_vcpu_seconds = 1,806,750
memory_gib_seconds = 3,942,000

gross = 164,250 * 0.000034
      + 1,806,750 * 0.000004
      + 3,942,000 * 0.000004
      = $28.5795

after published grants = $21.4920-$26.4195
100,000 external requests remain within the 2-million request grant = $0
```

The 0.5-vCPU collector gives the accepted 500-MiB ZIP path 2 GiB of documented ephemeral storage;
the 0.25-vCPU collector alternative is not used as the low case merely to lower cost.
[ACA ephemeral-storage allocation](https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts#temporary-storage)

### Expected warm case

```text
API:       0.50 vCPU, 1.0 GiB, 10% active, 90% idle
collector: 0.50 vCPU, 1.0 GiB, 25% active, 75% idle

active_vcpu_seconds = 459,900
idle_vcpu_seconds = 2,168,100
memory_gib_seconds = 5,256,000

gross = 459,900 * 0.000034
      + 2,168,100 * 0.000004
      + 5,256,000 * 0.000004
      = $45.3330

after published grants = $37.7730-$43.1730
500,000 external requests remain within the 2-million request grant = $0
```

### Conservative pressure case

```text
API:       1.00 vCPU, 2.0 GiB, 100% active
collector: 0.50 vCPU, 1.0 GiB, 100% active
no free ACA grant assumed

CPU = 1.5 * 2,628,000 * 0.000034 = $134.028
memory = 3.0 * 2,628,000 * 0.000004 = $31.536
5,000,000 requests * $0.40/million = $2.000
ACA subtotal = $167.564
```

The active percentages are assumptions, not measured production duty cycles. A warm replica is
not automatically idle: collector polling, CPU above 0.01 cores, background network above 1,000
bytes/s, startup, or an in-flight API request moves it to active billing. SPM-6 must measure ACA
active/idle seconds rather than infer them from user count.

## Other component arithmetic

### Fixed production services

```text
PostgreSQL compute = 730 * $0.022 = $16.060
PostgreSQL P4 storage = 32 * $0.164 = $5.248
PostgreSQL subtotal before excess backup = $21.308

ACR Basic = (730 / 24) * $0.1666 = $5.0674
Static Web Apps Standard = $9.900

two private endpoints = 2 * 730 * $0.01 = $14.600
two first-tier Private DNS zones = 2 * $0.50 = $1.000
```

Those items establish approximately **$51.88/month** before ACA, monitoring, operations, DNS
queries, Private Link bytes, or Internet egress. Private networking, not transient ZIP capacity,
is the storage-related fixed cost.

### Blob and private-network assumptions

| Quantity | Low | Expected | Conservative |
|---|---:|---:|---:|
| Average retained Hot ZRS ZIP capacity | 0.1 GB-month | 0.5 GB-month | 5 GB-month |
| Blob capacity at $0.025/GB-month | $0.0025 | $0.0125 | $0.1250 |
| Capacity plus operation allowance used in totals | $0.01 | $0.02 | $0.15 |
| Combined PostgreSQL/Blob Private Link bytes | 5 GB | 20 GB | 500 GB |
| Private Link data charge | $0.05 | $0.20 | $5.00 |
| Private DNS queries across both zones | 25,000 | 200,000 | 2,000,000 |
| Private DNS query charge | $0.01 | $0.08 | $0.80 |
| Network subtotal including two endpoints and zones | **$15.66** | **$15.88** | **$21.40** |

Immediate deletion changes Blob capacity from uploaded bytes per month to byte-days retained. Even
the conservative five-GB-month allowance is tiny relative to the two private endpoints.

### Key Vault assumptions

```text
low:          1,000 operations * $0.0396 / 10,000 = $0.00396
expected:    10,000 operations * $0.0396 / 10,000 = $0.03960
conservative:100,000 operations * $0.0396 / 10,000 = $0.39600
```

Password rotation itself can add operations, but no automatic certificate or secret-renewal meter
is selected. A Key Vault private endpoint is also not selected by ADR 0002; adding one with a
dedicated Private DNS zone would add about **$7.80/month** before bytes and queries.

### Monitoring assumptions

| Monitoring quantity | Low | Expected | Conservative |
|---|---:|---:|---:|
| Analytics logs ingested | 1 GB | 5 GB | 20 GB |
| Billable ingestion after 5-GB grant | $0 | $0 | `(20 - 5) * $3.29 = $49.35` |
| Log-alert signals | 2 at 15 minutes | 5 at 15 minutes | 10 at 5 minutes |
| Log-alert cost | `2 * $0.50 = $1.00` | `5 * $0.50 = $2.50` | `10 * $1.50 = $15.00` |
| Standard synthetic executions | 730 | 5,840 | 43,800 |
| Web-test cost | `730 * $0.000645 = $0.47085` | `5,840 * $0.000645 = $3.7668` | `43,800 * $0.000645 = $28.251` |
| **Monitoring subtotal** | **$1.47085** | **$6.2668** | **$92.601** |

Platform metrics are free and ping tests are free, but neither proves authenticated Google/JWT,
MCP, collector, import, or database behavior. The exact synthetic mechanism remains an SPM-6
design choice. The Standard web-test meter is a cost proxy for scheduled executions, not a claim
that one built-in test can exercise the whole flow. Application traces remain excluded.

### Jobs and traffic

- Expected ACA Job allowance: one 0.5-vCPU/1-GiB, 30-minute execution is
  `900 * $0.000034 + 1,800 * $0.000004 = $0.0378` before any remaining ACA grant.
- Conservative ACA Job allowance: ten hours at the same size is
  `18,000 * $0.000034 + 36,000 * $0.000004 = $0.756`.
- Low and expected Internet egress are modeled below the published 100-GB free quantity and cost
  $0 if that shared quantity is available.
- Conservative Internet egress is 250 GB from the Azure origin:
  `(250 - 100) * $0.12 = $18.00`. SWA traffic remains inside its separate published 100-GB
  subscription quota in this model.

## Scenario totals

| Component | Low | Expected | Conservative |
|---|---:|---:|---:|
| ACA apps and requests | $21.49-$26.42 | $37.77-$43.17 | $167.56 |
| ACA Jobs | $0.00 | $0.04 | $0.76 |
| PostgreSQL compute, P4, backup | $21.31 | $21.31 | $24.67, including 32 GB excess backup |
| ACR Basic and excess images | $5.07 | $5.07 | $6.07, including 10 GB excess storage |
| Blob capacity/operation allowance | $0.01 | $0.02 | $0.15 |
| Static Web Apps Standard | $9.90 | $9.90 | $9.90 |
| Key Vault operations | $0.004 | $0.04 | $0.40 |
| Monitoring | $1.47 | $6.27 | $92.60 |
| Private endpoints, DNS, processing | $15.66 | $15.88 | $21.40 |
| Internet egress | $0.00 | $0.00 | $18.00 |
| **Total** | **$74.91-$79.84** | **$96.29-$101.69** | **$341.50** |

Rounding is display-only. Totals were calculated from unrounded component values.

## Owner-selected scale-to-zero and scheduled-Job sensitivity

ADR 0002 now proposes an API at zero while idle and a collector that executes one finite cycle
every ten minutes. The following assumptions are sensitivities, not measurements:

- API: 0.5 vCPU/1 GiB, active for either 10 or 50 hours/month;
- collector: 0.5 vCPU/1 GiB, 4,320 executions/month, averaging one or two minutes; and
- requests remain inside the published two-million monthly grant.

| Sensitivity | vCPU-seconds | GiB-seconds | ACA after full grants | ACA with no grants |
|---|---:|---:|---:|---:|
| 10 API hours + one-minute collector | 147,600 | 295,200 | $0.00 | $6.20 |
| 50 API hours + one-minute collector | 219,600 | 439,200 | $1.66 | $9.22 |
| 50 API hours + two-minute collector | 349,200 | 698,400 | $7.11 | $14.67 |

These savings are taken only after SPM-6 cold-start/MCP/auth/upload gates and the collector's
finite-entry, singleton-lease, abandoned-claim, timeout, termination, and failure-exit gates pass.
Changing only the API minimum to one is the accepted bounded fallback.

## Non-production, migration, and one-time overlap

The selected target uses disposable non-production rehearsals rather than a standing environment.
The following preserved sensitivities show the recurring cost intentionally avoided:

- **Stopped-down persistent non-production floor:** 32-GiB PostgreSQL storage plus two private
  endpoints and two Private DNS zones is
  `32 * $0.164 + 2 * 730 * $0.01 + 2 * $0.50 = $20.848/month` before queries. ACA can scale to
  zero, SWA Free can serve a small nonproduction frontend, and PostgreSQL compute costs $0 while
  stopped. Flexible Server automatically restarts after its maximum stop window, so this is not a
  promise that compute stays stopped indefinitely.
- **Non-production with B1ms running all month:** add `$16.06`, making that narrow floor about
  `$36.91/month`; monitoring and use add more.
- **Temporary parallel restored server:** one extra B1ms/P4 server costs about `$0.7005` for 24
  hours or `$2.1016` for 72 hours when compute and storage are linearly prorated. Actual billing
  and retained backup/network resources must be checked after deletion.
- **Seven-day DigitalOcean soak overlap:** using the user-provided/current-evidence benchmark of
  `$108/month`, `($108 / 730) * 168 = $24.85`. This is not an Azure charge and does not include any
  DigitalOcean overage or backup retained during retirement.
- **IaC bootstrap:** the owner selected Bicep on 2026-08-26 UTC after the dated precedent audit.
  Bicep has no separate runtime service charge. Terraform would have added Blob state capacity and
  operations that should be pennies at this scale; a dedicated private endpoint and zone for state
  would have added about `$7.80/month`.
- Managed identities, workload federation, role assignments, VNets, and resource groups have no
  separately selected recurring meter here. GitHub-hosted runner usage and engineering labor are
  outside the Azure service bill.

## Front Door remains excluded

The refreshed Zone 7 Front Door Standard Retail API meters are unchanged from the dated edge note:

```text
base = $35/month
edge-to-client = $0.11/GB in the first tier
edge-to-Azure-origin = $0.06/GB
requests = $0.0108/10,000

100,000 requests, 1 GB to origin, 10 GB to clients:
$35 + (100,000 / 10,000) * $0.0108 + 1 * $0.06 + 10 * $0.11
= $36.268/month
```

Adding that light-use case would move the expected production total to approximately
**$132.56-$137.96/month** before its diagnostic logs. It is a 36%-38% increment on the expected
Azure base and about one third of the stated current-cost benchmark. This reinforces the approved
choice to omit Front Door initially. [Front Door pricing](https://azure.microsoft.com/en-us/pricing/details/frontdoor/)

The Retail API also exposes an Israel Central SWA managed Front Door add-on at `$0.0264/hour`, but
that is a different product meter from the standalone Front Door topology evaluated and rejected
in ADR 0002. It is not included or substituted.

## User-provided present-cost benchmark

The owner/session context and sanitized SPM-20 evidence state a present recurring DigitalOcean
core cost of about **$108/month**. It was not re-queried in this research and may not include every
current support, backup, traffic, tax, or labor cost.

Against that benchmark:

- low Azure production is about **26%-31% lower**;
- expected Azure production is about **6%-11% lower**;
- expected production plus the stopped-down nonproduction floor is about
  **$117.14-$122.54/month**, or roughly 8%-13% higher; and
- the conservative pressure case is deliberately over three times the benchmark because it
  includes continuously active larger ACA workloads and $92.60 of monitoring.

The earlier expectation of a roughly 30% saving is plausible only near the low duty-cycle case.
The more defensible expected case is approximately cost-neutral before nonproduction, support,
tax, and cutover overlap. Azure's value proposition here is managed service boundaries,
revisions, identity, recovery tooling, and reduced host operations, not a guaranteed large monthly
reduction.

## Retail coverage versus availability

No silent regional substitution is used:

- ACA, PostgreSQL B1MS/storage/backup, ACR Basic, Blob Hot ZRS, Key Vault, Log Analytics/Azure
  Monitor, and SWA Standard all returned `armRegionName = 'israelcentral'` Consumption meters.
- PostgreSQL availability is independently documented for Israel Central, and the prior dated
  evidence records a read-only subscription capability probe for B1ms, P4/P6, and zones. The
  Retail API is not that allocation proof.
- ACA is independently listed by Microsoft's rendered service/pricing region sources. Its meter
  confirms a price, not current subscription quota or environment-creation capacity.
- SWA is a global static-distribution service. Its Israel Central meter is the selected billing
  region for the app; it does not mean static assets are served only from Israel.
- Private Link and Private DNS return global or pricing-zone meters rather than an Israel-specific
  regional meter. That is the service's published billing shape, not a substitution with West
  Europe.
- Front Door uses client-edge Zone 7 meters, not the Israel Central origin region.
- Meter presence does not prove provider registration, policy permission, quota, zonal capacity,
  private-endpoint compatibility, or an agreement-specific price. Those remain mandatory
  pre-apply checks.

Microsoft's Retail API documentation describes `armRegionName` as the ARM region where the meter's
service is available, but Azure also documents allocation/capacity failures. Treat the API as
retail and broad availability evidence, never as a successful deployment preflight.
[Azure products by region](https://azure.microsoft.com/en-us/explore/global-infrastructure/products-by-region/table),
[PostgreSQL service regions](https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/service-overview),
[PostgreSQL capacity errors](https://learn.microsoft.com/en-us/azure/postgresql/troubleshoot/how-to-resolve-capacity-errors)

## Reproducible API filters

Base endpoint:

```text
https://prices.azure.com/api/retail/prices?api-version=2023-01-01-preview&currencyCode=USD
```

The URL-encoded form of each exact filter was supplied as `$filter`:

```text
serviceName eq 'Azure Container Apps' and armRegionName eq 'israelcentral' and priceType eq 'Consumption'

serviceName eq 'Azure Database for PostgreSQL' and armRegionName eq 'israelcentral' and priceType eq 'Consumption'

serviceName eq 'Container Registry' and armRegionName eq 'israelcentral' and priceType eq 'Consumption'

serviceName eq 'Key Vault' and armRegionName eq 'israelcentral' and priceType eq 'Consumption'

serviceName eq 'Storage' and armRegionName eq 'israelcentral' and productName eq 'General Block Blob v2' and skuName eq 'Hot ZRS' and priceType eq 'Consumption'

serviceName eq 'Virtual Network' and productName eq 'Virtual Network Private Link' and priceType eq 'Consumption'

serviceName eq 'Azure DNS' and priceType eq 'Consumption'

serviceName eq 'Log Analytics' and armRegionName eq 'israelcentral' and priceType eq 'Consumption'

serviceName eq 'Azure Monitor' and armRegionName eq 'israelcentral' and priceType eq 'Consumption'

productName eq 'Static Web Apps' and armRegionName eq 'israelcentral' and priceType eq 'Consumption'

productName eq 'Azure Front Door' and skuName eq 'Standard' and armRegionName eq 'Zone 7' and priceType eq 'Consumption'
```

Selected meters were matched by exact product, SKU, meter name, unit, and lowest applicable
`tierMinimumUnits`; similarly named legacy Single Server, HorizonDB, HNS Blob, Front Door Classic,
Premium, reservation, and nonprimary tiers were not substituted.

## Cost controls and validation gates

1. Before apply, reproduce every Retail API query and obtain the target subscription's portal or
   agreement quote in its billing currency. Compare, do not overwrite, this evidence.
2. Tag production and each disposable rehearsal separately. Suggested alerts during the first two
   months are 80%, 100%, and 120% of the `$60` app-level planning envelope, with anomaly alerts
   for daily ACA, log, Private Link, PostgreSQL, and temporary rehearsal changes.
3. Record ACA active, idle, memory, replica, and request meters per workload. Re-estimate after 14
   and 30 complete days; do not use user count as an activity proxy.
4. Cap Log Analytics daily ingestion, use redaction and sampling, keep 30-day retention, and
   measure each alert/test before multiplying its frequency or locations. Monitoring is the
   largest avoidable conservative-case cost.
5. Track PostgreSQL CPU credits, memory, connections, IOPS, storage, and `Backup Storage Used`.
   Reprice before moving to 64 GiB, B2s, General Purpose, or HA.
6. Track Blob byte-days, operations, Private Link bytes, terminal deletion latency, and orphans.
   Do not add soft delete, versions, Backup, or Defender without a refreshed privacy/cost decision.
7. Keep ACR below its included 10 GB with digest-based retention. Reprice before Premium/private
   ACR, geo-replication, or build tasks.
8. Keep Front Door, a Key Vault private endpoint, private ACA ingress, Redis, tracing, France
   resources, and premium support out until their explicit trigger and owner decision.

## Caveats

- PAYG list prices are estimates, not quotes. Actual pricing varies by agreement, purchase date,
  discounts, reservations, savings plan, invoice currency, and exchange rate.
- USD is Microsoft's pricing currency. Non-USD invoices use Microsoft's documented monthly
  conversion process; this note performs no USD/ILS conversion.
- Tax, including any applicable Israeli tax, and Azure Support are excluded.
- Free grants are shared at subscription or billing-account scope and may be partly or fully
  consumed by other workloads. The conservative case assumes none.
- The workload sizes, active percentages, log GB, requests, tests, DNS queries, Private Link
  bytes, backup excess, and egress are planning quantities. None was measured from Azure.
- Retail meter coverage is not proof of future allocation, and the target remains unprovisioned.
- No production or personal Spotify data was inspected to produce this estimate.

**STOP 1:** local-ready cost evidence for root verification. Yuval Moran later accepted this cost
posture as part of ADR 0002 with "Decision 4 A" on 2026-08-27 UTC. This note does not authorize
Azure apply or change any deployment or cutover authority.
