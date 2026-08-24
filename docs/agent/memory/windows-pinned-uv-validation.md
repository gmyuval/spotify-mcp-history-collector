# Pinned uv provides reproducible Windows validation when plain Python discovery fails
- Date: 2026-08-25
- Evidence: `uv --version` reported `uv 0.12.3`; `uv run --locked python --version` reported `Python 3.14.7`; plain `python --version` resolved through the WindowsApps shim and did not provide a usable interpreter.
- Affected surface: local repository validation on this Windows host

## Measured
On 2026-08-25, plain Python discovery selected the unusable WindowsApps shim. The
repository-pinned uv 0.12.3 selected Python 3.14.7 and ran the locked contract environment with a
writable repository-local cache.

## Inference
Pinned uv is the reliable entrypoint for repository validation on this host.

## Revisit when
Re-check this conclusion when Windows Python discovery changes or the repository changes its
pinned uv, Python, environment, or cache conventions.
