# Current repository state

Last verified: 2026-08-21 (UTC), from repository revision
`d0c8107eb8126e705c5b5852e39563d05e35f6a1` plus the local SPM-3 working tree.

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

The CI workflow runs these independent gates:

```text
python -m unittest discover -s tests/contracts -p "test_*.py"
ruff check .
ruff format --check .
mypy services/shared/src services/api/src services/collector/src services/frontend/src services/explorer/src
pytest services/api/tests/
(from services/collector) pytest tests/
pytest services/frontend/tests/
pytest services/explorer/tests/
```

Run `pytest services/shared/tests/` when shared code changes; it is not currently a separate CI
job. Do not treat `make test` as proof that every package-specific suite ran: the root pytest
configuration does not include Explorer or shared tests, and collector has a separate invocation
because the suites' fixtures conflict.

On the host used for the SPM-3 implementation session, `make`, Ruff, pytest, pre-commit, and mypy
were not available on `PATH`; the mypy environment gap is tracked by SPM-2. An unavailable tool is
an explicit gap, never a passing result. The dependency-free agent contract can be run with any
suitable Python 3 interpreter when the `python` launcher itself is unavailable.

## Deployment evidence and cautions

`.github/workflows/deploy.yml`, `docker-compose.prod.yml`, `deploy/`, and the deployment guides
describe a DigitalOcean production path. That workflow can change the database firewall, replace
the server checkout, rebuild and restart services, run Alembic migrations, recreate Caddy, and
prune images. Reading those files is orientation; executing or changing that path requires an
accepted plan and explicit authority.

No production health, deployment freshness, live database state, user account state, or secret
configuration is asserted by this document.

## Known documentation drift

Some pre-modernization files mix historical plans, implementation snapshots, and operational
commands. In particular, treat `docs/current-phase-plan.md`, `docs/prd-dev-step2.md`, and older
deployment/integration instructions as evidence to verify, not as current agent policy. Durable
work remains in Linear; accepted decisions belong under `docs/decisions/`; non-obvious lessons
belong under `docs/agent/memory/`.
