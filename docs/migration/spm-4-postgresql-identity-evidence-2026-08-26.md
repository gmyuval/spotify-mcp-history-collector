# SPM-4 PostgreSQL identity evidence - 2026-08-26

## Scope and evidence labels

This note compares initial database authentication choices for ADR 0002. It does not authorize an
Azure apply, Microsoft Entra or PostgreSQL role mutation, secret creation or rotation, credential
access, migration, deployment, or production access.

- **Measured** - observed in this repository at the current SPM-4 worktree head.
- **Official** - stated by current Microsoft documentation retrieved on 2026-08-26 UTC.
- **Inferred** - a design conclusion that still needs the named implementation and release proof.

## Current repository contract

- **Measured:** API, collector, health check, and Alembic accept a complete `DATABASE_URL`.
- **Measured:** the shared `DatabaseManager` creates a SQLAlchemy async engine with `asyncpg` and
  defaults to `NullPool`. It has no database-credential callback or token-refresh abstraction.
- **Measured:** Alembic reads the same environment variable and constructs a separate async engine
  with `NullPool`.
- **Measured:** `azure-identity` is not in the root dependency lock. The approved transient Blob
  design will need managed identity in the storage adapter, but it does not by itself implement
  PostgreSQL token acquisition.
- **Measured:** ADR 0002 already requires migration/DDL authority to be separate from runtime DML.
  It does not currently require distinct database roles for API and collector.

The password path therefore preserves the current connection seam. Microsoft Entra authentication
is feasible, and the current absence of a connection pool reduces one token-expiry failure mode,
but it still requires a token-producing connection adapter for every new connection and an Alembic
equivalent. Any later pool introduction must remain token-aware.

## Official Azure constraints

| Fact | Consequence |
|---|---|
| Flexible Server supports PostgreSQL password authentication, Microsoft Entra authentication, or both. Entra tokens are supplied as the PostgreSQL password. | Either initial choice is supported, and a staged later transition can use the dual mode. [Microsoft Entra authentication](https://learn.microsoft.com/en-us/azure/postgresql/security/security-entra-concepts) |
| Managed identities remove stored credentials, but the application must acquire and refresh tokens. Microsoft warns that sample connection-string substitution is not production-ready without a refresh policy. | Entra is not a connection-string-only IaC switch for the current SQLAlchemy/asyncpg code. [Python PostgreSQL quickstart](https://learn.microsoft.com/en-us/azure/postgresql/connectivity/connect-python) |
| Azure's Container Apps Python tutorial uses a user-assigned managed identity and dynamically replaces the database password with an Entra token at runtime. | There is an official target pattern, but the repository needs a locally owned, tested async implementation rather than copying a synchronous sample. [Container Apps Python tutorial](https://learn.microsoft.com/en-us/azure/developer/python/tutorial-deploy-python-web-app-azure-container-apps-01) |
| Only a PostgreSQL Microsoft Entra administrator can initially create Entra database principals. Role creation, grants, deletion, object ownership, and Entra identity lifecycle need explicit administration. | Entra adds an admin/bootstrap and identity-reconciliation boundary to IaC and recovery. [Microsoft Entra configuration](https://learn.microsoft.com/en-us/azure/postgresql/security/security-entra-configure) |
| Container Apps can reference Key Vault secrets through a managed identity. A versionless URI is refreshed within 30 minutes and active revisions using it as an environment variable restart. | Passwords can remain outside source, GitHub, and plain IaC. Rotation is supported but not transactional with `ALTER ROLE`; a reviewed stop/start or dual-role procedure is still required. [Container Apps secrets](https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets) |
| PostgreSQL roles should carry only the minimum application permissions. | Runtime DML and migration DDL must remain separate regardless of authentication mechanism. [Flexible Server access management](https://learn.microsoft.com/en-us/azure/postgresql/security/security-access-control) |

## Options

### A - PostgreSQL passwords referenced from Key Vault

Start Flexible Server with PostgreSQL password authentication and local PostgreSQL login roles for
the application. Do not configure an unused Entra administrator or Entra database principals
initially. Create separate non-owner DML login roles for the public API and private collector, plus
a distinct migration login that can perform only the accepted Alembic DDL. Store separate
connection secrets in Key Vault. Each workload identity may read only its own database secret.

**Benefits**

- Preserves the existing `DATABASE_URL`, asyncpg, health-check, and Alembic paths.
- Smallest code and dependency change for the initial Azure migration.
- Key Vault keeps credentials out of source control, GitHub secrets, image layers, and plain IaC.
- A 1-5-user deployment can accept a short, planned rotation restart instead of building
  zero-downtime dual-login machinery now.
- Flexible Server can enable dual authentication later through a separately accepted migration;
  the initial target does not operate an unused identity system.

**Costs and risks**

- Long-lived database credentials exist and must be generated, scoped, audited, rotated, and
  revoked.
- A compromised workload can use its retrieved password until it is rotated; managed identity
  tokens have a shorter validity boundary.
- Updating the PostgreSQL password and Key Vault value is not atomic. The initial runbook needs a
  bounded maintenance window, explicit ordering, health verification, and rollback.
- Three login roles and secrets require a small grant/rotation matrix. This is retained because the
  public API and private collector have different exposure and need independent revocation; it is
  a security boundary rather than a growth feature.

**Minimum initial controls**

- No administrator or object-owner credential in a runtime workload.
- Revoke default public privileges; grant only required schema/table/sequence/function rights.
- Separate API DML, collector DML, and migration DDL logins and Key Vault secrets.
- Use private PostgreSQL networking, TLS verification, Key Vault audit logs, and secret access
  limited to the named workload identity.
- Rehearse rotation before cutover. For the initial cohort, a short write-fenced restart is
  acceptable; measure it and set a maximum duration. Do not pretend versionless secret refresh is
  an atomic database rotation.

### B - Microsoft Entra managed identity for runtime and migrations

Create distinct user-assigned managed identities as PostgreSQL principals. API/collector obtain a
fresh PostgreSQL token through a shared async connection factory; the migration process obtains its
own token and uses a separate DDL principal. Disable password authentication after recovery and
bootstrap procedures prove Entra-only operation.

**Benefits**

- No long-lived application database passwords.
- Azure identity lifecycle, audit, and revocation are the primary authentication controls.
- Supports clean per-workload identity and attribution.
- Aligns with Microsoft's passwordless guidance and the managed identities already planned for
  Azure resource access.

**Costs and risks**

- Requires a production-grade token-refreshing SQLAlchemy/asyncpg adapter, an Alembic adapter,
  `azure-identity`, configuration changes, local-development behavior, and failure-injection tests.
- Adds Entra PostgreSQL administrator bootstrap, principal creation, object ownership/grants,
  identity deletion/recreation handling, DNS access to Entra endpoints, and a recovery path.
- Token acquisition or renewal failure becomes a database-availability failure mode.
- A later connection pool must never cache an expired token as the password for new connections.
- This work does not improve product behavior or capacity for the initial 1-5-user cohort.

### C - Hybrid authentication

Use a Key Vault password for runtime and Entra managed identity for migrations, or the inverse.

**Benefits**

- Can remove the most privileged long-lived DDL secret while leaving runtime unchanged.
- Permits staged proof of Entra role/bootstrap behavior on the short-lived migration path.

**Costs and risks**

- Operates and tests two database authentication mechanisms from day one.
- Still retains one class of password while adding Entra administration and dependencies.
- Creates more failure modes than A and less credential elimination than B.
- No current compliance or threat requirement identifies this compromise as necessary.

## Recommendation

Select **A for the initial 1-5-user Azure deployment**, with the controls above and PostgreSQL
password authentication only. This is an explicit YAGNI choice, not a claim that passwords are
architecturally superior. It changes configuration and secret delivery while preserving the
measured database client code, keeps DML and DDL authority separate, and accepts a short rehearsed
maintenance restart for rotation instead of implementing an unneeded zero-downtime credential
system.

Do not schedule Entra migration merely by date. Reopen the decision when any objective trigger is
met:

- policy or compliance disallows database passwords;
- a rotation rehearsal exceeds the accepted outage or operator-effort limit;
- API and collector need distinct database permissions, attribution, or independent revocation;
- pooling or connection-lifecycle work creates and proves a token-capable connection factory;
- more workloads/operators make secret distribution materially harder; or
- incident/threat evidence shows the long-lived credential boundary is unacceptable.

At that point, choose B coherently rather than leaving C as an indefinite hybrid.

## Mandatory plan and release gates for A

1. Define exact runtime and migration grants from the observed query and migration inventory;
   revoke public/default privileges and prove runtime DDL denial.
2. Keep the server administrator credential out of runtime and migration workloads. Define its
   separately authorized break-glass ownership, storage, audit, and recovery procedure.
3. Use distinct Key Vault secrets and read identities for API DML, collector DML, and migration
   DDL. No secret appears in logs, plans, issues, images, command lines, or test artifacts.
4. Rehearse password rotation with API and collector write-fenced, bounded downtime, new-secret
   pickup, database/health/MCP/collector verification, and rollback. Set the maximum acceptable
   duration before implementation acceptance.
5. Prove TLS hostname/certificate verification and private DNS/networking from every workload.
6. Run SPM-6 mixed workload and connection-headroom evidence against B1ms, including failed-secret,
   revoked-role, restart, and exhausted-connection behavior.
7. Run Alembic using only the migration role; prove the runtime role cannot apply schema changes and
   the migration role is unavailable to normal runtime containers.
8. Record the objective Entra revisit triggers in monitoring/runbooks. A trigger opens a dedicated
   accepted identity plan; it does not silently change production authentication.

## Owner decision evidence

On 2026-08-26 UTC, after reviewing the password, Entra managed-identity, and hybrid alternatives,
the owner asked whether Key Vault meant an existing service or a resource that must be deployed.
The clarification established that Azure Key Vault is a managed service but the target uses a new
app-specific vault resource, that the vault is already required for other application secrets, and
that no resource is authorized or created by this decision. Yuval Moran then approved Option A
with **"In that case, option a is good and accepted"**. This selects PostgreSQL password
authentication only initially, separate API/collector/migration login roles and secrets, the named
rotation controls, and trigger-based Entra reconsideration.
