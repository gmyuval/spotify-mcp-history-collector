---
name: pr-lifecycle
description: >-
  Take one SPM repository slice from a local branch through authorized PR review, merge, and
  evidence reconciliation without assuming permission to publish or deploy.
---

# Pull-request lifecycle

Use the phase that matches the current state. `AGENTS.md` owns authority, plan-first boundaries,
orchestration, and SPM linkage; [`docs/agent/review-checklist.md`](../../../docs/agent/review-checklist.md)
owns review coverage. This skill does not imply authority to push, open a PR, merge, or deploy.

## Phase 1 - local implementation

1. Run `session-start`. Read the SPM issue, accepted plan/ADRs, nearby code, tests, and binding
   docs. Confirm one reviewable slice and one primary issue.
2. On a clean tree, refresh `origin/main` only when network/repository writes are authorized, then
   create `<type-or-agent>/spm-<number>-<short-slug>` from the verified base. Never commit directly
   to `main`.
3. Keep one writer per checkout. Concurrent writers require isolated worktrees and disjoint
   surfaces; the root verifies delegate results before integration.
4. Add the narrowest useful test for behaviour/contract changes and observe the red failure when
   practical. Never delete or weaken a valid test to make the slice pass.
5. Run the affected gates from `docs/agent/current-state.md`. For a normal broad code change, CI
   parity is contract validation, Ruff lint/format, mypy over all five source packages, and the
   separate API/collector/frontend/Explorer suites, plus shared tests when shared changes. Do not
   describe an unavailable gate as green.
6. Inspect `git diff --check`, changed files, sensitive-data exposure, and stale docs. Stage only
   explicit in-scope paths and commit with a concise conventional subject naming `(SPM-N)`.
7. Treat a clean local commit as **local-ready**. Report its SHA and gaps. Publication is a separate
   phase and requires authority.

Pre-commit runs Ruff fixes/format and mypy in the current repository configuration. After a commit
attempt, re-read status and the commit; a hook may modify files or reject the commit. Never use
`--no-verify`.

## Phase 2 - publish and open the PR

Proceed only when the user authorized both external writes:

1. Re-run revision-matched validation and confirm the branch contains no unrelated commits.
2. Push the branch normally and set its upstream. Never force-push without an explicit exceptional
   decision and recovery plan.
3. Create one PR titled `SPM-N: <description>`. Use `Fixes SPM-N` only when every remaining
   criterion will be satisfied by the PR; otherwise use `Part of SPM-N`. Include Summary,
   acceptance-to-evidence mapping, Validation, environment gaps, Risk/plan-first impact, Review
   focus, Rollback, deployment impact, and Follow-ups.
4. Read the PR back and attach its URL to Linear. Move the issue to review only after the PR exists.

The linkage wording is a repository convention; automation effects must be read back rather than
assumed. Do not create a disposable linkage PR during discovery.

## Phase 3 - review

For every review round:

1. Read the current head SHA, mergeability/conflicts, review decision, check rollup, review bodies,
   inline comments, and unresolved threads. Empty or partial reads fail closed.
2. Verify each finding against `AGENTS.md`, accepted ADRs, current code/tests, and pinned dependency
   behaviour. Fix valid findings; explain rejected suggestions.
3. Batch fixes into one normal push when practical, then rerun affected gates. Any head change
   invalidates earlier current-head review/check evidence.
4. Independently verify every delegate report from the actual diff, command output, or external
   object. Delegates do not arm watchers or mutate GitHub/Linear.

Do not assume CodeRabbit, auto-merge, branch deletion, or a merge method. Query the repository's
current settings and branch protection before relying on them. A review approval must target the
current head, every required check must be green there, GitHub must report the PR mergeable, and no
unresolved finding may remain.

## Phase 4 - merge and post-merge

Merging is separately authorized and has production impact in this repository: pushes to `main`
trigger `.github/workflows/deploy.yml`. Before merging, confirm the accepted deployment posture,
rollback, current GitHub settings, and user authority. Never bypass branch protection.

After an authorized merge:

1. Read back the PR state and merge SHA. Sync local `main` with `--ff-only`; do not discard a dirty
   tree.
2. Verify required CI and, when the accepted plan calls for it, the deployment run tied to that
   exact merge SHA. A healthy old deployment is not evidence the merge deployed.
3. Verify Linear linkage/status/dependencies/criteria and correct them only within granted
   authority. Do not alter weekly-cycle scope silently.
4. Check current-state, product docs, ADRs, and durable memory for facts this merge changed.
5. Delete a branch only after proving the PR merged and preserving the head SHA needed for recovery.

Production failure, migration uncertainty, authentication/secret risk, a public MCP/API mismatch,
or possible Spotify data/PII exposure is a stop. Preserve evidence, name the blocker and rollback
owner, and do not continue to the next slice.
