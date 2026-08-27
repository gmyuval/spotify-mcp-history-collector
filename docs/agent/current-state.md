# Current repository state

Last verified: 2026-08-27 (UTC), in `codex/spm-5-spotify-api-audit` after merging `origin/main`
`a88e52c3ab0d62c9540f4d89def9b54330ce57ee`. This verification describes the local SPM-5
candidate before repository delivery; revalidate the live branch, pull request, and remote state
before relying on it.

This is volatile orientation, not a work queue, architecture decision, or deployment record. Linear
team **SPM**, project **Spotify MCP modernization**, is authoritative for planned work, ownership,
status, estimates, dependencies, milestones, and weekly-cycle scope. Re-check every fact here
against the named source before using it for a consequential decision.

## Modernization posture

- The repository is a working Python 3.14 monorepo being modernized from a DigitalOcean-hosted
  system. Existing deployment documents and workflows are evidence about that estate, not an
  automatically binding future architecture.
- `AGENTS.md` and `docs/agent/orchestration.md` define the vendor-neutral operating contract.
- Canonical repository skills live in `.agents/skills/`; `.claude/skills/` contains exact discovery
  adapters only.
- Azure, deployment, infrastructure, cloud retirement, secrets/auth/OAuth, database schema or data
  movement, public MCP/API compatibility, Spotify account data, retention, and broad framework
  changes remain plan-first boundaries.

SPM-4's constituent owner choices now point to an Azure Static Web Apps Free frontend, an API
Container App scaled from zero to one replica, and a ten-minute scheduled collector Container Apps
Job. PostgreSQL Flexible Server uses private VNet integration; Blob Storage retains one private
endpoint. Images use a neutral organization-shared ACR whose platform lifecycle is outside this
repository, while Spotify owns its repository namespaces, immutable digests, publishing, and pull
permissions. The current small-cohort forecast is about USD 40 per month within a USD 31-46
planning range and a USD 60 initial budget alert. These are binding target choices in
[Accepted ADR 0002](../decisions/0002-azure-target-architecture-and-migration-boundaries.md),
not authority to provision, deploy, migrate, or delete cloud resources.

## Spotify Web API audit and identity posture

SPM-5 inventories the Spotify endpoints, fields, scopes, retry behavior, quota modes, playlist
semantics, Audio Features providers, and identity dependencies used by this repository. Its safe
maintenance preserves public behavior while adding an internal non-retrying
`QUOTA_EXCEEDED` subtype, malformed-`Retry-After` fallback, concrete Spotify-to-Soundcharts
fallback coverage, and corrected operator/configuration guidance.

[Accepted ADR 0003](../decisions/0003-adopt-staged-account-id-migration.md) selects a bounded
additive migration from Spotify profile `id` linking to authoritative `account_id` linking. It
preserves internal `users.id`, requires a finite all-active-cohort reauthorization gate, fails
closed on conflicting identity evidence, and initially preserves `spotify_user_id` compatibility.
No schema, OAuth, production-account, token, credential, or user-data change has been made.

[Accepted ADR 0004](../decisions/0004-separate-provider-identities-and-minimize-profile-retention.md)
separates the stable Google provider identity from Spotify identity and internal `users.id`. It
prohibits email-only and single-user automatic linking, removes `user-read-email` only after every
active user has an explicit stable provider link, stops ingesting Spotify email/country/product,
and puts legacy-value deletion behind public-nullability, rollback, finite-cohort, and separately
authorized contraction gates. `user-read-private` remains only while an accepted Search contract
requires it. No implementation or data contraction has occurred.

[Accepted ADR 0005](../decisions/0005-support-spotify-development-mode-as-the-common-denominator.md)
selects current restricted Development Mode as the one-to-five-user common denominator. Extended
installations run the same path; postponed legacy access and Extended-only endpoints are not product
contracts. `QUOTA_EXCEEDED` remains non-retrying, while coordinated caching, coalescing, foreground
priority, resumable background deferral, and sanitized budget-pressure observability are
implementation gates. No dashboard/account access, mode change, or quota-policy implementation has
occurred.

[Accepted ADR 0006](../decisions/0006-bundle-both-playlist-modification-scopes-for-write-access.md)
retains `playlist-modify-public` and `playlist-modify-private` as one complete write-capability
bundle for every initial user. Partial grants fail locally before a Spotify request; the bundle is
not proof of playlist ownership or other resource authority. This formalizes current behavior and
does not authorize OAuth rollout or provider/account access.

[Accepted ADR 0007](../decisions/0007-keep-playlist-media-contract-track-only.md) keeps playlist
reads, mutations, cache, and memory track-only. Unexpected episodes and future item types must
preserve position as unsupported placeholders rather than crash, masquerade as tracks, or disappear.

[Accepted ADR 0008](../decisions/0008-stage-retirement-of-undocumented-playlist-embed-scraping.md)
classifies the private `__NEXT_DATA__` parser as transitional compatibility debt. Retirement
requires a kill switch, privacy-safe aggregate evidence, a usable user-supplied URI/list import,
and a later explicit owner gate. No embed, import, Azure, or production behavior has changed.

[Accepted ADR 0009](../decisions/0009-use-soundcharts-as-the-default-audio-features-provider.md)
selects Soundcharts as the sole default Audio Features provider and removes Spotify Audio Features
from the supported provider chain. SPM-18 owns the stale-adapter correction, quota controls,
provenance, and operational proof. The current runtime remains Spotify-first with an optional
Soundcharts fallback until that separately reviewed implementation lands; no provider account,
credentials, spend, real tracks, deployment, or production state were accessed or changed.

Public MCP/API compatibility remains decision-blocked.
Implementing the accepted identity, OAuth, profile-retention, app-mode/quota, playlist-media, and
embed-retirement decisions remains plan-first, as does operationalizing the Soundcharts policy.
Do not infer production entitlements or account state from mocked tests or public documentation.

## Observed service layout

The local Compose file declares PostgreSQL, Valkey, API, collector, admin frontend, and Explorer
services. Production configuration declares API, collector, frontend, Explorer, oauth2-proxy, and
Caddy while using externally supplied database and cache configuration. The Python packages are:

- `services/shared` - shared database, cache, crypto, Spotify, MusicBrainz, Soundcharts, and ZIP
  import primitives;
- `services/api` - FastAPI auth, admin, history, Explorer support, and MCP endpoints;
- `services/collector` - polling, initial sync, import, resolution, and enrichment worker;
- `services/frontend` - administrative FastAPI/Jinja application;
- `services/explorer` - listening-history Explorer FastAPI/Jinja application.

Detailed product and integration behaviour remains documented in the code, `README.md`, and topic
documents under `docs/`; do not recreate the MCP tool catalog or a future-work list here.

## Reproducible development and CI baseline

SPM-2 established the root uv workspace, pinned uv 0.12.3, Python 3.14.7, and committed `uv.lock`.
The clean-checkout setup command is:

```text
uv sync --locked --all-packages --all-extras --all-groups
```

Pull-request CI runs lock and workflow drift checks, the dependency-free contract suite, Ruff check
and format validation, strict mypy across all five source trees, pre-commit, and one isolated pytest
job for each workspace package. Keep package suites separate because their fixtures can conflict.
The same commands are exposed through the root `Makefile`; Make is an optional convenience, and the
exact Python contract fallback is documented in `AGENTS.md`.

On the published SPM-2 head, Windows verification passed 45 workflow contract tests, 24 shared
tests, 618 API tests with 7 integration tests deselected, 53 collector tests, 66 frontend tests,
and 102 Explorer tests. Ruff validated 272 files and strict mypy validated 157 source files. Both
development and production Compose configurations validated without starting services. The SPM-3
branch adds agent-contract coverage; use its exact-head validation and GitHub checks rather than
assuming the earlier counts are sufficient.

## Pull-request merge strategy

SPM-31 verified on 2026-08-23 that repository settings report `allow_merge_commit=true`,
`allow_squash_merge=true`, `allow_rebase_merge=true`, and `allow_auto_merge=true`. `main`
protection requires a branch current with strict
status checks named `Lint`, `Type Check`, `Test API`, `Test Collector`, `Test Frontend`, and `Test
Explorer`, plus one approval with stale reviews dismissed. It does not require code-owner or
last-push approval, signed commits, conversation resolution, administrator enforcement, or linear
history; force pushes and branch deletion are blocked. Both repository rulesets and effective
`main` branch rules were empty.

[ADR 0001](../decisions/0001-pull-request-merge-method-policy.md) makes an explicitly selected
`merge` operation the canonical default for qualifying pull requests. Squash and rebase remain
available only as justified exceptions; an agent-proposed exception requires an owner prompt and
explicit approval before use.
Re-check the live settings, protection, and
required linear history before every merge; do not mutate them while selecting a method.

## Production packaging boundary

SPM-2 preserved the current production packaging path. Production Dockerfiles still install
committed pip-tools `requirements*.txt` files through their existing Compose build contexts, and
the manual deploy workflow retains its pip-based pre-deployment gates. `docker-requirements.lock`
records package metadata and requirement-file digests so this temporary implemented boundary fails
closed on drift.

[SPM-4's Accepted ADR 0002](../decisions/0002-azure-target-architecture-and-migration-boundaries.md)
records the owner's constituent choice of direct package-scoped synchronization from the root
`uv.lock` for future production images. This choice does not change the current Dockerfiles by
itself. Implementation requires a strict root `.dockerignore` and
build-context tests, pinned uv 0.12.3 and base-image digests, locked production-only non-editable
synchronization, multi-stage runtime copying, provenance, and service-cache proof before the
pip-compatible artifacts can be retired.

## Manual production deployment posture

SPM-30 changed `.github/workflows/deploy.yml` to manual `workflow_dispatch`. A merge or push to
`main` does not dispatch production. A separately authorized dispatch must identify an immutable
full commit SHA reachable from `origin/main` and a fresh deployment UUID, then be monitored through
a terminal result with revision, environment, health, and rollback evidence.

The workflow can mutate the database firewall, production checkout, containers, services, and
schema. It requires an accepted plan and separate deployment authority. Before any authorized
production deployment, configure `DROPLET_SSH_HOST_FINGERPRINT` and complete the documented external
OAuth allowlist migration. This repository integration neither performs nor authorizes those
steps. No production health, deployment freshness, live database state, account state, or secret
configuration is asserted here.

## Known documentation drift

Some pre-modernization files mix historical plans, implementation snapshots, and operational
commands. In particular, treat `docs/current-phase-plan.md`, `docs/prd-dev-step2.md`, and older
integration instructions as evidence to verify, not as current agent policy. Durable work remains
in Linear; accepted decisions belong under `docs/decisions/`; non-obvious lessons belong under
`docs/agent/memory/`.
