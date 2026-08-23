# Current repository state

Last verified: 2026-08-23 (UTC), after integrating `origin/main` at
`12d6198095eeeaa8a37ca8903e4694a1bb08d886` into `codex/spm-3-orchestration-contract`. The
resulting reviewed integration merge is `25d8e4780bbadd1db9e5e80c8700ef69adb08676`.

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

## Production packaging boundary

SPM-2 preserved the production packaging path. Production Dockerfiles still install committed
pip-tools `requirements*.txt` files through their existing Compose build contexts, and the manual
deploy workflow retains its pip-based pre-deployment gates. `docker-requirements.lock` records
package metadata and requirement-file digests so this temporary boundary fails closed on drift.

Normal runtime requirement regeneration self-constrains the committed production pins and carries
forward explicit environment markers. Development requirement generation is constrained by each
service's runtime output. SPM-4 owns the accepted-plan decision between direct `uv.lock`
consumption and pip-compatible exports; do not change Docker or deployment consumption before that
decision.

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
