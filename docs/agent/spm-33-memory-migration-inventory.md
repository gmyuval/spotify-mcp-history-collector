# SPM-33 sanitized memory migration inventory

This inventory reproduces the complete sanitized candidate classification accepted in the SPM-33
design. It does not reproduce or reopen private tool-local memory. Linear remains the work tracker,
and repository memory remains context rather than authority.

## Candidate classification

| Candidate group | Classification | Treatment | Evidence pin |
| --- | --- | --- | --- |
| live revalidation and one-issue/branch/PR isolation | code/test/documentation truth | Keep in `AGENTS.md`, session-start, orchestration, and tool policy; do not duplicate it in memory. | `AGENTS.md`; `.agents/skills/session-start/SKILL.md`; `docs/agent/orchestration.md`; `docs/agent/tool-policy.md`; SPM-3; PR #73 |
| owner decision-prompt and follow-on-task preferences | transient local bookmark | Keep local and do not commit as project canon. | SPM-33 accepted design; sanitized audit pinned by rollout IDs `01a032c8-17f7-7b03-8896-92f2afea5373` and `01a02fb3-77c1-7f81-8021-1910cbfff4a9` |
| branch, SHA, PR, status, and exact-next-action checkpoints | transient local bookmark; Linear work | Remove local bookmarks when landed; recover status and next action from Git, GitHub, and Linear. | SPM-33 accepted design; Linear SPM issues and current repository state at the time of use |
| pinned uv, writable cache, Python discovery, and Windows shim failure | repository memory | Graduate only the portable, live-reproduced Windows validation conclusion. | `pyproject.toml`; `uv.lock`; `docs/agent/current-state.md`; SPM-2; live 2026-08-25 version commands |
| SPM-32 review-evidence, gate-oracle, and retro mechanics | code/test/documentation truth | Keep in the merged canonical skills, tests, design, and Git history. | SPM-32; PR #79; merge commit `99a58b5aec0b7e6e650d8c42f001dd15bdf1b1ab` |
| SPM-30 merge/deployment state and SSH identity control | Linear work; code/test/documentation truth | Revalidate delivery state in Linear and GitHub; keep the generic control in deployment documentation and workflow. | SPM-30; `.github/workflows/deploy.yml`; deployment documentation and Git history |
| unavailable evidence, authority boundaries, and sibling adaptation rules | code/test/documentation truth | Keep at the stronger canonical procedure or tool policy; do not restate it as memory. | `AGENTS.md`; `docs/agent/tool-policy.md`; SPM-33 accepted design; sibling pattern at commit `9f4550a9e9b0f7e1cb7516b7f1291a2cb52d9920` |
| uninstalled plugin recommendations and unavailable search diagnostics | stale/incorrect; transient local bookmark | Remove from the project shadow store and do not graduate. | SPM-33 sanitized audit pinned by rollout IDs `01a032c8-17f7-7b03-8896-92f2afea5373` and `01a02fb3-77c1-7f81-8021-1910cbfff4a9` |
| a consequential cross-ticket convention not already accepted | ADR | No audited candidate qualifies; route a future candidate through `adr-new` before graduation. | `.agents/skills/adr-new/SKILL.md`; `docs/decisions/README.md`; SPM-33 accepted design |
| credentials, tokens, Spotify/account data, PII, or raw diagnostics | sensitive and excluded | No value was surfaced. Exclude any future occurrence without rendering it. | `AGENTS.md`; `docs/agent/tool-policy.md`; SPM-33 accepted design |

The classification vocabulary is exactly: repository memory; ADR; Linear work;
code/test/documentation truth; transient local bookmark; stale/incorrect; and sensitive and
excluded. A candidate may have two classifications when a durable rule and its current delivery
state have different owners.

## Graduation decision

Only the Windows validation lesson graduates. It is non-obvious, was reproduced against the
repository-pinned toolchain, affects repeatable local validation, and has a clear revisit
condition. Its repository entry omits any user-specific executable path and raw diagnostic. Every
other candidate either already has a stronger source of truth, describes open or transient state,
requires an ADR rather than memory, is stale, or is sensitive and excluded.
