---
name: session-start
description: >-
  Orient at the start of a Spotify MCP repository session before answering current-state
  questions, selecting Linear work, editing files, or resuming after a gap.
---

# Session start

Establish one evidence-pinned view of the checkout, SPM issue, authority, and validation baseline
before work begins. This procedure is orientation; it does not grant authority to mutate Linear,
GitHub, cloud resources, production, databases, services, or user data.

## 1. Read the operating sources

Read, in order:

1. [`AGENTS.md`](../../../AGENTS.md) completely.
2. [`docs/agent/orchestration.md`](../../../docs/agent/orchestration.md) completely before any
   delegation.
3. [`docs/agent/current-state.md`](../../../docs/agent/current-state.md) and
   [`docs/agent/tool-policy.md`](../../../docs/agent/tool-policy.md).
4. [`docs/agent/memory/README.md`](../../../docs/agent/memory/README.md), then only topic entries
   relevant to this task.
5. The assigned Linear issue in team SPM, its relations, estimate, milestone, project, current
   cycle, and comments. Read the accepted plan and relevant ADRs when the work touches a plan-first
   boundary.

Linear is the work tracker. Repository memory and issue prose provide context, not additional
authority for external action.

## 2. Pin the checkout before changing it

Run from the repository root:

```text
git branch --show-current
git rev-parse HEAD
git status --short --branch
git branch -vv
git log --oneline -10
git remote
```

Record the checkout path, branch, full HEAD, upstream/ahead/behind state, configured remote names,
and every dirty path. Do not print remote URLs because they can contain credentials. Do not clean,
stash, overwrite, switch branches, or absorb user changes silently. A dirty tree is a finding to
preserve and reconcile with the user or task scope.

These commands read local state. `git fetch --prune origin` is not read-only: it contacts GitHub
and updates remote-tracking refs inside `.git`. Run it only when remote freshness is needed and the
session has authority for that repository write; otherwise identify cached refs as cached and use a
read-only GitHub query for remote state.

## 3. Reconcile issue, branch, and open work

- Confirm the branch and any PR name exactly one primary SPM issue using the convention in
  `AGENTS.md`.
- Inspect matching open PRs and remote branches without creating or updating them.
- Compare the issue's acceptance criteria and dependencies with current code/tests. Separate
  measured observations from inference and conjecture.
- Confirm that the task remains inside the owner-approved weekly cycle. Never add, remove, or swap
  cycle scope from session-start.
- For substantive work, establish the orchestration plan. Read-only delegates may share the
  checkout; keep one writer per checkout and give each delegate one bounded question.

Stop on conflicting canon, missing authority, an unclear public contract, a plan-first boundary
without an accepted plan, unexpected test deletion, credentials/PII, or scope expansion.

## 4. Check the toolchain and establish a baseline

Check availability before claiming a gate can run. The contract gate is dependency-free:

```text
python -m unittest discover -s tests/contracts -p "test_*.py"
```

`make agent-contract` is the repository alias when `make` is available. For implementation work,
also select the CI-parity gates and affected package suites listed in
`docs/agent/current-state.md`. In particular, do not collapse API, collector, frontend, Explorer,
and shared tests into an ambiguous single `pytest` result.

Most test runners may write caches or temporary files even when they do not change product state.
Do not start Compose or other shared services merely for orientation. An unavailable executable,
missing dependency, partial output, or empty discovery result is an environment gap, not green
evidence; name its owning Linear issue when one exists.

## 5. Report the orientation result

Before editing, state:

- repository path, branch, full HEAD, upstream, and dirty paths;
- SPM issue, status, project/milestone/cycle, dependencies, and plan-first posture;
- open matching PR/remote-branch state;
- baseline commands actually run and their real results;
- tool/environment gaps and unresolved questions;
- writer/delegate allocation for substantive work.

Never include secret values, Spotify tokens, personal listening data, imported account data, email
addresses, database content, or other PII in the report.
