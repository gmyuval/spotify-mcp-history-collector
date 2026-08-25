# SPM-33 repository-first memory design

Status: accepted implementation interpretation of Linear SPM-33, read live on 2026-08-25.
This document does not grant authority beyond the issue, `AGENTS.md`, or the active harness.

## Goal

Spotify MCP will keep durable, shareable agent knowledge in the repository under
`docs/agent/memory/`. Tool-local memory will contain only a pointer to that repository index and
genuinely transient or personal bookmarks. Linear remains the sole work tracker, and memory remains
context rather than authority.

## Evidence base

- Linear SPM-33 defines the two layers, admissibility rules, correction semantics, required
  instruction surfaces, tool-local cleanup, and dependency-free validation.
- SPM-3 is Done and PR #73 established the vendor-neutral contract that this issue extends.
- SPM-32 is Done at verified STOP 2; PR #79 merged as
  `99a58b5aec0b7e6e650d8c42f001dd15bdf1b1ab` and is the base of this worktree.
- The sibling pattern was verified at larp-matchmaker commit
  `9f4550a9e9b0f7e1cb7516b7f1291a2cb52d9920`: a conclusion-oriented repository index, one
  durable conclusion per file, same-PR correction, and private memory reserved for scratch state.
- The existing Spotify MCP tool-local registry was audited on 2026-08-25 as migration input. The
  sanitized snapshot below is the complete worker-facing input; implementers must not reopen the
  private source. Historical rollout IDs `01a032c8-17f7-7b03-8896-92f2afea5373` and
  `01a02fb3-77c1-7f81-8021-1910cbfff4a9` pin the SPM-32 planning and sibling-audit summaries.

## Sanitized migration snapshot

The audited Spotify project candidates are grouped without private source text or machine paths:

| Candidate group | Classification | Repository treatment |
| --- | --- | --- |
| live revalidation and one-issue/branch/PR isolation | code/test/documentation truth | keep in `AGENTS.md`, session-start, orchestration, and tool policy; do not duplicate |
| owner decision-prompt and follow-on-task preferences | transient local bookmark | keep local; do not commit as project canon |
| branch, SHA, PR, status, and exact-next-action checkpoints | transient local bookmark; status and next action are Linear work | remove when landed; re-read Git/GitHub/Linear instead of graduating |
| pinned uv, writable cache, Python discovery, and Windows shim failure | repository memory | graduate only the portable, live-reproduced Windows validation conclusion |
| SPM-32 review-evidence, gate-oracle, and retro mechanics | code/test/documentation truth | keep in the merged canonical skills, tests, design, and Git history |
| SPM-30 merge/deployment state and SSH identity control | Linear work for delivery state; code/test/documentation truth for the control | revalidate live state; keep the generic control in deployment docs/workflow rather than memory |
| unavailable evidence, authority boundaries, and sibling adaptation rules | code/test/documentation truth | keep at the stronger canonical procedure or tool policy; do not create restated memory entries |
| uninstalled plugin recommendations and unavailable search diagnostics | stale/incorrect; the diagnostic itself is a transient local bookmark | remove from the project shadow store; do not graduate |
| a consequential cross-ticket convention not already accepted | ADR | no audited candidate qualifies; route a future candidate through `adr-new` before graduation |
| credentials, tokens, Spotify/account data, PII, or raw diagnostics | sensitive and excluded | no value was surfaced; exclude any future occurrence without rendering it |

The classification vocabulary is exactly: repository memory; ADR; Linear work;
code/test/documentation truth; transient local bookmark; stale/incorrect; and sensitive and
excluded. A row may use two of these exact categories when the durable rule and its current delivery
state have different owners. No credential value, Spotify/account data, personal listening history,
imported account data, email address, database content, or raw diagnostic is approved for repository
memory. If such a candidate is encountered later, classify it as sensitive and excluded without
rendering it.

## Two-layer model

### Repository layer

`docs/agent/memory/README.md` is the only index. Each indexed entry has one conclusion, a kebab-case
filename, an absolute evidence date, primary evidence, an affected surface, measured facts,
explicit inference, and a revisit condition. Entries are reviewed and corrected through the same
issue-linked pull-request flow as the change that earned them.

Repository memory does not contain open work, priority, cycle scope, acceptance criteria, session
handoffs, authority, credentials, tokens, production identifiers, personal Spotify/account data,
email addresses, database content, or raw diagnostics. It does not duplicate facts already owned by
code, tests, ADRs, Git history, canonical procedures, product documentation, or Linear.

### Tool-local layer

Supported tool-local memory contains a pointer to `docs/agent/memory/README.md` plus transient or
personal bookmarks only. A bookmark is removed when its delivery state is recoverable from Git,
GitHub, Linear, or the repository. Durable knowledge is never kept only in a private note.

The repository cannot safely rewrite every tool's private store. For this Codex environment, only
after the issue-linked pull request is merged, GitHub and Linear are read back, and the repository
index is present on verified `main`, the root will re-check direct user/platform authorization and
use the platform-authorized memory-update-note mechanism. The note will request replacement of the
broad Spotify project shadow store with the repository pointer and only still-current transient
preferences. It will not copy private source text into Git.

## Migration decision

The detailed classification belongs in `docs/agent/spm-33-memory-migration-inventory.md`. Most
existing candidates remain at their actual source of truth or stay tool-local. One non-obvious,
currently reproduced Windows validation lesson is approved for repository memory: on this host,
plain `python` resolves to an unusable WindowsApps shim, while the repository-pinned uv 0.12.3
provides Python 3.14.7 and a reproducible contract environment. The entry is portable and must not
record a user-specific executable path.

## Enforcement

A dependency-free `scripts/validate_agent_memory.py` validator will fail closed when:

- an index link escapes `docs/agent/memory/`, is broken, duplicated, or points to the README;
- a topic file is unindexed or has a non-kebab-case filename;
- an indexed topic lacks the required evidence fields or section structure;
- the canonical contract, thin Claude adapter, or required instruction surfaces lose their
  repository-memory pointers or two-layer boundary. The required surfaces are `AGENTS.md`,
  `CLAUDE.md`, `docs/agent/tool-policy.md`, `.agents/skills/session-start/SKILL.md`,
  `.agents/skills/pr-lifecycle/SKILL.md`, `.agents/skills/end-session/SKILL.md`, and
  `docs/agent/review-checklist.md`.

The validator emits sanitized path/category diagnostics only. Contract tests use a known-good
control, a motivating index mutation, and restored GREEN evidence. `make agent-contract` remains the
canonical aggregate gate and invokes the memory validator.

## Correction semantics

When an entry becomes false, stale, duplicated by a stronger source, or unsafe, update or delete it
in the normal issue-linked pull request and update the index in the same change. Do not layer a
contradictory private note over the repository entry. Removal of an entry is a correction, not loss
of authority, because memory never owns authority.

## Safety and scope

This is repository-governance work. It does not authorize deployment, production access, cloud
changes, credentials, Spotify data, database access, public MCP/API changes, cycle replanning, or a
second work tracker. Any discovery that would change privacy, authority, retention, authentication,
or a public contract is a decision stop.
