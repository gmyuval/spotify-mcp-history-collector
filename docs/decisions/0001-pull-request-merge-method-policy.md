# ADR 0001 - Use merge commits by default for pull requests

Date: 2026-08-23 (UTC)
Status: Accepted
Decision owners: Yuval Moran
Linear issue: [SPM-31](https://linear.app/stratex/issue/SPM-31/make-merge-commits-the-default-pull-request-merge-strategy)

## Context

GitHub exposes which merge methods a repository permits, but does not select one as this
repository's workflow default. The canonical PR lifecycle previously required agents to query the
live settings and protection without resolving which method to use when several qualified. The
dated configuration evidence for this decision belongs in `docs/agent/current-state.md` and must be
rechecked before every merge.

## Decision drivers

- Preserve the branch history and ticket-level integration context of reviewed pull requests.
- Make autonomous qualifying merges deterministic without weakening live protection checks.
- Keep exceptional methods available without silently turning them into the routine path.
- Avoid mixing merge-method policy with deployment or GitHub-settings mutations.

## Options considered

1. Select `merge` explicitly by default and retain squash/rebase as documented exceptions.
2. Disable squash and rebase in repository settings.
3. Leave all methods available without a workflow default.

## Decision

The root invokes the GitHub merge operation with the `merge` method explicitly for every qualifying
pull request. Before merging, it re-queries method availability, branch protection, and required
linear history. If merge commits are unavailable or linear history is required, it stops and
reconciles the mismatch rather than substituting another method or changing protection.

Squash and rebase remain enabled as explicit alternatives. Use one only when direct owner
instruction or the issue's accepted scope names it. Every exception must be justified in the pull
request. If an agent proposes either exception, it must prompt the owner with the requested method
and rationale, then obtain explicit approval before using it. Selecting a method never authorizes
repository-settings, branch-protection, deployment, or production mutations.

## Consequences

- Normal pull-request integration preserves a merge node and makes the chosen method explicit.
- Squash and rebase remain available for deliberate exceptions, so GitHub settings need not change.
- The lifecycle must fail closed if future settings or linear-history rules conflict with this
  default.
- Commit history is less linear than squash or rebase-only history.

## Validation

The dependency-free agent-contract validator requires the explicit merge default, alternative
boundary, agent-proposed exception owner prompt, live-setting check, and no-mutation rule. Its tests
mutate the canonical lifecycle and prove the validator reports `PR_LIFECYCLE_MERGE_POLICY`.

## Rollback / revisit trigger

Revisit this ADR if GitHub adds a repository-level default selector, main requires linear history,
merge commits are disabled, or measured review/history costs justify another method. Rollback is a
new accepted decision plus the matching lifecycle and contract-test change; do not silently weaken
the validator.

## Related decisions

SPM-30 keeps production deployment manual and separate from merges. This decision does not change
that boundary.
