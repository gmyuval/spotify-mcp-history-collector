# Current repository state

Last verified: 2026-08-22 (UTC), from `codex/spm-2-uv-baseline-main`.

This is a volatile implementation snapshot, not an architecture decision or deployment record.
Re-check its claims against the named files and commands before relying on them.

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

Detailed product and integration behaviour remains documented in the code, `README.md`, and the
topic documents under `docs/`.

## Reproducible development and CI baseline

Development and pull-request CI use the root uv workspace, pinned uv 0.12.3, Python 3.14.7, and
the committed `uv.lock`. The clean-checkout setup command is:

```text
uv sync --locked --all-packages --all-extras --all-groups
```

The CI workflow then runs lock and workflow drift checks, the dependency-free uv-workflow suite,
Ruff check and format validation, strict mypy across all five source trees, pre-commit, and one
isolated pytest job for each workspace package. Keep package suites separate because their
fixtures can conflict. The same commands are exposed through the root `Makefile`, but Make is an
optional convenience rather than a prerequisite.

On the Windows SPM-2 writer host, a fresh locked environment synchronized successfully with the
exact pinned tools. Fresh root verification passed 15 uv-workflow contract tests, 24 shared tests,
618 API unit tests (7 integration tests deselected), 53 collector tests, 66 frontend tests, and
102 Explorer tests. Ruff validated 271 files and strict mypy validated 157 source files. Both
development and production Compose configurations validated without starting services. Linux
GitHub Actions remains the independent published-head verification source.

The 870 package tests currently collected plus 15 workflow contract tests supersede the earlier
874-function static orientation count; the discrepancy is recorded rather than silently treated
as a failure in the uv migration.

## Production packaging boundary

SPM-2 does not change the production packaging path. Production Dockerfiles still install the
committed pip-tools `requirements*.txt` files through their existing Compose build contexts, and
the deploy workflow still uses its existing pip-based pre-deployment gates.
`docker-requirements.lock` records package metadata and requirement-file digests so this temporary
boundary fails closed on drift.

Normal runtime requirement regeneration self-constrains the committed production pins and carries
forward their explicit environment markers. Development requirement generation is constrained by
each service's runtime output, so a development-only dependency cannot silently select different
runtime pins. Regeneration also closed the inherited collector `aiosqlite` and Explorer
`python-multipart` direct-dependency gaps; the manifest currently records no known direct gaps.
SPM-4 owns the accepted-plan decision between direct `uv.lock` consumption and pip-compatible
exports; do not change Docker or deployment consumption before that decision.

The deployment workflow can mutate production infrastructure and services. SPM-2 neither runs nor
changes it. No production health, deployment freshness, live database state, user account state,
or secret configuration is asserted by this document.
