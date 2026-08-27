# SPM-4 durable upload storage evidence: Azure Files versus Blob Storage

Date: 2026-08-26 (UTC)

Linear issue: [SPM-4](https://linear.app/stratex/issue/SPM-4/record-the-product-and-azure-target-architecture-and-migration-boundaries)

Decision status: evidence for an open owner choice; no Azure apply, production access, data
movement, retention change, or ADR edit is authorized by this note

## Conclusion

**Recommend transient durable staging in Azure Blob Storage, Hot ZRS, in a dedicated
general-purpose v2 storage account—not archival ZIP storage.** Use the Blob SDK from the API and
collector, Microsoft Entra managed identities, container-scoped RBAC, a Blob private endpoint,
disabled public and Shared Key access, opaque object keys, and an application-level SHA-256. Keep
an object only while its import is pending, processing, or retryable. After a terminal database
state is committed, schedule immediate object deletion and retain only nonsensitive import
metadata, counts, and the checksum. The collector should download its atomically claimed object to
unique ephemeral storage, verify it, parse it with the unchanged streaming ZIP parser, and remove
the temporary file in `finally`.

Blob is not the lowest-code-change option. Azure Files can preserve `/app/uploads` by mounting one
share into both Container Apps. However, the Container Apps mount still requires a storage-account
key and does not support identity-based access. It also gives the workloads a shared mutable
filesystem rather than an immutable, least-privilege object boundary. Blob requires a small durable
upload-store abstraction and a database reference migration, but it better matches the actual
workflow: one API writer creates a uniquely named ZIP, one collector claims and reads it, and a
retention process eventually deletes it. [Container Apps Azure Files tutorial](https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts-azure-files), [Blob Microsoft Entra authorization](https://learn.microsoft.com/en-us/azure/storage/blobs/authorize-access-azure-active-directory)

At the measured current volume, storage capacity cost does not decide the question. The sanitized
SPM-20 baseline contains one 2,606,440-byte archive. Current public Israel Central meters put that
active payload below USD 0.001/month under either Hot ZRS option. Even at 10 GB retained, Blob data
capacity is about USD 0.25/month and Files about USD 0.325/month before protection copies and
transactions. A private endpoint and private DNS zone are the common material floor, about USD
7.80/month before data processing. Security, deletion semantics, implementation risk, and
reversibility should therefore drive the choice, not the storage-capacity difference.

The owner clarified that each ZIP is uploaded once per user and has no product purpose after it is
processed. That rules out archival retention, versioning, and Blob Backup as the default. The
remaining requirement is only a crash-safe handoff between the separately deployed API and
collector plus bounded retry. A privacy-first transient-staging proposal is recorded below.

## Scope and evidence classification

This note compares the durable handoff between the public API and the separately running collector
in the accepted Static Web Apps plus Container Apps product shape. Static Web Apps does not need
storage credentials: the browser continues to upload through the authenticated API. Direct browser
upload to a private endpoint would not work from the public internet; enabling a public Blob
endpoint or issuing browser SAS URLs would be a separate security and CORS decision.

- **Measured from repository source at** `271b009cf3cb837f95dacab9d6db8d477b7da3ce`:
  the current path, database, parser, and tests described below.
- **Measured from the sanitized SPM-20 evidence:** one retained 2,606,440-byte upload; successful
  imports do not delete archives; retention, checksum, backup, and restore evidence are absent.
- **Measured from current Microsoft documentation and the public Retail Prices API on 2026-08-26:**
  the service, security, recovery, and list-price properties cited below.
- **Inferred:** the recommendation and the expected implementation/operational tradeoffs. They must
  be proven with synthetic or authorized sanitized test data before cutover.
- **Owner-supplied requirement:** each ZIP is uploaded once per user and has no reason to remain
  after processing; it is a transient job payload, not a record of authority.
- **Unresolved:** exact subscription allocation and policy, invoice pricing, acceptable physical
  deletion latency after terminal processing, retry expiry, and whether malware scanning is
  required. No Azure subscription or resource was queried for this note.

## Current upload contract

### Measured behavior

1. `services/api/src/app/admin/router.py` accepts an authenticated multipart upload, checks only the
   lowercase `.zip` suffix, creates a filename containing `user_id`, a UUID, and the sanitized
   original filename, then writes directly to `UPLOAD_DIR` in 1 MiB chunks. It deletes the partial
   file only for an over-limit or write exception. The default maximum is 500 MiB.
2. After the file is closed, the API inserts an `ImportJob` whose `file_path` is the absolute local
   path and whose status is `pending`. A failure after file creation but before database commit can
   leave an unreferenced file; there is no orphan reconciler.
3. `docker-compose.yml` and `docker-compose.prod.yml` mount the same `upload_data` volume at
   `/app/uploads` in the API and collector. This is the only cross-service storage contract.
4. `services/collector/src/collector/zip_import.py` atomically changes one database row from
   `pending` to `processing`, then opens `Path(import_job.file_path)`. The database claim prevents
   two collector processes from ingesting one job. No filesystem lock supplies that guarantee.
5. `services/shared/src/shared/zip_import/parser.py` uses `zipfile.ZipFile` on a seekable path and
   streams each selected JSON member through `ijson` in batches. It does not extract the entire ZIP
   or load every record in memory.
6. Successful and failed jobs retain the source ZIP. The `ImportJob` model has size and path but no
   storage backend, object key, content hash, ETag/version, retention deadline, or deletion state.
7. Current upload tests cover a successful small ZIP, nonexistent user, filename suffix, job
   status, successful collector ingestion, missing path, and bad format. They do not cover the
   maximum-size boundary, partial upload cleanup, database-failure compensation, checksum failure,
   orphan reconciliation, terminal-job deletion, storage retry, or interrupted staging.

### Consequences for the target

- The upload is a durable **job payload**, not a shared editing surface. The API is the only writer;
  the collector is normally a reader; object names are already unique; and database state is the
  concurrency authority.
- Storage and database publication cannot be one transaction in either service. The safe protocol
  is: commit an immutable payload, insert the job reference, compensate on database failure, and
  reconcile old unreferenced payloads. Never expose a half-written object under a referenced key.
- A content checksum is required independently of the selected Azure service. An ETag is a
  concurrency/version identifier, not the application's portable SHA-256 contract.
- Original filenames can contain personal information. Use an opaque object key such as
  `imports/<uuid>.zip`; keep the original name and user identity out of Azure object paths and logs
  unless a separately approved product requirement needs it.

### Why some transient durability is still required

The accepted target runs the public API and continuous collector as separate Container Apps.
Container-local and replica-scoped ephemeral files are not shared between those workloads and can
disappear on replica or revision replacement. Therefore an API-local temporary file cannot be the
authority after the upload request returns. [Container Apps storage mounts](https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts)

Avoiding a shared service entirely would require one of these product-shape changes:

- process up to 500 MiB synchronously inside the public API request, coupling upload, parsing, and
  database ingestion to the API replica and ingress timeout;
- stream the upload directly from API to collector, making both workloads and the client request
  simultaneously available and leaving no replay source after interruption; or
- store the ZIP in PostgreSQL, adding large personal-data objects to WAL, backups, PITR retention,
  and the deliberately small B1ms database workload.

None is a proportionate reliability or privacy improvement. Blob is therefore a **transient durable
handoff**, not long-term product storage: it persists only long enough to decouple request receipt
from asynchronous processing and bounded retry.

## Microsoft service evidence

| Area | Azure Files mount | Blob SDK | Primary evidence |
|---|---|---|---|
| Container Apps integration | Native persistent SMB/NFS mount; the same share can appear at the same path in API and collector revisions. Container Apps supports only classic Azure file shares for this mount. | Blob cannot be mounted as a Container Apps volume. Each workload uses the Blob SDK over HTTPS. | [Container Apps storage mounts](https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts), [Azure Files mount tutorial](https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts-azure-files) |
| Identity | The documented Container Apps mount requires the storage-account key and explicitly says identity-based share access is unsupported. | Microsoft Entra OAuth and managed identities are supported; data roles can be scoped as narrowly as one container. Shared Key can be disabled. | [Azure Files mount tutorial](https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts-azure-files), [Blob authorization](https://learn.microsoft.com/en-us/azure/storage/blobs/authorize-access-azure-active-directory), [prevent Shared Key](https://learn.microsoft.com/en-us/azure/storage/common/shared-key-authorization-prevent) |
| Network | A `file` private endpoint and `privatelink.file.core.windows.net` DNS are required when public access is disabled. | A `blob` private endpoint and `privatelink.blob.core.windows.net` DNS are required when public access is disabled. | [Storage network security](https://learn.microsoft.com/en-us/azure/storage/common/storage-network-security-overview), [Azure Files endpoints](https://learn.microsoft.com/en-us/azure/storage/files/storage-files-networking-endpoints), [Storage private endpoints](https://learn.microsoft.com/en-us/azure/storage/common/storage-private-endpoints) |
| Container Apps egress | A VNet-integrated workload-profile environment can reach resources behind private endpoints. This is common to both choices. | Same. | [Container Apps networking](https://learn.microsoft.com/en-us/azure/container-apps/networking), [custom VNet](https://learn.microsoft.com/en-us/azure/container-apps/custom-virtual-networks) |
| Concurrency | Filesystem operations and open handles are available, but the application still needs its database claim and cross-store compensation. | Strong consistency; SDK clients do not support concurrent writes to the same blob. ETags/conditions provide optimistic control and leases provide exclusive writes. Unique keys plus create-without-overwrite avoid same-object contention here. | [Blob concurrency](https://learn.microsoft.com/en-us/azure/storage/blobs/concurrency-manage), [Python upload](https://learn.microsoft.com/en-us/azure/storage/blobs/storage-blob-upload-python) |
| Upload publication | The current code writes to its final path before the job row exists. A temporary name plus same-share rename can reduce partial visibility, but not make the file and database atomic. | Large SDK uploads stage blocks and commit a block list. Publish the database row only after successful blob commit, using `overwrite=False` or an equivalent create condition. | [Python upload](https://learn.microsoft.com/en-us/azure/storage/blobs/storage-blob-upload-python), [Put Block List](https://learn.microsoft.com/en-us/rest/api/storageservices/put-block-list) |
| Per-object recovery | File-share soft delete restores a deleted **share**, not an individual file. Individual recovery needs share snapshots or Azure Files Backup. | Blob soft delete restores individual deleted/overwritten blobs for 1-365 days. Container soft delete covers container deletion. Versioning preserves previous states until lifecycle deletion. | [Azure Files soft delete](https://learn.microsoft.com/en-us/azure/storage/files/storage-files-prevent-file-share-deletion), [Files snapshots](https://learn.microsoft.com/en-us/azure/storage/files/storage-snapshots-files), [Blob soft delete](https://learn.microsoft.com/en-us/azure/storage/blobs/soft-delete-blob-overview) |
| Automated expiry | No object lifecycle equivalent for ordinary files; application cleanup or another scheduled process is needed. | Lifecycle policies can tier/delete current blobs, versions, and snapshots by age and selected conditions. A database-aware reconciler is still needed because Azure lifecycle does not understand `ImportJob` state. | [Blob lifecycle management](https://learn.microsoft.com/en-us/azure/storage/blobs/lifecycle-management-overview), [lifecycle deletion](https://learn.microsoft.com/en-us/azure/storage/blobs/lifecycle-management-policy-delete) |
| Backup | Share snapshots and Azure Backup support item/share restore; vaulted backup can retain offsite recovery points. | In-account operational backup composes point-in-time restore, versioning, soft delete, change feed, and a delete lock. Vaulted backup stores an offsite copy. Both operational and vaulted Blob backup are available in public regions, subject to documented limits. | [Azure Files Backup](https://learn.microsoft.com/en-us/azure/backup/azure-file-share-backup-overview), [Blob Backup](https://learn.microsoft.com/en-us/azure/backup/blob-backup-overview), [Blob backup support](https://learn.microsoft.com/en-us/azure/backup/blob-backup-support-matrix) |
| Zone durability | LRS keeps replicas in one datacenter; ZRS synchronously copies across three or more zones. Microsoft specifically recommends ZRS for Azure Files. | The same GPv2 ZRS account-level semantics apply to block blobs. | [Azure Storage redundancy](https://learn.microsoft.com/en-us/azure/storage/common/storage-redundancy), [storage account types](https://learn.microsoft.com/en-us/azure/storage/common/storage-account-overview) |
| Malware scanning | Defender for Storage on-upload malware scanning does not support Azure Files. | Defender supports block blobs and compressed archives, including ZIP, up to 50 GB; it is optional and separately billed. | [Defender malware scanning](https://learn.microsoft.com/en-us/azure/defender-for-cloud/introduction-malware-scanning) |
| Encryption | Azure Storage encrypts data at rest by default with platform-managed keys; customer-managed keys add a separate key-availability and operations boundary. | Same. | [Azure encryption at rest](https://learn.microsoft.com/en-us/azure/security/fundamentals/encryption-atrest) |

Redundancy is not backup: every replica reflects application deletion and overwrite. LRS protects
against drive/server/rack failure inside one datacenter; ZRS adds synchronous zone copies and
transient-fault retry requirements. Israel Central has availability zones, and the Retail Prices
API exposes both Files and Blob Hot ZRS meters there. This is public capability evidence, not proof
that the future target subscription can allocate the exact account configuration.

## Option comparison

| Criterion | A. Azure Files Hot ZRS | B. Blob Hot ZRS |
|---|---|---|
| Current compatibility | **Best.** Mount at `/app/uploads` in both apps; current path column and parser can remain initially. | Requires an `UploadStore` seam, object reference migration, SDK dependencies, and collector download-to-temp before parsing. |
| Static Web Apps + separate ACA | Browser uploads through API; API and collector share the mounted path. | Browser uploads through API; API commits the blob and collector reads it by object key. Static Web Apps has no storage access in either design. |
| Credential posture | **Weakest.** The ACA environment storage link needs an account key. A dedicated account limits but does not remove its blast radius and rotation duty. | **Best.** Managed identities and container-scoped RBAC; disable Shared Key and anonymous/public access. API and collector permissions can differ. |
| Cross-replica sharing | Native shared filesystem across API and collector replicas/revisions. | Native service-level object access from any authorized replica; no mount or shared local path. |
| Immutability and concurrency | Shared mutable namespace. Unique names and the SQL claim make contention unlikely, but a mounted writer can still alter/delete any accessible file. | Natural immutable-object pattern with unique keys and create-without-overwrite. Strong consistency plus conditional writes/leases if later needed. |
| Parsing performance | Avoids an explicit second full-object download, but `zipfile` seeks and member reads traverse remote SMB. Must benchmark a 500 MiB archive and reconnect behavior. | One extra Blob-to-ephemeral download, then current parser reads local disk. Transfer is predictable and tunable; staging adds latency and temporary-disk demand. |
| Ephemeral capacity | Not required for the source archive. | Required. ACA provides 1 GiB at 0.25 vCPU, 2 GiB at 0.5 vCPU, 4 GiB at 1 vCPU, and 8 GiB above 1 vCPU. A 500 MiB max ZIP technically fits the smallest tier, but use 0.5 vCPU/2 GiB or reduce the cap until a worst-case staging/cleanup test proves safe. [ACA storage mounts](https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts) |
| Retention and deletion | Application job plus snapshots/Backup. Share soft delete does not recover one deleted file. | First-class per-object soft delete, container soft delete, versions, lifecycle policies, and optional Blob Backup. Easier to express and audit an expiry contract. |
| Accidental overwrite protection | Needs snapshots/backup; filesystem permissions are broad under the mount key. | Create condition, soft delete, optional versioning, and optional immutability. For UUID write-once payloads, prohibit overwrite instead of accumulating versions. |
| Malware gate | Requires application or third-party scanning. | Optional Defender on-upload scanning is native for ZIP block blobs. Do not make ingestion depend on it without a verdict, timeout, quarantine, false-positive, and cost design. |
| Initial implementation risk | **Lowest.** Mostly IaC/mount and private-DNS work, plus the still-required retention/checksum fixes. | **Moderate.** Code, schema, dependency, retries, staging, and failure-injection work. The change is bounded to upload storage and import orchestration. |
| Long-term operations | Key storage/rotation, mount health, SMB behavior, snapshots/backup, cleanup, and shared-write access review. | SDK/identity/RBAC, private endpoint/DNS, lifecycle/reconciliation, staged-download cleanup, and object metrics. No account key in the workload path. |
| Reversibility | Fastest first Azure landing, but a later Blob change repeats storage and database migration work. | Local filesystem and Files adapters can coexist behind the same seam. Object keys can be copied back and references dual-read during rollback. Building the seam now avoids a second architecture migration. |

### Why not “Files now, Blob later”

That sequence is superficially safer because it preserves `/app/uploads`, but SPM-25 already has to
add checksum, deletion, retention, reconciliation, and migration behavior. Choosing Files now adds
key/mount operations and then repeats the data-reference and validation migration later. With one
2.6 MB observed object and no Azure implementation yet, this is the cheapest point to introduce the
portable seam. Choose Files only if delivery time is more valuable than managed-identity-only
access and the owner explicitly accepts a second migration trigger.

## Low-volume Israel Central cost

### Reproducible inputs

The public [Microsoft Retail Prices API](https://prices.azure.com/api/retail/prices?api-version=2023-01-01-preview&currencyCode=USD)
was read on 2026-08-26 with these filters:

```text
armRegionName eq 'israelcentral' and serviceName eq 'Storage'
  and productName eq 'Files v2' and skuName eq 'Hot ZRS'

armRegionName eq 'israelcentral' and serviceName eq 'Storage'
  and productName eq 'General Block Blob v2' and skuName eq 'Hot ZRS'

serviceName eq 'Virtual Network' and productName eq 'Virtual Network Private Link'

serviceName eq 'Azure DNS' and meterName eq 'Private Zone'
```

Relevant zero-tier USD Consumption meters were:

- Blob Hot ZRS stored data: USD 0.025/GB-month.
- Blob Hot LRS stored data: USD 0.020/GB-month.
- Azure Files Hot ZRS stored data: USD 0.0325/GB-month, plus actual metadata at
  USD 0.0396/GB-month; reads/other operations USD 0.00572/10,000 and writes/lists
  USD 0.0715/10,000.
- Azure Files Hot LRS stored data: USD 0.026/GB-month, plus actual metadata at
  USD 0.0396/GB-month.
- One Private Endpoint: USD 0.01/hour, or USD 7.30 at 730 hours/month.
- Private Link data processed: USD 0.01/GB in the first tier in each direction.
- First Azure Private DNS zone: USD 0.50/month; first million queries USD 0.40.

### Comparable example

Assume one chosen storage service, one private endpoint, one private DNS zone, 10 GB of active ZIPs
retained for the whole month, and those same 10 GB written once and read once through the private
endpoint. Ignore metadata size, operation counts, soft-deleted/version/snapshot/backup copies,
Defender, monitoring, support, taxes, discounts, and any existing shared DNS zone.

| Item | Azure Files Hot ZRS | Blob Hot ZRS |
|---|---:|---:|
| 10 GB active data | USD 0.325 | USD 0.250 |
| Private endpoint, 730 hours | USD 7.300 | USD 7.300 |
| First private DNS zone | USD 0.500 | USD 0.500 |
| 20 GB total private-link processing | USD 0.200 | USD 0.200 |
| **Illustrative subtotal** | **USD 8.325** | **USD 8.250** |

The USD 0.075/month capacity difference is immaterial. File metadata/SMB transactions and Blob
block operations will differ, but at one to four users they are unlikely to overtake the common
private-network floor. Obtain a portal/calculator quote and measure transaction patterns before
apply; public meters are not a subscription quote.

Soft-deleted objects, versions, snapshots, and vault copies continue to consume billable storage.
A retention promise must model recoverable copies, not only visible active objects.

## Recommended Blob contract

### Storage and access

- Dedicated GPv2 `Standard_ZRS` account in Israel Central; Hot access tier; one private `blob`
  endpoint and linked `privatelink.blob.core.windows.net` zone; public network and anonymous blob
  access disabled.
- Disable Shared Key authorization. Use Container Apps managed identities and Azure RBAC scoped to
  the upload container. The API needs create/write and failure-compensation delete. The collector
  needs read; if it owns terminal cleanup, scope its write/delete authority explicitly. A separate
  scheduled cleanup identity is cleaner but not mandatory at this volume.
- Platform-managed encryption keys initially. Customer-managed keys require a separate accepted
  compliance requirement and key-recovery plan.
- Use no browser SAS in the initial design. If direct-to-Blob browser upload is later needed, prefer
  a short-lived user-delegation SAS and separately review public endpoint/firewall, CORS, CSRF,
  object-key authorization, maximum size, abort, and finalization semantics.

### Application publication protocol

1. API authenticates and authorizes the user before accepting bytes.
2. Generate an opaque unique object key; never use the client filename as authority or path.
3. Stream to a block blob with overwrite disabled while counting bytes and hashing SHA-256. Enforce
   the 500 MiB limit during the stream and abort/clean uncommitted data on failure.
4. After Blob commit, persist the backend, object key, size, SHA-256, ETag/version, and status in one
   database transaction. On database failure, attempt immediate object deletion and record a
   sanitized cleanup failure without logging the filename or object contents.
5. A periodic reconciliation pass finds old objects with no database row and rows whose objects are
   missing. It alerts before destructive repair and follows the accepted retention policy.

### Collector protocol

1. Keep the existing conditional SQL update as the sole job claim.
2. Download the claimed blob to a UUID-named ephemeral file; cap bytes again; verify stored length
   and SHA-256; fail closed on mismatch.
3. Run the current seekable `ZipFile`/`ijson` parser unchanged against the local temporary path.
4. Delete the temporary file in `finally`, including cancellation, parser error, and replica-shutdown
   recovery. A startup sweep may delete only clearly owned stale temp names.
5. Mark database success/error before applying the separately approved source-object retention
   action. An object deletion failure is a cleanup alert, not an ingestion rollback.

### Transient staging and deletion proposal for owner approval

Treat source ZIPs solely as job payloads, not database backups or records of authority. The
storage service must survive request completion, replica replacement, and bounded processing
retries; the object must not survive successful processing as a product-retention feature.

| State/copy | Recommended starting policy | Consequence |
|---|---|---|
| Pending/processing/retryable blob | Retain only while the database job is legitimately active or within its bounded automated-retry policy. | Supplies the crash-safe API-to-collector handoff without promising archival retention. |
| Successful blob | Schedule deletion immediately after the terminal success transaction commits and reconciliation proves the imported result. | Raw Spotify export data no longer remains after its product purpose is complete. A deletion failure becomes a cleanup alert and retry, not an ingestion rollback. |
| Terminal failed/cancelled blob | Schedule deletion immediately after the terminal state commits; retain sanitized error metadata and checksum, not the ZIP. | Diagnosis cannot depend on indefinitely retaining personal source data; a later retry requires a fresh authorized upload. |
| Unreferenced/orphan blob | Delete after a short reconciliation grace period, proposed at 24 hours. | Compensates for an API crash after Blob commit but before database publication without leaving abandoned uploads indefinitely. |
| Blob and container soft delete | Disabled initially in the dedicated transient account. | Makes application deletion meaningful instead of retaining a hidden recoverable copy. Accidental deletion before processing requires a fresh upload; ZRS and application state/retries mitigate infrastructure failure, not operator deletion. |
| Blob versioning | Disabled initially; uploads are UUID-keyed and create-only. | Avoids indefinite hidden versions and purge complexity. Enable only if overwrite/version recovery becomes a real requirement, with lifecycle deletion for old versions. |
| Azure Backup | None. | Account loss can lose pending/retry payloads and require a fresh upload. Imported plays are protected through the PostgreSQL recovery design. |
| Storage account lock | `CanNotDelete` after migration/recovery validation. | Protects against account deletion but requires an explicit unlock boundary for retirement. |

The terminal-state transaction and object deletion cannot be atomic. Use an outbox or explicit
`source_delete_pending` state so a crash between them is repaired deterministically. Do not report
the object as purged until Blob confirms absence. Azure lifecycle evaluation is only a fallback for
unreferenced-object cleanup and does not establish a hard deletion deadline; measure the complete
terminal-to-absence path before making a privacy promise.

Microsoft recommends versioning plus soft delete for critical Blob data. The narrower recommendation
here is an inference based on the owner's statement that these are unique, create-only, transient
job payloads whose privacy exposure grows with hidden recoverable copies—not an Azure default. If
originals are later classified as critical records, use versioning and vaulted backup only through
a new owner-approved retention decision. [Blob soft delete versus versioning](https://learn.microsoft.com/en-us/azure/storage/blobs/soft-delete-vs-versioning-options)

## Migration and reversibility

1. Introduce an `UploadStore` interface with local-filesystem and Blob implementations. Keep ZIP
   parsing independent of Azure; the store returns a verified local staging path or seekable handle.
2. Evolve `ImportJob.file_path` to an explicit storage locator without silently reinterpreting old
   rows. Prefer separate `storage_backend`, `object_key`, `content_sha256`, and deletion/recovery
   fields; preserve legacy-path reads during the bounded migration. This schema/data change belongs
   to a separately accepted SPM-25 plan.
3. Copy retained source archives to opaque Blob keys, compute and compare hashes, then update only
   validated rows. The measured estate has one small object, but rerun the sanitized inventory at
   migration time.
4. Run dual-read with new writes going only to Blob. Reconcile counts, bytes, hashes, job references,
   and representative parse results. Do not dual-write because partial success creates ambiguous
   authority.
5. Before first Azure production write, rollback can return new writes to the filesystem adapter.
   After first Azure write, follow ADR 0002's forward-recovery boundary: copy/verify referenced
   objects into the replacement store before changing locators; do not make DigitalOcean writable
   again implicitly.
6. Remove legacy-path support only after the retention window expires, no old referenced object
   remains, restore/delete rehearsals pass, and the owner authorizes the cleanup.

## Mandatory implementation and cutover gates

- Unit and integration tests for both adapters, create-without-overwrite, 500 MiB boundary,
  interrupted multipart upload, database-failure compensation, orphan detection, missing object,
  size/hash mismatch, retry, cancellation, stale temp cleanup, and retention state transitions.
- A production-shaped synthetic ZIP proof through Static Web Apps origin -> authenticated API ->
  private Blob -> collector staging -> parser -> PostgreSQL, including a collector revision restart
  after upload and during download.
- Verify private DNS resolution from both apps, public endpoint denial, anonymous denial, Shared Key
  denial, exact managed-identity role scope, storage diagnostic logs, and alerts for authorization,
  latency, capacity, reconciliation, and deletion failures.
- Measure 500 MiB upload/download time, private-link bytes, Blob transactions, collector ephemeral
  peak, CPU/memory, time to first parsed batch, total import time, and temp cleanup. Reduce the size
  limit or raise collector CPU/ephemeral capacity if headroom fails.
- Rehearse soft-delete recovery for one blob and one deleted container, then exercise expiry and
  prove the owner-approved hard-deletion bound. If Backup is selected, restore from the vault rather
  than treating configuration as proof.
- Refresh Israel Central account/SKU/ZRS availability, private-endpoint quota, policy, and the full
  subscription quote immediately before apply. No result in this note grants apply authority.
- Run a privacy review of key naming, storage/log fields, retention, soft-deleted copies, diagnostic
  logs, backups, operator access, malware verdicts if enabled, and customer deletion behavior.

## Owner decision

On 2026-08-26 UTC, after clarifying that each ZIP is uploaded once per user and
has no purpose after processing, the owner replied “option B approved” to this
cohesive choice:

1. **Blob Hot ZRS**, dedicated GPv2 account, private endpoint, public/anonymous/Shared Key disabled,
   and managed-identity RBAC.
2. Keep a blob only while its job is pending, processing, or retryable; schedule deletion
   immediately after any terminal state; delete unreferenced objects after a proposed 24-hour
   reconciliation grace period; disable soft delete, versioning, and Blob Backup.
3. Require the abstraction, checksum, reconciliation, staging, privacy, and recovery gates above.

Choose **Azure Files Hot ZRS** instead only if preserving the path contract is the overriding
near-term objective and the owner accepts the storage-account-key boundary, broader shared-write
surface, file-level recovery tooling, and a later Blob migration trigger. If Files is selected, use
a dedicated account, SMB rather than NFS, a `file` private endpoint, the same application SHA-256
and orphan protocol, explicit key rotation, ZRS, and an approved snapshots/Backup plus deletion
policy; mounting the share alone does not close the current durability gaps.

This approval selects transient Blob staging and the immediate terminal-deletion package. It does
not grant Azure apply, deployment, production-data access, migration, cutover, credential, or
destructive-cleanup authority.
