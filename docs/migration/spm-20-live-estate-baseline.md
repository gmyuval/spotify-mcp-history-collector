# SPM-20 live estate baseline

Captured at `2026-08-23T22:59:22.967447Z` for SPM-20. This is a sanitized,
read-only pre-migration baseline. No Azure apply, DigitalOcean mutation, deployment,
credential value, provider identifier, network address, email address, or personal
Spotify data is included.

Repository revision: `6cd855e0c7162443fe6e22996b1398a826770ae3`

Deployed revision: `67d85e5a60a2d1a35a8bb156d8555bb77c9ec99e`

Provider evidence hash:
`67f4f5f0d3db5de1cc3a40a0a04f786faca1abc777209327574dd1759b63aaee`

The machine-readable companion is
[`spm-20-live-estate-baseline.json`](spm-20-live-estate-baseline.json). The
allowlisted collector is [`scripts/capture_estate_baseline.py`](../../scripts/capture_estate_baseline.py).
It keeps raw provider responses and correlation selectors in memory, writes only
validated aggregates, requires explicit provider contexts, and fails closed if any
planned read fails or returns malformed JSON. The aggregate collector covers 19
DigitalOcean and three Azure collection families; product linkage was separately
correlated with read-only probes, and SPM-27 owns the cutover-time recapture.

## Measured evidence

### Repository, deployment, and runtime

- The deployed checkout is clean on `main`, at the revision above, and 41 commits
  behind `origin/main`. The current repository deployment workflow is manual-only.
- The last successful deployment run matching the live revision completed on
  2026-04-04. It predates the current manual-only trigger posture.
- Production Compose runs six services: API, Caddy, collector, explorer, frontend,
  and OAuth2 proxy. It declares three named volumes for uploads and Caddy state.
- All six services were running. API, frontend, and explorer reported Compose health;
  Caddy, collector, and OAuth2 proxy had no Compose health status.
- Public and direct-origin `/healthz` probes both returned HTTP 200 with TLS
  verification enabled. The observed certificate expires on 2026-10-22.
- Deployment requires an exact repository revision and deployment UUID. Migrations
  run before service replacement, but there is no automatic database rollback.
- The repository has 13 Alembic revisions with expected head `013`, and 25 expected
  application tables. The live database is also at `013`, with 26 total tables
  including migration metadata, 199 columns, and an estimated 10,214,372 rows.
- Application images are built on the target from service-scoped requirements files;
  no product registry repository was found.
  Mutable base tags and target rebuilds mean image rollback is not reproducible.
  SPM-4 still owns the Docker packaging decision.

### Dependency and image provenance

- The current developer baseline has no `environment.yml`; it uses pinned uv 0.12.3,
  Python 3.14.7, and the committed `uv.lock`. CI performs a locked workspace sync,
  does not use editable pip installs, and runs five isolated package-test jobs.
- At revision `bf4758bfa113106db135175d2c6cf90bfa8ceb56`, the historical developer
  path used Conda with Python 3.14, pip-tools, pre-commit, and five editable
  workspace packages. This is provenance evidence, not the current packaging path.
- The manual deployment gates still install five workspace packages editable and
  install Ruff without a version pin. SPM-34 owns that contract drift.
- Production Docker builds remain requirements-based: pip-tools 7.5.3 on Python
  3.14.7 compiles the service-scoped requirement files. `docker-requirements.lock`
  records hashes for 15 inputs and outputs. The four Dockerfiles consume their
  service-specific files plus shared requirements where applicable. Exact versions
  are pinned, but package hashes are absent.
- All four application Dockerfiles reference `python:3.14-slim`; Compose directly
  references `quay.io/oauth2-proxy/oauth2-proxy:v7.14.2` and `caddy:2-alpine`.
  Git object hashes for the lock, production Compose file, and every Dockerfile are
  recorded in the machine artifact. Base-image digests, resulting application-image
  identities, and build timestamps were unavailable and remain owned by SPM-23.

### DigitalOcean product estate

The account-wide safe capture observed 9 droplets, 4 databases, 18 domains, 9
firewalls, 4 VPCs, 5 projects, 14 snapshots, 27 tags, 15 alert policies, 3 uptime
checks, one CDN endpoint, one certificate, 40 custom images, two registry
repositories, one reserved IP, and no block volumes, load balancers, Kubernetes
clusters, or Apps Platform applications. Product linkage used live endpoints, the
host address, project membership, DNS relations, and provider associations without
retaining their values. No product linkage was found for the account-level CDN,
custom images, registry repositories, reserved IP, snapshots, or block volumes.

| Alias | Measured state | Classification |
| --- | --- | --- |
| `do-droplet-primary` | One active fra1 `s-2vcpu-2gb` host runs the six-service stack. | Retain temporarily for rollback, then retire under SPM-29. |
| `do-firewall-primary` | One linked firewall has three inbound and three outbound rules. | Retain with the droplet, then retire. |
| `do-vpc-default` | The droplet uses the regional default VPC. | Explicit exception; do not delete as product work without proving exclusive ownership. |
| `do-project-production` | The project contains the product host plus four databases. | Explicit exception because unrelated resources may share it. |
| `do-postgresql-primary` | One online PostgreSQL 18 cluster, one node, 60 GiB provisioned storage. | Migrate; retain for rollback, then retire. |
| `do-valkey-primary` | One online Valkey 8 node. | Replace after the SPM-4 cache decision; retain through rollback. |
| `do-dns-zone-shared` | The product record shares a zone with 20 other records. | Explicit exception; never retire the entire zone as product work. |
| `do-dns-record-primary` | One A record points directly at the product host, TTL 300. | Replace during the authorized SPM-27 cutover. |
| `do-uptime-check-primary` | One enabled HTTPS check runs from European and US regions. | Replace with accepted Azure monitoring, then retire. |
| `do-provider-certificate-primary` | One provider certificate is domain-linked; actual runtime use is unverified. | Explicit exception until ownership and use are verified. |
| `do-droplet-backup-set` | Backups are enabled and five provider backup objects were observed. | Retain through the rollback window, then retire with the host. |
| `do-trusted-source-tags` | PostgreSQL trusts two tag rules in addition to one host and one address rule. | Retain until shared consumers and cutover rules are reconciled. |

The exact July 2026 recurring cost attributed to the product core was USD 108.00:
USD 20.10 for the droplet and backups, USD 72.90 for PostgreSQL, and USD 15.00 for
Valkey. The product-linked firewall, VPC, project, DNS, certificate, monitoring,
trusted-source rules, and local volumes had no separate July line item in the
measured invoice.

### Database and durable state

- Managed PostgreSQL reports provider version 18; the live server reports 18.4.
  Provisioned storage is 61,440 MiB and measured database size is 3,390,977,727
  bytes. The only observed extension is `plpgsql`.
- The sanitized schema baseline contains 26 public tables and 199 columns, with
  10,214,372 estimated rows. Its SHA-256 hashes compact JSON for ordered
  `(table_name, column_name, data_type, is_nullable)` tuples from
  `information_schema.columns`.
- Eight managed database backups were visible from 2026-08-16 through 2026-08-23.
  The configured retention policy, restore-test evidence, and agreed recovery
  objectives were unavailable; SPM-26 owns those gaps.
- One retained upload archive occupies 2,606,440 bytes. The baseline records its
  count and a sanitized SHA-256 manifest hash. Successful imports do not delete
  source archives, and the application defines no cleanup, retention, per-object
  checksum, or backup policy for this volume; SPM-25 owns that contract.
- Caddy's persistent data and configuration occupy 76 KiB and 16 KiB respectively.
  They are replaceable from the accepted ingress design rather than retention inputs.
- The required external authenticated-email allowlist is absent. A tracked legacy
  allowlist remains present with two lines. This must be migrated before any
  separately authorized production deployment.

### External couplings

- GitHub has a `production` environment. Repository secret names observed were
  `DROPLET_IP` and `SSH_PRIVATE_KEY`; no repository variables or production
  environment secrets/variables were present. The workflow contract also names
  `DO_API_TOKEN`, `DO_DB_CLUSTER_ID`, and `DROPLET_SSH_HOST_FINGERPRINT`.
  Live placement of the first two was not visible; the fingerprint is not configured.
- DigitalOcean DNS points `music.praxiscode.dev` directly at the host with TTL 300.
  TLS is automated by Caddy. Registrar ownership and DNS change authority were
  unavailable from read-only provider evidence.
- Spotify Accounts OAuth and the Spotify Web API are required for authorization,
  token refresh, and playback-history collection; the HTTPS callback is
  `/auth/callback`. Google OAuth protects operator-facing routes through callback
  `/oauth2/callback`. Provider-console redirect inventories and control-plane
  ownership were unavailable.
- MusicBrainz is a public metadata dependency. Soundcharts is an optional
  credential-backed audio-feature dependency. Production Valkey is an external
  cache dependency that SPM-4 must replace or deliberately retain.
- MCP clients use `/mcp/v1`, `/mcp/tools`, and `/mcp/call`. Caddy routes `/healthz`,
  `/mcp/*`, `/auth/*`, and `/api/*` to the API without Google forward-auth;
  `/oauth2/*` goes to OAuth2 proxy; `/admin/*` goes to the frontend with Google
  forward-auth. Explorer `/`, `/login`, and `/static/*` are public, while its other
  routes require Google forward-auth.
- Root SSH is the initial provisioning boundary; the routine workflow uses the
  deploy SSH principal. The checked-in deployment guide's route table is stale
  relative to this measured Caddyfile contract and remains owned by SPM-34.

### Azure readiness

One enabled subscription and tenant were visible under sanitized hashes
`c560ebbf4f76` and `4f116b141f93`. The intended environment is production. The
subscription contains 11 resource groups and 67 resources, but no product-specific
resource-group or final ownership boundary exists. The authenticated identity is a
user with four subscription-scope role assignments exposing Owner, Key Vault
Secrets Officer, and Storage Blob Data Contributor capabilities.

| Candidate region | Compute quota | Container Apps profiles | PostgreSQL | Posture |
| --- | --- | --- | --- | --- |
| `germanywestcentral` | 0 of 10 vCPUs used | 25; Consumption, Flex, D/E, DC/EC represented | No tiers or versions reported | Reject unless availability changes. |
| `westeurope` | 0 of 10 vCPUs used | 11; Consumption, Flex, D/E, GPU represented | 3 tiers and 8 versions | Candidate. |
| `northeurope` | 0 of 10 vCPUs used | 13; Consumption, Flex, D/E, A100 represented | 3 tiers and 8 versions | Candidate. |

The three PostgreSQL tiers in each viable region are Burstable, General Purpose,
and Memory Optimized. Required provider types for Container Apps, PostgreSQL
Flexible Server, Redis Enterprise, ACR, Storage, Key Vault, Managed Identity,
private endpoints, and Log Analytics are registered. Redis Enterprise SKU detail
is unavailable because its optional CLI preview extension was not installed; no
installation or provider mutation was needed for this read-only baseline.

## Inferences and decisions

- DigitalOcean remains the production authority until a separately accepted
  migration and deployment plan says otherwise. This baseline authorizes no cutover.
- The droplet, firewall, backups, databases, and product DNS record need a bounded
  rollback-retention period; the shared default VPC, project, and DNS zone are not
  safe product-level deletion units.
- Upload data and PostgreSQL data are migration inputs. Caddy state is replaceable
  from the accepted ingress design rather than a portable production dependency.
- `westeurope` and `northeurope` are viable candidates from the measured
  capability surface. `germanywestcentral` is not a viable PostgreSQL target for
  this subscription in the current evidence.
- Production packaging remains requirements-based. SPM-4 owns any Docker packaging
  change, and SPM-23 owns reproducible image publication and provenance.
- The deployment-contract drift belongs to SPM-34. Operator-only control-plane
  ownership belongs to SPM-35. Neither gap justifies a production mutation here.

## Unavailable evidence

| Gap | Owning follow-up |
| --- | --- |
| DigitalOcean access-principal names, scopes, rotation, and service-account ownership | SPM-35 |
| Registrar ownership and DNS change authority | SPM-35 |
| Spotify and Google OAuth control-plane ownership and provider-console redirects | SPM-35 |
| Production SSH fingerprint secret and external allowlist migration | SPM-24 |
| PostgreSQL restore test and agreed recovery objectives | SPM-26 |
| Configured managed PostgreSQL backup retention | SPM-26 |
| Upload-volume cleanup, retention, per-object checksum, and backup policy | SPM-25 |
| Base-image digests, application-image identities, and build timestamps | SPM-23 |
| Azure Redis Enterprise SKU detail for the selected cache architecture | SPM-4 |
| Final cutover-time recapture and rollback validation | SPM-27 |
| Accepted resolution of deployment-contract drift | SPM-34 |

SPM-34 and SPM-35 were created from gaps first proven by this baseline. The other
gaps remain with their existing owning tickets, avoiding a duplicate issue queue.

## Reproduction and safety

Run the collector only with authenticated, explicitly selected provider contexts:

```powershell
python scripts/capture_estate_baseline.py --live `
  --doctl-context <context> `
  --azure-subscription <subscription> `
  --output <sanitized-output.json>
```

The command plan contains list/show reads only. The capture does not apply Azure
resources, mutate DigitalOcean, connect to production application data, dispatch a
deployment, or write raw provider payloads. Before any separately authorized
production deployment, configure `DROPLET_SSH_HOST_FINGERPRINT` and complete the
documented external allowlist migration.
