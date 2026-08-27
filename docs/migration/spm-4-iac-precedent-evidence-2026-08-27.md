# SPM-4 IaC precedent evidence - 2026-08-27 UTC

This dated note supports the open infrastructure-as-code choice in
[ADR 0002](../decisions/0002-azure-target-architecture-and-migration-boundaries.md). It audits the
current local Agrisense Terraform implementation and compares its reusable operating precedent
with the narrower LARP Store Bicep precedent and Spotify MCP's selected Azure target.

It grants no Azure, deployment, credential, DNS, OAuth, production, state, tracker, or repository
delivery authority. No Terraform or Bicep preview, plan, apply, refresh, import, workflow, cloud
query, production query, state read, credential read, or remote-state read was performed.

Evidence labels used below:

- **Configured** - directly present in source at the pinned local revision.
- **Exercised** - the repository's accepted current-state or durable execution record says the
  path ran against Azure. This audit did not independently contact Azure.
- **Inferred** - a conclusion from configured or exercised evidence, with the remaining proof
  stated explicitly.
- **Absent** - a repository-wide tracked-source search found no matching implementation.

## Repository and authority pins

All Git observations were local and read-only. Remote **names**, never remote URLs, were queried.

| Checkout | Branch / upstream | Full HEAD | Ahead / behind | State at audit start |
|---|---|---|---:|---|
| `D:\projects\agrisense` | `main` / `origin/main` | `82e78a0f57ee84f2cc03094d9e8c9019916ff02b` | `0 / 0` | Clean; sole remote name `origin`. |
| `D:\projects\larp-store` | `main` / `origin/main` | `89feabb9d096157365fc0a799d1793057d512189` | `0 / 0` | Clean; sole remote name `origin`. |
| `D:\projects\spotify-mcp-history-collector\build\worktrees\spm4-architecture-decision` | `codex/spm-4-architecture-decision` / `origin/main` | `271b009cf3cb837f95dacab9d6db8d477b7da3ce` | `2 / 0` | Root-owned modified ADR/current-state/index files, five existing untracked SPM-4 evidence notes, and pre-existing `.local-data/**`; all preserved. This note is the delegate's only write. |

Applicable instructions were read completely from:

- `D:\projects\agrisense\AGENTS.md`;
- `D:\projects\agrisense\docs\agent\memory\README.md` and the infrastructure/migration topics it
  routes to;
- `D:\projects\larp-store\AGENTS.md` for the limited sibling comparison;
- `D:\projects\spotify-mcp-history-collector\AGENTS.md` and
  `D:\projects\spotify-mcp-history-collector\docs\agent\orchestration.md`;
- the current Accepted ADR 0002, its index, and the existing SPM-4 Azure architecture evidence in
  this worktree.

The sibling repositories are evidence only. Their issue trackers, credentials, resource names,
deployment authority, production data, and cloud assumptions do not transfer to Spotify MCP.

## Bottom line

The Agrisense evidence **materially strengthens Terraform**: it removes the earlier claim that the
owner has no operating Terraform precedent, and it demonstrates a real Israel Central landing
zone with PostgreSQL Flexible Server B1ms/P4, private networking, Blob, Key Vault, ACR, Azure
Monitor, managed identities, GitHub OIDC image publication, remote Blob state, and an executed
DigitalOcean-to-Azure cutover.

It does **not** overturn the recommendation. For Spotify MCP, **Bicep remains the narrower
recommendation**, now by a modest rather than decisive margin, because:

1. Spotify MCP is deliberately Azure-only.
2. The LARP Bicep precedent is much closer to the selected runtime shape: Container Apps,
   a manually triggered migration Job, per-workload identities, PostgreSQL, ACR, Key Vault,
   observability, and separate read-only preview versus apply identities.
3. At 1-5 users, a separate sensitive Terraform state service, its imperative bootstrap,
   lock/recovery procedures, provider lifecycle, and environment state separation are fixed
   operational costs that provide no user-facing value.
4. Agrisense's Terraform **runtime is live**, but its infrastructure control plane is still local
   and manual: there is no Terraform CI plan, no IaC apply workflow, no scheduled drift detector,
   no exact Terraform CLI pin, no state-recovery/force-unlock runbook, no import blocks, no
   non-production state, and no lifecycle guard on its durable resources.

This is not a rejection of Terraform. If the owner values standardizing on the production-proven
Agrisense toolchain more than minimizing Spotify MCP's control-plane machinery, Terraform is a
credible choice **only with the missing controls below added before the first apply**. Do not mix
Bicep and Terraform inside one Spotify MCP resource ownership boundary.

## Agrisense Terraform inventory

### Toolchain, providers, and locks

- **Configured:** `D:\projects\agrisense\infra\azure\providers.tf:1-13` requires Terraform
  `>= 1.9`, `hashicorp/azurerm ~> 4.0`, and `hashicorp/random ~> 3.6`.
- **Configured:** `D:\projects\agrisense\infra\azure\.terraform.lock.hcl:4-21` selects
  `azurerm 4.80.0` with checksums; lines 24-42 select `random 3.9.0` with checksums. The committed
  lock therefore reproduces provider selections even though the constraints are ranges.
- **Absent:** no `.terraform-version`, `.tool-versions`, mise/asdf pin, setup-terraform action, or
  equivalent exact Terraform CLI version exists in the tracked repository.
- **Measured host context, not repository authority:** the read-only local probes returned
  Terraform `1.15.8` and OpenTofu `1.12.5`. No Agrisense OpenTofu source, lock, workflow, or
  documented OpenTofu execution was found; OpenTofu compatibility is therefore unproven and is not
  part of the precedent.
- HashiCorp documents that the dependency lock records exact provider selections and checksums,
  while the Terraform CLI itself is governed separately by `required_version`:
  [dependency lock](https://developer.hashicorp.com/terraform/language/files/dependency-lock) and
  [version constraints](https://developer.hashicorp.com/terraform/language/expressions/version-constraints).

### Files and module shape

The tracked Terraform/OpenTofu inventory is exactly:

```text
infra/azure/.terraform.lock.hcl
infra/azure/compute.tf
infra/azure/data.tf
infra/azure/dns.tf
infra/azure/identity.tf
infra/azure/keyvault.tf
infra/azure/monitoring.tf
infra/azure/network.tf
infra/azure/outputs.tf
infra/azure/providers.tf
infra/azure/terraform.tfvars.example
infra/azure/variables.tf
```

- **Configured:** one flat root module, split into files by concern. There are 60 `resource`
  declaration blocks and one data-source block, including `for_each` resources whose live instance
  count is higher. No child `module` block exists. The layout is also described at
  `D:\projects\agrisense\infra\azure\README.md:12-28`, although that README's claims that the
  backend is commented and Azure is still plan-only are stale relative to current source and
  accepted current state.
- **Absent:** no Terraform `module`, `import`, `moved`, or `removed` block; no `terraform import`
  procedure; no Terraform CLI workspace command or `terraform.workspace` expression.
- **Configured:** this root is production-specific. The resource group is named as production at
  `D:\projects\agrisense\infra\azure\network.tf:6-10`, and default tags include `env = "prod"` at
  `D:\projects\agrisense\infra\azure\variables.tf:18-26`. There is no non-production parameter
  set, separate backend key, or separate root.
- HashiCorp explicitly says CLI workspaces are not appropriate when deployments require separate
  credentials and access controls. Spotify MCP should therefore use separate environment roots or
  backend configurations, not a workspace switch:
  [Terraform workspaces](https://developer.hashicorp.com/terraform/language/state/workspaces).

### Azure resources and topology

The Agrisense root declares:

| Concern | Configured evidence | Relevance to Spotify MCP |
|---|---|---|
| Region and resource group | Israel Central is the default at `variables.tf:6-10`; the production RG is at `network.tf:6-10`. | Direct regional precedent, but no production/non-production separation pattern. |
| Network | VNet and VM, delegated PostgreSQL, and private-endpoint subnets at `network.tf:12-69`; PostgreSQL and service private DNS zones/links at `network.tf:135-175`. | Reusable naming, subnet derivation, private DNS, and service-endpoint drift lessons. Spotify needs an ACA environment subnet rather than the VM subnet. |
| Compute | Public IP, NIC, Linux VM, managed data disk, attachment, and VM RBAC at `compute.tf:9-118`. | Not portable as target compute; Spotify selected split Container Apps and Static Web Apps. |
| PostgreSQL | Flexible Server 18, delegated private network, 32 GiB P4, selectable SKU, and fixed zone at `data.tf:9-30`; B1ms default at `variables.tf:41-45`. | Direct B1ms/P4 precedent. Spotify's version, backup retention, no-HA posture, private endpoint/VNet model, role split, and restore gates still need its own implementation. |
| Blob | GPv2 Hot LRS account, public and Shared Key disabled, private container, private endpoint, and DNS at `data.tf:112-155`. | Strong managed-identity/private-Blob pattern, but Spotify requires ZRS, transient deletion semantics, and separate API/collector roles. |
| ACR | Premium, admin disabled, public RBAC-gated push plus private VM pull at `data.tf:157-205`. | The auth split is reusable. Premium/private endpoint is not automatically justified for a 1-5-user Spotify deployment; price and network posture must decide it. |
| Key Vault | RBAC mode, public endpoint default-deny with deployer-IP exception, private endpoint, and purge protection at `keyvault.tf:12-63`. | Useful hardening evidence. Spotify needs one app-specific vault and separate secret-reader grants per API, collector, and migration identity. |
| Secrets | PostgreSQL and internal passwords are generated and written to Key Vault at `keyvault.tf:65-130`; external/provider secrets remain out-of-band at lines 99-105. | Demonstrates both patterns. Generated values still enter Terraform state; out-of-band values create a reconciliation boundary. Spotify must choose deliberately per secret. |
| Managed identities and OIDC | Separate VM and image-push identities at `identity.tf:1-34`; the GitHub-main federated credential and ACR-only `AcrPush` at `identity.tf:36-55`. | Reusable OIDC shape, but it is image publication only. It is not a plan or infrastructure-apply identity model. |
| Observability | Log Analytics, Application Insights, AMA/DCR, action group, RBAC, and alerts at `monitoring.tf:9-216`. | Resource patterns are reusable; VM-agent pieces are not. Spotify needs ACA-native log/metric and collector-liveness alerts. |
| DNS | Azure DNS service and mail records at `dns.tf:19-115`. | The record verification lesson is useful, but Spotify ADR 0002 keeps DNS ownership outside the application RG and does not authorize importing/deleting a zone. |

There is no Agrisense Terraform resource for Container Apps, a Container Apps environment or Job,
Static Web Apps, or a dedicated continuous collector. The current official AzureRM provider does
offer first-party resources for the target surfaces, including
[Container Apps environments](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/container_app_environment),
[Container Apps](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/container_app),
[Container Apps Jobs](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/container_app_job),
[Static Web Apps](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/static_web_app),
and [PostgreSQL Flexible Server](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/postgresql_flexible_server).
Provider availability is not local implementation evidence: Spotify would still be authoring and
testing those resources for the first time in this Terraform codebase.

## Terraform state, bootstrap, and recovery

### What is configured

- `D:\projects\agrisense\infra\azure\providers.tf:15-26` configures one `azurerm` backend Blob
  key with Microsoft Entra data-plane authentication. Its comments say the state account was
  bootstrapped imperatively before first apply with Shared Key disabled, versioning, 30-day soft
  delete, TLS 1.2, and no public Blob access.
- `D:\projects\agrisense\docs\agent\memory\deployment-infra.md:20-24` records a distinct
  Terraform-state resource group in the accepted operating memory.
- `D:\projects\agrisense\.gitignore:106-114` excludes the plugin directory, tfvars, state,
  plans, and crash logs while deliberately retaining `.terraform.lock.hcl`.
- HashiCorp confirms that the AzureRM backend stores state in Blob and uses Azure Blob native
  locking and consistency checking, with Microsoft Entra ID and OIDC among the recommended auth
  methods: [AzureRM backend](https://developer.hashicorp.com/terraform/language/backend/azurerm).

### What is exercised or still uncertain

- **Exercised, repository-recorded:** the state backend exists as part of the executed cutover;
  Agrisense's accepted deployment memory names it and the backend is active in source.
- **Not independently verified here:** the live account's versioning, soft-delete duration,
  firewall, shared-key setting, encryption scope, role assignments, current state generation, and
  lock behavior. Those facts are documented in comments, but the bootstrap resource is outside
  Terraform and this audit did not contact Azure or inspect state.
- **Absent:** a checked-in bootstrap template for the state account; least-privilege plan/apply
  identity definitions for that backend; a state backup/restore rehearsal; `state pull/push`
  recovery instructions; a lock-timeout policy; a reviewed force-unlock procedure; and an import
  or state-reconstruction runbook.
- HashiCorp warns that state and plan files can contain database passwords and other sensitive
  values. Agrisense explicitly stores its generated PostgreSQL and application passwords in state
  before writing them to Key Vault, so backend recovery and access are security boundaries, not
  plumbing: [sensitive data](https://developer.hashicorp.com/terraform/language/manage-sensitive-data)
  and [state backends](https://developer.hashicorp.com/terraform/language/state/backends).

### Spotify consequence

If Terraform is selected, Spotify MCP needs a **separate, owner-run bootstrap layer** for each
state boundary, with immutable documentation of:

1. storage account/container creation and location;
2. Shared Key/public access settings, encryption, versioning, soft delete, and retention;
3. plan/apply principal access and break-glass access;
4. locking, lock timeout, force-unlock approval, and interrupted-apply handling;
5. state restore and reconstruction from Azure inventory;
6. separate production and non-production keys and identities; and
7. explicit handling of every secret-bearing attribute in plans, logs, artifacts, and state.

That is all defensible, but it is additional fixed work that Bicep does not require.

## Planning, applying, review, and drift

### Agrisense's actual control plane

- **Procedural gate:** infrastructure/deployment is plan-first in
  `D:\projects\agrisense\AGENTS.md:45-53`; repository changes receive protected-branch CI and
  review at lines 82-112.
- **Mechanical repository gate:** `.github/rulesets/main-protection.json:41-63` requires lint,
  typecheck, unit, integration, and coverage checks. None is a Terraform plan or validation check.
- **Absent:** a repository-wide search found no Terraform command in `.github/workflows/` and no
  Terraform invocation in the validation scripts. The local instructions at
  `infra/azure/README.md:39-53` describe `init`, `fmt`, `validate`, and `plan` from a signed-in
  operator CLI instead.
- **Exercised:** the durable migration record reports successive live-subscription plans and the
  eventual apply/cutover at
  `docs/agent/memory/hyperscaler-migration.md:51-67`, `74-155`, and `157-205`.
- **Configured deployment, not IaC apply:** `.github/workflows/cd-azure.yml:55-58` requests OIDC,
  and lines 96-140 use the narrowly scoped CD identity to push images. Its deploy job at lines
  153-257 ships runtime artifacts to the VM; it does not run Terraform.
- **Absent drift automation:** there is no scheduled or pull-request `terraform plan`,
  `-refresh-only`, or `-detailed-exitcode` gate. The cutover later discovered an Azure-added
  PostgreSQL subnet service endpoint as drift and codified it at `network.tf:45-49`, showing why a
  post-deploy drift pass is necessary.
- HashiCorp documents that normal plans refresh remote objects, `-refresh-only` isolates state
  reconciliation, and `-detailed-exitcode` makes change detection automatable:
  [terraform plan](https://developer.hashicorp.com/terraform/cli/commands/plan) and
  [refresh-only](https://developer.hashicorp.com/terraform/tutorials/state/refresh).

### Rollback and recovery

- **Strong application rollback, exercised:** Agrisense deploys commit-addressable images and has
  a tested `.last-good` runtime rollback. The accepted current state records older-image dispatch
  and automatic rollback at `docs/agent/current-state.md:50-61`; the implementation explains its
  database-revision guard at `docker/azure/vm-deploy.sh:10-36` and `283-357`.
- **Strong migration lesson, exercised:** the cutover found that a TimescaleDB version downgrade
  made the expected binary restore invalid and used a logical copy instead at
  `docs/agent/memory/hyperscaler-migration.md:157-176`. Spotify does not use TimescaleDB, but the
  transferable rule is to rehearse the exact source/target engine and extension path rather than
  infer data recovery from IaC success.
- **Weak infrastructure rollback:** no Terraform-specific infrastructure rollback or state
  recovery runbook was found. Reapplying old HCL can propose destructive changes and cannot undo
  data migration. No `lifecycle` block, including `prevent_destroy`, exists anywhere under
  `infra/azure/*.tf`.
- **Exercised deployment hazards:** the first apply/cutover exposed Key Vault data-plane reachability,
  quota, provider CLI, PostgreSQL preload/extension, and platform-added subnet drift issues at
  `docs/agent/memory/hyperscaler-migration.md:177-205`. These are valuable proof that an apparently
  clean plan is not an acceptance test.

## Evidence that Agrisense is live

This audit did not contact Azure or production. The repository evidence is nevertheless strong and
internally consistent:

- the accepted current-state record says the Azure cutover executed and DigitalOcean was later
  decommissioned at `D:\projects\agrisense\docs\agent\current-state.md:3`;
- it describes the live Israel Central VM, PostgreSQL, Redis, Blob, Key Vault, ACR, DNS, and
  Azure-only CD path at `docs/agent/current-state.md:50-61`;
- the durable infrastructure note names Terraform state and Azure DNS at
  `docs/agent/memory/deployment-infra.md:20-31` and the runtime Key Vault/managed-identity path at
  lines 34-40;
- local Git history contains the cutover fix, Azure CD flip, and DigitalOcean-retirement commits,
  culminating in the pinned current `main` HEAD.

Classification: **Agrisense is an exercised production Terraform precedent according to accepted
repository evidence, not a fresh cloud verification by SPM-4.**

## Limited Bicep comparison

The current LARP checkout contains **19** Bicep or Bicep-parameter files, not the 18 recorded in the
2026-08-25 SPM-4 evidence snapshot. The extra current file is part of the later runtime/migrator
identity split. This note corrects the count without attempting to replace the root orchestrator's
full LARP audit.

### What the LARP precedent already demonstrates

- **Configured:** subscription bootstrap, application RG, separate runtime/migrator identities,
  network, ACR, Key Vault, PostgreSQL B1ms/32 GiB, Log Analytics/Application Insights, a Container
  Apps environment, an API Container App, and a manual migration Job. The map is explicit at
  `D:\projects\larp-store\infra\README.md:12-39`, and the root modules are wired at
  `infra/main.bicep:97-211`.
- **Configured:** privileged Owner bootstrap is separate from RG-scoped deployment; the deploy
  identity cannot assign roles. A read-only preview identity has `Reader` plus only the what-if
  action, while the deploy identity has RG `Contributor` plus ACR push. See
  `infra/README.md:42-53` and `.github/workflows/deploy-nonprod.yml:1-18`.
- **Configured:** pull requests run `what-if`; apply is manual in the `nonproduction` GitHub
  environment under OIDC. See `.github/workflows/deploy-nonprod.yml:21-28`, `50-100`, and
  `107-144`.
- **Configured:** the migration Job is manual-triggered, one replica, no retry, same immutable image
  as the application, and gates the app deployment. See
  `infra/modules/migration-job.bicep:1-18`, `59-97`, and `98-170`.
- **Configured and exercised:** the Container App uses multiple revisions, commit-derived suffixes,
  managed-identity ACR pull, and explicit probes at
  `infra/modules/containerapps.bicep:45-83` and `84-190`; the runbook records traffic-shift rollback
  plus revision verification at `docs/operations.md:80-122`.
- **Exercised, repository-recorded:** non-production has been live in France Central since
  2026-07-21 and deploy/rollback were demonstrated, while no production deployment exists. See
  `docs/agent/current-state.md:55-60`.
- **Exercised drift discipline:** every PR receives what-if, and a documented manual post-deploy
  drift run maintains a dated provider-noise baseline. That first run found a real PostgreSQL
  subnet change. See `docs/operations.md:199-265`.

### Bicep gaps relevant to Spotify MCP

- LARP is a **non-production** precedent; Agrisense is the production precedent.
- LARP currently has one API app with scale-to-zero and explicitly no worker at
  `docs/operations.md:267-275`. Spotify needs a warm API, a warm continuous collector, and a
  separate migration Job.
- It has no Static Web Apps or transient Blob upload module. Those are new Spotify resources.
- It uses Entra-only PostgreSQL; Spotify has accepted separate Key Vault-backed database passwords.
- It has only a non-production app parameter file today, so Spotify's production/non-production
  promotion and parameter strategy still needs design.
- Entra application registrations and federated credentials are outside ARM/Bicep and are
  imperatively reconciled. LARP calls this out at `infra/README.md:42-53` and
  `docs/operations.md:61-78`.
- Bicep's default incremental deployment leaves omitted resources in place. LARP therefore needs
  explicit imperative cleanup/guards for identity changes. Microsoft documents the omission
  behavior at [ARM deployment modes](https://learn.microsoft.com/en-us/azure/azure-resource-manager/templates/deployment-modes).
- What-if is useful but not complete proof: Microsoft documents expansion limits,
  short-circuiting, and ignored resources at
  [Bicep what-if](https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/deploy-what-if).
- The Azure CLI/Bicep CLI version is not pinned in the repository, so deterministic validation
  still needs an explicit toolchain pin.

## Portability to Spotify MCP's selected target

| Spotify target surface | Agrisense Terraform precedent | LARP Bicep precedent | Required Spotify-specific work either way |
|---|---|---|---|
| Israel Central | **Direct:** current default and repository-recorded production region. | Parameterized but exercised in France Central. | Subscription provider/SKU/quota recheck; France remains unprovisioned contingency only. |
| Separate warm API and collector ACA apps | Provider supports it, but Agrisense has no ACA code. | API ACA module and revision rollback exist; no collector and current API scales to zero. | Two apps, `minReplicas: 1`, private collector ingress, liveness, scaling, MCP/SSE gates. |
| Static Web Apps | No local implementation. | No local implementation. | New resource, custom domain, deployment identity, artifact pinning, and frontend/API origin tests. |
| PostgreSQL B1ms, 32 GiB P4, no HA | **Direct:** B1ms/P4/32 GiB is configured and live by repository record. | B1ms/32 GiB configured; non-production only. | 14-day PITR, password-role split, private networking, restore rehearsal, capacity gates. |
| Transient Blob Hot ZRS | Blob/private endpoint/Entra pattern exists, but LRS archive semantics differ. | No Blob module. | ZRS, no Shared Key/public access, per-workload RBAC, immediate terminal deletion, 24-hour orphan cleanup, no soft delete/versioning/backup. |
| Key Vault | Direct RBAC/private-endpoint/deployer-path precedent. | Direct RBAC/firewall precedent. | App-specific vault; API/collector/migrator secret scopes; database-password rotation contract. |
| Managed identities | VM runtime plus image-push identity. | Separate runtime and migrator identities plus preview/deploy identities. | API, collector, migration, image-push, plan, and apply identities with environment-constrained OIDC. |
| ACR | Direct production precedent; Premium driven by private endpoint. | Basic non-production precedent. | Reprice Basic versus Premium; immutable digests; SBOM/provenance; managed-identity pulls. |
| Observability | Direct Log Analytics/App Insights/alerts; VM-agent portions do not transfer. | Direct workspace/App Insights foundation. | ACA logs/metrics, collector liveness, migration/import/DB alerts, redaction and ingestion budget. |
| Migration Job | No ACA Job. | Direct manual Job and deploy gate. | Alembic-only identity, same immutable image, one replica/no retry, exact terminal-result monitoring. |
| No Front Door initially | No relevant dependency. | No relevant dependency. | Keep SWA and ACA hostnames separate; exact CORS/cookie/CSRF/callback/MCP tests. |
| France contingency | No environment abstraction or second state. | Region parameterized, but only France non-production is exercised. | Documentation only; no standby resources, replication, or hidden cost. |

## Owner-ready choice

### Option A - Bicep with the LARP control-plane pattern - recommended

Use Bicep for subscription/bootstrap and environment application layers. Adapt the LARP module and
workflow patterns, not its product configuration.

**Benefits**

- Closest existing code precedent to Spotify's Container Apps and migration-Job target.
- Azure-native resource APIs and deployment history; no separate sensitive Terraform state store,
  state lock, state recovery, or provider plugin state schema.
- Existing read-only pull-request what-if and separate apply identity pattern is stronger than
  Agrisense's current local Terraform process.
- Lower fixed operational burden for an Azure-only app with 1-5 users.
- Incremental omission behavior makes accidental deletion from merely removing a declaration less
  likely, although it also creates cleanup debt.

**Costs and risks**

- LARP is non-production, and its exact Spotify gaps—SWA, Blob, warm collector, password-backed DB
  roles, Israel Central—still need implementation and proof.
- What-if can be noisy or incomplete; provider-noise baselines and focused post-deploy assertions
  are mandatory.
- Omitted resources survive incremental deployments, so deletion must be explicit, inventoried,
  and separately authorized.
- Entra/OIDC bootstrap remains imperative and must be reconciled/tested; Bicep is not a complete
  identity-directory tool.
- Azure-only coupling is deliberate. A later provider move would require new IaC.

**Downstream effects**

- Reuse LARP's bootstrap/application split, read-only preview identity, environment-constrained
  apply identity, migration Job gate, immutable revision proof, and manual drift/noise runbook.
- Add Spotify-owned modules for SWA, API, collector, transient Blob, password secrets/RBAC, and
  observability.
- Pin Azure CLI/Bicep, resource API versions, actions, container digests, and generated outputs.
- Use targeted guards where what-if cannot prove behavior: identity/RBAC end state, deletion
  inventory, private DNS, ACR pull, Key Vault secret access, PostgreSQL role denial, migration
  terminal state, and serving revision.

### Option B - Terraform with an upgraded Agrisense operating model

Use Terraform/AzureRM, drawing patterns from Agrisense but not copying its flat VM root or manual
operator workflow.

**Benefits**

- Stronger production precedent: the owner has already taken an Israel Central Terraform stack
  through planning, apply, cutover, incidents, follow-up fixes, and retirement of the old estate.
- Direct precedent for B1ms/P4, Blob, Key Vault, ACR, private DNS, monitoring, and state on Azure.
- Terraform plan has first-class state-aware create/update/delete and drift semantics; imports and
  lifecycle controls are available when deliberately designed.
- More portable if the infrastructure later needs non-Azure providers, though no such need is
  selected today.

**Costs and risks**

- Requires a separately secured and recoverable remote-state service before the app stack exists.
- Plans and state may contain database passwords and secret values; artifact and operator access
  become security boundaries.
- Agrisense does not supply the required CI plan/apply separation, drift automation, environment
  isolation, import/recovery procedure, or ACA/SWA modules.
- Provider upgrades and state schema are another lifecycle. Agrisense has exact provider locks but
  no exact Terraform CLI pin.
- A state or ownership mistake can propose deleting durable resources. Agrisense currently has no
  `prevent_destroy` lifecycle blocks to copy.

**Downstream effects**

- Create separate bootstrap, non-production, and production state boundaries with distinct
  identities and backend keys; do not use CLI workspaces for credential separation.
- Add exact Terraform CLI and provider upgrade policy, PR fmt/validate/policy/plan gates, sanitized
  plan review, manual environment-gated apply, scheduled drift detection, post-apply verification,
  and state/lock recovery rehearsals.
- Add lifecycle/deletion controls for PostgreSQL, Key Vault, Blob, ACR, and resource groups, while
  preserving the ADR's separately authorized destructive operations.
- Author ACA, collector, migration Job, SWA, and Spotify-specific RBAC modules from official
  provider schemas and test them; they are not present in Agrisense.

## Recommendation and decision rule

Recommend **Option A, Bicep**, subject to the controls above.

The recommendation did change in one important respect: Terraform is no longer a hypothetical
portable alternative or a tool with no team precedent. It is a viable, production-exercised option
and should be described that way in ADR 0002. The recommendation itself does not flip because the
selected Spotify topology and its YAGNI constraint weight **control-plane simplicity and target
similarity** more heavily than production tenure of a different VM topology.

Choose Terraform instead only if the owner explicitly prioritizes one production-exercised IaC
tool across repositories and accepts the remote-state/bootstrap/recovery program as worthwhile
standardization work. User count is not a reason to weaken either tool's security gates; it is a
reason not to carry an unnecessary second control-plane service.

Do not choose a mixed deployment where Bicep owns some Spotify resources and Terraform imports or
references others in the same lifecycle. Mixing creates two drift models, two preview semantics,
two deletion semantics, output/bootstrap ordering, and ambiguous ownership. A future tool switch
must be a separately planned state/import migration with one declared owner per resource before
the old tool releases it.

## Mandatory gates before either first apply

1. Pin the IaC CLI, Azure CLI, action SHAs, resource/provider versions, and environment parameter
   inputs.
2. Separate owner bootstrap, pull-request preview/plan, infrastructure apply, image push,
   application deployment, runtime, and migration identities.
3. Run preview/plan with a read-only identity; keep apply manual and environment-constrained.
4. Prove that preview/plan output cannot leak secrets or personal data.
5. Maintain production and non-production as separate authority and recovery boundaries.
6. Add focused tests/guards for every limitation of the selected preview engine.
7. Verify provider registration, quota, Israel Central capacity, private DNS, managed-identity
   access, database role separation, and the exact serving revision after apply.
8. Establish drift review after the first deployment and on a schedule; classify noise only from
   measured evidence and expire the baseline when APIs/tool versions change.
9. Rehearse application rollback, database restore/connection switch, and the IaC tool's own
   recovery path before cutover.
10. Keep resource deletion, DNS/callback changes, first production write, and DigitalOcean
    retirement behind their existing separate owner gates.

Terraform additionally requires the remote-state, lock, interrupted-apply, force-unlock, import,
and state-reconstruction gates described above. Bicep additionally requires omission/deletion
inventory, imperative Entra reconciliation, what-if short-circuit/noise handling, and prior-template
reapplication guards.

## Primary external sources

Sources were read on 2026-08-27 UTC. They are version-sensitive and must be refreshed before
implementation:

- [HashiCorp AzureRM backend](https://developer.hashicorp.com/terraform/language/backend/azurerm)
- [HashiCorp dependency lock](https://developer.hashicorp.com/terraform/language/files/dependency-lock)
- [HashiCorp sensitive data](https://developer.hashicorp.com/terraform/language/manage-sensitive-data)
- [HashiCorp state storage and locking](https://developer.hashicorp.com/terraform/language/state/backends)
- [HashiCorp Terraform plan](https://developer.hashicorp.com/terraform/cli/commands/plan)
- [HashiCorp Terraform workspaces](https://developer.hashicorp.com/terraform/language/state/workspaces)
- [Microsoft comparison of Terraform and Bicep](https://learn.microsoft.com/en-us/azure/developer/terraform/comparing-terraform-and-bicep)
- [Microsoft Bicep what-if](https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/deploy-what-if)
- [Microsoft ARM deployment modes](https://learn.microsoft.com/en-us/azure/azure-resource-manager/templates/deployment-modes)
- [GitHub OIDC with Azure](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-azure)
- [Official AzureRM Container App resource](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/container_app)
- [Official AzureRM Container Apps Job resource](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/container_app_job)
- [Official AzureRM PostgreSQL Flexible Server resource](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/postgresql_flexible_server)

## Audit commands and limitations

Read-only commands used included:

```text
git -c safe.directory=D:/projects/agrisense -C D:/projects/agrisense rev-parse --show-toplevel
git -c safe.directory=D:/projects/agrisense -C D:/projects/agrisense remote
git -c safe.directory=D:/projects/agrisense -C D:/projects/agrisense branch --show-current
git -c safe.directory=D:/projects/agrisense -C D:/projects/agrisense rev-parse HEAD
git -c safe.directory=D:/projects/agrisense -C D:/projects/agrisense rev-list --left-right --count HEAD...@{upstream}
git -c safe.directory=D:/projects/agrisense -C D:/projects/agrisense status --short --branch --untracked-files=all
git -c safe.directory=D:/projects/agrisense -C D:/projects/agrisense ls-files
rg --files D:/projects/agrisense
rg -n over the tracked source, workflows, instructions, runbooks, and accepted-state files
terraform version
tofu version
```

The same command-scoped Git probes were repeated with the exact LARP and SPM worktree paths shown
in the repository-pin table.

The command-scoped `safe.directory` setting avoided changing global Git configuration. Git emitted
a warning that the sandbox account could not read the user's global ignore file; it still returned
the repository and untracked status shown above. No branch switch, fetch, checkout, config write,
state operation, tool initialization, provider download, or external mutation occurred.

Uncertainty retained:

- accepted repository records, not a fresh Azure query, establish Agrisense and LARP deployment
  state;
- no remote-state property or current lock was inspected;
- no GitHub secret, environment policy, workflow run, branch rule, or cloud RBAC assignment was
  queried live;
- current provider support pages prove resource availability, not that Spotify's exact API,
  authentication, network, or deletion semantics work without acceptance tests;
- the root orchestrator owns the full LARP/Bicep audit and the final owner choice.

**STOP 1:** local-ready evidence note for root verification. It is not an accepted IaC decision,
an implementation plan, a plan/preview result, or apply authority.
