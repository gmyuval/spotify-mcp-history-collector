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
4. Read [`docs/agent/memory/README.md`](../../../docs/agent/memory/README.md) first, then only topic
   entries relevant to this task.
5. The assigned Linear issues and ready candidates in the current cycle, including relations,
   estimates, milestones, project, status, and comments. Read accepted plans and relevant ADRs
   when work touches a plan-first boundary.

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

- Confirm every existing branch and PR names exactly one primary SPM issue using the convention in
  `AGENTS.md`; inspect matching open PRs and remote branches without creating or updating them.
  Before resuming an issue's existing delivery lane, verify and record its exact branch/PR head,
  primary issue linkage, owner, uniqueness, and absence of another writer. Resume it only when safe
  and authorized. Never create a second branch or PR for the same delivery slice implicitly.
- Derive a transient batch from the current approved cycle. A ticket is eligible when acceptance
  criteria and authority are clear, dependencies are satisfied, applicable plan-first decisions
  are accepted, and validation can run safely.
- Select two or more eligible tickets when available, with no fixed maximum. Order them by
  dependency, then approved priority. If only one is eligible, record why the multi-ticket default
  cannot be met.
- Choose sequential or parallel work deliberately. Sequential execution is the default. Read-only
  delegates may share the checkout; concurrent writers require isolated worktrees with disjoint
  surfaces. Give each delegate exactly one ticket or bounded question.
- Compare each selected ticket's acceptance criteria with current code/tests. Separate measured
  observations from inference and conjecture. Never add, remove, or swap cycle scope from
  session-start.

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
- selected SPM batch, eligibility, dependency order, sequential/parallel decision, and the status,
  project/milestone/cycle, authority, and plan-first posture of each ticket;
- open matching PR/remote-branch state;
- baseline commands actually run and their real results;
- tool/environment gaps and unresolved questions;
- writer/delegate allocation for substantive work.

Never include secret values, Spotify tokens, personal listening data, imported account data, email
addresses, database content, or other PII in the report.
