# SPM-4 PostgreSQL availability and recovery evidence

Captured 2026-08-26 for the owner decision on Azure Database for PostgreSQL
Flexible Server in **Israel Central**. This is decision evidence only: it
does not create, query, or alter an Azure resource, subscription, production
database, or Spotify data.

## Decision context and evidence classification

**Measured from repository evidence.** The sanitized SPM-20 baseline records
one PostgreSQL 18 node with 60 GiB provisioned storage, an approximately 3.39
GB database, about 10.2 million estimated rows, and no agreed restore test,
retention, RPO, or RTO. It also records that the application is a small but
continuously running API/collector system and that DigitalOcean remains
authoritative until an independently authorized cutover. These facts make a
32-GiB Azure disk a technical list-price floor, not a production sizing result.
The existing ADR selects Israel Central as primary and France Central as an
unprovisioned contingency; it explicitly leaves HA, retention, RPO/RTO, and
restore-rehearsal cadence to an owner decision.

**Measured from current Microsoft documentation.** Flexible Server is offered
in Burstable, General Purpose, and Memory Optimized compute tiers. Israel
Central supports Intel v3/v4 compute, same-zone HA, and zone-redundant HA, but
does **not** support geo-redundant backup. Israel Central is also an Azure
availability-zone region but has no paired region. Thus an Israel-only design
cannot present geo-backup as a France contingency or automatic regional
recovery. [Azure PostgreSQL region capabilities](https://learn.microsoft.com/en-us/azure/postgresql/overview), [Azure regions](https://learn.microsoft.com/en-us/azure/reliability/regions-list)

**Unresolved and a pre-apply gate.** The current target subscription's policy,
quota, SKU/zone capacity, price agreement/currency, service registration,
network feasibility, and exact portal quote were not queried. Public list
prices and regional capability are not proof that this subscription can deploy
the selected configuration. A reviewed subscription preflight and quote must
pass before any apply.

**Measured from the signed-in Azure subscription on 2026-08-26.** A read-only
`az postgres flexible-server list-skus --location israelcentral` capability
probe succeeded against an enabled AzureCloud subscription. Its Burstable
catalog includes `Standard_B1ms` with 1 vCore, 2,048 MiB memory per vCore, 640
supported IOPS, no restriction reason, and supported zones 1, 2, and 3. It
also offers a 32-GiB P4 managed disk with 120 baseline IOPS and a 64-GiB P6
managed disk with 240 baseline IOPS. The catalog does **not**
include `Standard_B1s`; B1s is an Azure VM size, but it is not an available
Azure Database for PostgreSQL Flexible Server SKU in this location/catalog.
This proves subscription-visible SKU support, not transient capacity at the
future creation time. Only the separately authorized pre-apply check can prove
that the selected zone and SKU are allocatable then.

**Owner clarification:** “The relevant instance size is `Standard_B1ms`.”
This confirms which Burstable candidate the owner intended; storage size, HA,
PITR retention, and recovery objectives remain part of the open decision below.

## What the service documents

### Compute and availability

- **Burstable:** B1ms is 1 vCore/2 GiB with 35 default user connections; it is
  the lowest published and subscription-visible Flexible Server compute floor
  in Israel Central. B1s is not offered for this service. B1ms has no built-in
  PgBouncer and does not support HA. It suits a cost experiment only after
  realistic connection, CPU-credit, query, and import-path testing—not an
  assumed migration size.
  [Flexible Server limits](https://learn.microsoft.com/en-us/azure/postgresql/configure-maintain/concepts-limits), [HA configuration](https://learn.microsoft.com/en-us/azure/postgresql/high-availability/how-to-configure-high-availability)
- **General Purpose / Memory Optimized:** these tiers support HA. The smallest
  General Purpose shape documented is D2s/D2ds (2 vCores/8 GiB); D2ds v5 is the
  smallest concrete General Purpose list-price meter returned for this note.
  [Compute options](https://learn.microsoft.com/en-gb/azure/postgresql/compute-storage/concepts-compute), [Flexible Server limits](https://learn.microsoft.com/en-us/azure/postgresql/configure-maintain/concepts-limits)
- **No HA:** Azure keeps three locally redundant storage copies and can restart
  a crashed server or relocate it to another node. It is not a standby design;
  its recovery time is workload-dependent and Azure does not publish a fixed
  RTO for it. Client code must retry dropped connections and failed
  transactions. [HA concepts](https://learn.microsoft.com/en-us/azure/postgresql/high-availability/concepts-high-availability), [business continuity](https://learn.microsoft.com/en-us/azure/postgresql/backup-restore/concepts-business-continuity)
- **Same-zone HA:** a synchronously replicated, same-zone standby protects
  against node failure and automatically fails over on primary disruption. It
  does not survive loss of that availability zone: recover with PITR to another
  zone. Microsoft documents RPO 0 and RTO in most cases below 120 seconds for
  this HA model, plus an uptime SLA of about 99.95%; this is a service claim,
  not an application-end-to-end promise. [HA concepts](https://learn.microsoft.com/en-us/azure/postgresql/high-availability/concepts-high-availability), [business continuity](https://learn.microsoft.com/en-us/azure/postgresql/backup-restore/concepts-business-continuity)
- **Zone-redundant HA:** a synchronously replicated standby in another Israel
  Central zone protects node and zone failure. Microsoft documents automatic
  failover in 60-120 seconds with zero data loss, an RTO in most cases below
  120 seconds, and an uptime SLA of about 99.99%. The application must reconnect
  after connections are drained; synchronous commit can add write latency. This
  is the only in-region choice here with a documented automatic response to a
  zone failure. [HA concepts](https://learn.microsoft.com/en-us/azure/postgresql/high-availability/concepts-high-availability), [business continuity](https://learn.microsoft.com/en-us/azure/postgresql/backup-restore/concepts-business-continuity)

HA copies the primary's compute, storage, and network configuration for its
standby. Microsoft cost guidance says HA doubles deployment cost. It prevents
neither logical/user error nor a bad application write, because those changes
are synchronously replicated; use PITR for that class of recovery. [HA concepts](https://learn.microsoft.com/en-us/azure/postgresql/high-availability/concepts-high-availability), [cost optimization](https://learn.microsoft.com/en-us/azure/postgresql/configure-maintain/how-to-cost-optimization)

### Planned and unplanned interruption

With HA, scheduled software updates and minor upgrades apply to the standby
first, then the service drains connections and promotes it. A planned failover
still interrupts writes while it promotes the standby and updates DNS; the
documentation does not give a universal duration. Compute/storage scaling can
also cause short downtime on the primary. Without HA, a failed restart causes
Azure to provision a new server; its RTO is workload/recovery dependent.
[HA concepts](https://learn.microsoft.com/en-us/azure/postgresql/high-availability/concepts-high-availability), [business continuity](https://learn.microsoft.com/en-us/azure/postgresql/backup-restore/concepts-business-continuity)

Maintenance is impactful and has downtime dependent on transactional load.
Microsoft provides a one-hour system-managed or custom window, normally gives
five calendar days' notice, and says critical updates can have shorter or no
notice. General Purpose and Memory Optimized maintenance can be rescheduled
when eligible; Burstable cannot. Treat maintenance as an application reconnect
and monitoring requirement, not as a promised maintenance RTO.
[planned maintenance](https://learn.microsoft.com/en-us/azure/postgresql/configure-maintain/concepts-maintenance)

### Backup, point-in-time recovery, and geography

- Automatic physical backups are daily snapshots plus continuously archived WAL.
  Selectable retention is 7 days (default) through 35 days. Azure describes
  delay RPO from archived logs as up to five minutes; this is the logical-error
  / restore recovery point, not the HA failover RPO. [backup and restore](https://learn.microsoft.com/en-us/azure/postgresql/backup-restore/concepts-backup-restore)
- A PITR creates a **new** server with the source's compute, storage, retention,
  and backup-redundancy configuration; it never overwrites the source. Restored
  networking and the deliberate application/DNS/connection switch are part of
  the recovery runbook. Azure says recovery usually ranges from a few minutes
  to a few hours, depending on data and WAL, and does not publish an app-specific
  RTO. [backup and restore](https://learn.microsoft.com/en-us/azure/postgresql/backup-restore/concepts-backup-restore)
- Backups are online snapshots. The first snapshot follows server creation,
  later snapshots are daily/differential, and backup windows cannot be chosen.
  Automated backup files are Microsoft-managed and cannot be exported. [backup and restore](https://learn.microsoft.com/en-us/azure/postgresql/backup-restore/concepts-backup-restore)
- Same-zone HA and no-HA servers default to locally redundant backup storage;
  zone-redundant HA has zone-redundant backup storage. Geo-redundant backup is
  creation-only and depends on a paired region. Israel Central has no paired
  region and the PostgreSQL regional-capability table marks geo-redundant backup
  unavailable, so it is not an option in this location. [backup and restore](https://learn.microsoft.com/en-us/azure/postgresql/backup-restore/concepts-backup-restore), [Azure PostgreSQL region capabilities](https://learn.microsoft.com/en-us/azure/postgresql/overview)
- Built-in automated backup retention ends at 35 days. The service documentation
  now describes an on-demand physical snapshot, while its limits page still says
  manual backups are not supported and recommends `pg_dump`; this documentation
  inconsistency is unresolved. Do not rely on on-demand backup in the plan until
  the exact selected region/SKU/portal capability is verified. Azure Backup LTR
  is a different design with its own cost, recovery path, privacy, and authority
  choices, and is not included in the options below. [backup and restore](https://learn.microsoft.com/en-us/azure/postgresql/backup-restore/concepts-backup-restore), [Flexible Server limits](https://learn.microsoft.com/en-us/azure/postgresql/configure-maintain/concepts-limits)

## Public Israel Central PAYG floors

**Measured 2026-08-26 UTC from the public Microsoft Retail Prices API** using
USD Consumption records for `armRegionName eq 'israelcentral'`: B1MS =
USD 0.022/hour; B2S = USD 0.088/hour; `Standard_D2ds_v5` = USD 0.2332/hour;
Flexible Server storage = USD 0.164/GB-month; Backup Storage LRS = USD
0.105/GB-month. No Flexible Server B1S meter was returned, consistent with the
subscription capability catalog. This uses 730 hours/month, not an invoice or
calculator quote. The service's smallest assignable storage size is 32 GiB.
[Retail Prices API](https://prices.azure.com/api/retail/prices?api-version=2023-01-01-preview&currencyCode=USD), [storage sizing](https://learn.microsoft.com/en-us/azure/postgresql/scale/how-to-scale-storage-size)

| Floor | Assumptions and arithmetic | Compute + storage/month | Backup included? |
| --- | --- | ---: | --- |
| No-HA technical floor | B1ms + 32 GiB: `(0.022 x 730) + (32 x 0.164)` | USD 21.31 | USD 0 only if all backup/WAL use stays within the 32-GiB free allowance; otherwise LRS excess is USD 0.105/GB-month. |
| HA technical floor | Zone-redundant or same-zone D2ds v5 plus an identical 32-GiB standby: `2 x ((0.2332 x 730) + (32 x 0.164))` | USD 350.97 | Same allowance caveat; no excess amount can be modeled without retention and WAL volume. |
| Recommended starting capacity cost | Zone-redundant D2ds v5 with primary and standby at 64 GiB, reflecting the present 60-GiB source allocation: `2 x ((0.2332 x 730) + (64 x 0.164))` | USD 361.46 | Same caveat; measure `Backup Storage Used` before forecasting excess. |

The floors exclude tax, support, egress, network/private-endpoint/DNS charges,
monitoring/log ingestion, application compute, Azure Backup/LTR, `pg_dump`
storage, migration/rehearsal parallel capacity, regional contingency resources,
discounts, reservation purchase, and all excess backup. The included backup
allowance is 100% of provisioned server storage; WAL volume and retention can
exceed it. Storage can grow but not shrink, so the 64-GiB recommendation should
be confirmed in a rehearsal rather than treated as a reversible price toggle.
[backup storage cost](https://learn.microsoft.com/en-us/azure/postgresql/backup-restore/concepts-backup-restore), [storage sizing](https://learn.microsoft.com/en-us/azure/postgresql/scale/how-to-scale-storage-size)

Reservations are deliberately separate from the PAYG floors. The Retail Prices
API also returns General Purpose reservation meters, but their effective cost
depends on one- or three-year term, quantity, agreement, currency, exchange,
eligibility, utilization, and cancellation rules. Do not buy a reservation
until the selected zone-redundant SKU passes preflight and a post-rehearsal
steady-state size is known.

## Owner choices

| Option | Benefits | Drawbacks and risks | Cost impact and recovery posture |
| --- | --- | --- | --- |
| A. Cost-first: B1ms, 32-64 GiB, no HA, 14-day PITR | Lowest spend; managed node/storage resiliency; adequate only if interruption is acceptable. | No HA or PgBouncer; 35 default user connections; no fixed Azure RTO; a zone outage requires manual PITR and traffic switch; burst performance and connection behavior are untested. | About USD 21.31/month at 32 GiB (USD 26.56 at 64 GiB) before exclusions. Choose only with an owner-accepted recovery objective measured in hours, restore rehearsal proof, and no promise of zone continuity. |
| B. Availability within one zone: D2ds v5, 64 GiB, same-zone HA, 14-day PITR | Automatic synchronous failover for node failures; documented RPO 0 and most-case RTO below 120 seconds; lower write latency than cross-zone. | Does not survive loss of the whole zone; still needs PITR for logical errors; doubles database resources; no geo backup from Israel Central. | About USD 361.46/month at 64 GiB before exclusions. Appropriate only if owner accepts restore-based recovery after a zone failure and the 99.95% service-SLA model fits the real availability need. |
| C. In-region resilient: D2ds v5, 64 GiB, zone-redundant HA, 14-day PITR | Only option here with standby in another zone; documented 60-120 second automatic zone-failure failover and zero committed-data loss; improves planned-maintenance posture. | Doubled resources/cost; added synchronous write latency; application reconnect and full-stack zone behavior still need testing; no automatic France/geo recovery; logical errors still need PITR. | About USD 361.46/month at 64 GiB before exclusions. The PostgreSQL service describes about 99.99% uptime SLA, but do not represent it as an app SLA. |

**Independent availability-first recommendation before the owner cost decision
(inferred from the documented recovery mechanisms and the current live durable-data
baseline): choose Option C as the production target,
with a 14-day initial PITR window and a 64-GiB starting disk, subject to the
pre-apply gate and a successful rehearsal.** It is the smallest defensible
in-region path that protects a zone failure automatically. It does *not* solve
regional disaster recovery; France remains a contingency requiring a separate,
accepted cross-region data-movement and application-failover design. If the
owner's measured outage tolerance is hours and the budget difference is
material, Option A is a valid deliberate cost trade-off; it must not be called
HA or assigned the Option C failover objective.

## Owner decision

On 2026-08-26 UTC, after the subscription-specific Azure CLI probe and the
32-GiB versus 64-GiB cost, IOPS, capacity, and reversibility comparison, the
owner clarified that `Standard_B1ms` was the intended SKU and replied
“approved” to the complete proposal:

- `Standard_B1ms`, 1 vCore and 2 GiB memory;
- 32 GiB P4 managed-disk storage with 120 baseline IOPS;
- no HA and no promise of automatic zone continuity;
- 14-day PITR and an accepted restore-based, hours-scale recovery posture;
- production-shaped restore and mixed-workload proof before cutover;
- explicit connection headroom under the 35-user-connection limit;
- CPU-credit, memory, IOPS, latency, capacity, backup, and recovery monitoring;
- quarterly PITR plus application-reconnection rehearsal; and
- a reviewed move to 64 GiB, B2s, General Purpose, or zone HA when the relevant
  capacity, performance, support, or recovery gate fails.

This owner choice selects Option A and supersedes the independent
availability-first recommendation above. It does not grant Azure apply,
deployment, production-data access, migration, cutover, or credential authority.

## Proportionate evidence and rehearsal cadence

1. Before the first production migration, run a non-production, production-shaped
   restore rehearsal using authorized sanitized or synthetic material. Measure
   end-to-end elapsed time: restore request, server ready, networking/identity,
   connection switch, application health/MCP and collector checks, data
   reconciliation, and rollback decision. Record actual RPO boundary and RTO;
   do not substitute provider documentation for this evidence.
2. At cutover, prove PITR availability and run the accepted migration/fence
   procedure. Monitor `Backup Storage Used`, storage, failed connections,
   availability/HA health, and Service Health maintenance notifications. Alert
   storage before 80% usage; Azure warns that storage pressure can force
   read-only behavior.
3. Rehearse a PITR plus application reconnection quarterly and after a material
   change to schema, data volume, PostgreSQL major version, networking,
   authentication, connection pooling, HA mode, or recovery runbook. Exercise a
   planned HA failover in non-production before relying on its reconnect path;
   use controlled production testing only with separate owner authorization.
4. Review capacity and backup-excess cost monthly, and review the owner RPO/RTO,
   subscription SKU/zone availability, and the unimplemented France recovery
   design at least annually or before any resilience-affecting change.

These cadences are recommendations, not Azure guarantees. The owner must still
choose the business impact of lost uncommitted work, logical-error recovery,
and regional outage; those choices determine whether the recommended 14-day
PITR window and quarterly rehearsal remain sufficient.

## Sources and unresolved checks

All external claims above use current Microsoft/Azure documentation or the
public Microsoft Retail Prices API. The highest-value pre-apply checks are:

1. Confirm in the target subscription that Israel Central can allocate the
   chosen D2ds v5 zone-redundant HA server, primary/standby zones, 64-GiB
   storage, networking, and selected PostgreSQL version.
2. Obtain the portal/calculator quote in the billing currency and agreement,
   including expected backup/WAL use, support, monitoring, and network meters.
3. Verify the exact on-demand-backup feature exposure or select an explicit LTR
   design; the current public documentation conflict must not become an
   untested recovery dependency.
4. Establish a separately approved France recovery design if regional outage
   tolerance is less than a manual rebuild/recovery. Israel Central does not
   supply the geo-backup mechanism needed to make France automatic.
