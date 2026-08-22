# Current repository state

Last verified: 2026-08-22 (UTC), from the SPM-2 working tree on
`codex/spm-2-uv-baseline`, based at `e1459adcd6ae34026af439435083de4ff0bbe4b3`.

This is volatile orientation, not a work queue or an architecture decision. Linear team **SPM**,
project **Spotify MCP modernization**, is authoritative for planned work, ownership, status,
estimates, dependencies, milestones, and weekly-cycle scope. Re-check every fact here against the
named source before using it for a consequential decision.

## Modernization posture

- The repository is a working Python 3.14 monorepo being modernized from a DigitalOcean-hosted
  system. Existing deployment documents and workflows are evidence about that estate, not an
  automatically binding future architecture.
- `AGENTS.md` and `docs/agent/orchestration.md` define the vendor-neutral operating contract.
- Canonical repository skills live in `.agents/skills/`; `.claude/skills/` contains exact
  discovery adapters only.
- Azure, deployment, infrastructure, cloud retirement, secrets/auth/OAuth, database schema or
  data movement, public MCP/API compatibility, Spotify account data, retention, and broad
  framework changes remain plan-first boundaries.

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

Product and integration detail belongs in the code, `README.md`, and the topic documents under
`docs/`; do not recreate the MCP tool catalog or a future-work list here.

## Validation surface

Development and pull-request CI use the root uv workspace, pinned uv 0.12.3, Python 3.14.7, and
the committed `uv.lock`. The canonical clean-checkout setup command is:

```text
uv sync --locked --all-packages --all-extras --all-groups
```

The CI workflow then runs lock and workflow drift checks, the dependency-free agent-contract
suite, Ruff check and format validation, strict mypy across all five source trees, pre-commit, and
one isolated pytest job for each workspace package. Keep package suites separate because their
fixtures can conflict. The same commands are exposed through the root `Makefile`, but Make is an
optional convenience rather than a prerequisite.

On the Windows SPM-2 writer host, the locked environment synchronized successfully and produced
these local results: 23 agent-contract tests, 24 shared tests, 618 API unit tests (7 integration
tests deselected), 53 collector tests, 66 frontend tests, and 102 Explorer tests passed. Ruff
validated 273 files and strict mypy validated 157 source files. A second locked sync also created
a fresh environment, and both development and production Compose configurations validated without
starting services. Linux GitHub Actions remains unverified until publication is separately
authorized and CI actually runs.

## Deployment evidence and cautions

`.github/workflows/deploy.yml`, `docker-compose.prod.yml`, `deploy/`, and the deployment guides
describe a DigitalOcean production path. That workflow can change the database firewall, replace
the server checkout, rebuild and restart services, run Alembic migrations, recreate Caddy, and
prune images. Reading those files is orientation; executing or changing that path requires an
accepted plan and explicit authority.

SPM-2 does not change that packaging path. Production Dockerfiles still install the committed
pip-tools `requirements*.txt` files through their existing Compose build contexts, and the deploy
workflow still uses its existing pip-based pre-deployment gates. `docker-requirements.lock` records
the package metadata and requirement-file digests so this temporary boundary fails closed on
drift. Its current evidence also records two inherited direct-dependency gaps: collector dev
requirements omit `aiosqlite`, and Explorer dev requirements omit `python-multipart`. SPM-4 owns
the accepted-plan decision between direct `uv.lock` consumption and pip-compatible exports; do
not change Docker or deployment consumption before that decision.

No production health, deployment freshness, live database state, user account state, or secret
configuration is asserted by this document.

## Known documentation drift

Some pre-modernization files mix historical plans, implementation snapshots, and operational
commands. In particular, treat `docs/current-phase-plan.md`, `docs/prd-dev-step2.md`, and older
deployment/integration instructions as evidence to verify, not as current agent policy. Durable
work remains in Linear; accepted decisions belong under `docs/decisions/`; non-obvious lessons
belong under `docs/agent/memory/`.
