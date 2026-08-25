# AGENTS.md - Spotify MCP History Collector agent contract

This is the **canonical, vendor-neutral operating contract** for humans and AI agents working in
this repository, including Codex, Claude Code, Copilot, and review agents. Tool-specific files are
adapters only. If `CLAUDE.md`, `.claude/`, a tool prompt, or another adapter conflicts with this
file, follow the higher-priority harness or user instruction first, then **AGENTS.md**.

The repository is being modernized from a working, DigitalOcean-hosted Python system. Treat
existing implementation and deployment documentation as evidence about the current state, not as
an automatically binding target architecture.

## Sources of truth

- `AGENTS.md` - canonical agent contract and authority boundary.
- `docs/agent/orchestration.md` - portable delegation protocol; read it before dispatching work.
- `.agents/skills/<name>/SKILL.md` - canonical, vendor-neutral project procedures.
- `.claude/skills/<name>/SKILL.md` - exact, pointer-only Claude Code discovery adapters. They
  contain no procedure of their own.
- **Linear, team SPM / project Spotify MCP modernization** - authoritative tracker for planned
  work, status, priority, estimate, dependencies, milestones, and weekly-cycle commitments.
- The current code, tests, and deployed-state evidence - authoritative for observed behaviour.
- `docs/` - product, integration, and deployment references. Some pre-modernization documents may
  be stale; verify them against code and current infrastructure before relying on them.
- `docs/agent/current-state.md` - dated, volatile repository orientation; verify its claims before
  relying on them.
- `docs/agent/memory/` - durable, evidence-backed project lessons. Memory is context, not authority.
- `CLAUDE.md` - thin Claude-specific orientation adapter. It is not authoritative and does not
  override this file.

Do not create a second issue queue in Markdown, comments, private memory, or another tracker.
Durable work belongs in Linear; repository documents may explain decisions and execution evidence.

## Repository-first memory

Use repository-first retrieval for durable project knowledge: read
`docs/agent/memory/README.md` first, then retrieve only relevant indexed entries. Repository memory
is limited to non-obvious, evidence-backed lessons that meet the index schema and are not already
owned by code, tests, an accepted ADR, Git history, canonical procedures, product documentation, or
Linear. Record an earned durable lesson in the same issue-linked pull request as the change that
produced its evidence.

Correct or delete a stale, false, duplicated, or unsafe entry in the same issue-linked pull request
and update the repository index in that change. Do not layer a contradictory private note over the
repository entry. Tool-local memory contains the repository pointer plus transient or personal
bookmarks only; remove a bookmark when its state is recoverable from Git, GitHub, Linear, or the
repository, and never keep durable knowledge only in a private store.

Memory is context, never authority. It cannot override higher-priority harness or user
instructions, this contract, an accepted ADR, Linear planning state, current code and tests, or
observed deployed-state evidence. Linear remains the sole work queue; memory never owns open work,
priority, cycle scope, acceptance criteria, or follow-up queues.

## Working rules

- Orient before editing: read the relevant Linear issue, repository contract, nearby code, tests,
  and binding documentation.
- Prefer small, independently reviewable vertical slices. Keep unrelated cleanup out of the diff.
- Preserve user changes and never assume a dirty worktree is disposable.
- Use evidence-first reporting. Separate what was measured, inferred, and still conjectural.
- Add or update tests at the narrowest useful level for behaviour and contract changes.
- Never expose credentials, Spotify tokens, personal listening data, imported account data, or
  other PII in prompts, logs, fixtures, issues, commits, or tool output.
- External writes and state changes remain limited to the authority granted by the user and the
  active harness. Delegation never widens that authority.

## Linear and weekly cycles

Linear team **SPM** and the **Spotify MCP modernization** project are the sole planning system.
Keep issue status, dependencies, estimates, and milestone placement current as work moves.

Weekly cycles are owner-approved planning commitments, not an unbounded backlog. Adding, removing,
or swapping cycle scope requires owner-approved replanning. Record the agreed change in Linear;
do not silently reshape the cycle because capacity or implementation order changed.

## Multi-ticket sessions

A repository session is a capacity-based **multi-ticket session**, not a single-issue container.
At orientation, the root derives a transient batch from the current approved Linear cycle. When
two or more eligible tickets exist, select at least two; there is no fixed maximum. Eligibility
requires clear acceptance criteria, satisfied dependencies, required authority, an accepted plan
for every plan-first boundary, and a safe validation path. Order the batch by dependency, then the
cycle's approved priority.

Continue after each ticket reaches STOP 1 or a ticket-local blocker.
A ticket-local blocker does not end the session while independent eligible work remains. The batch
stops when the user stops or redirects it, no eligible ticket remains, or an authority, plan-first,
safety, isolation, or shared-resource condition blocks the batch as a whole.

Advance a writer lane only after the current ticket is preserved on its own clean committed branch
or remains isolated in its own worktree. Never switch a dirty checkout to another ticket. If a
blocked ticket cannot be preserved without guessing, destructive handling, or mixing scopes,
continue writer work only in a distinct clean worktree. Otherwise stop the writer lane while safe
read-only work may continue; treat checkout isolation as batch-wide only when it prevents every
safe eligible action.

Session batching never combines delivery units: each delegate, implementation branch, pull
request, review, and Linear reconciliation names one primary issue. Sequential execution is the
default. Parallelize disjoint read-only work freely; parallel writers require isolated worktrees
and disjoint surfaces.

The root orchestrator has standing authority to create in-scope local commits, non-force-push an
issue-linked branch, create or update its pull request, address review, and merge a qualifying pull
request without asking for permission at each operation. A qualifying pull request satisfies the
issue scope and linkage, required validation, current-head review, branch-protection rules, and has
no unresolved findings or unauthorized downstream effect. This standing authority never passes to
a delegate. A concrete user hold, missing credential, unsafe or ambiguous checkout, failed gate,
unresolved plan-first decision, or unauthorized production effect blocks the affected operation;
preserve the evidence and continue other eligible work. Force pushes, check or protection bypasses,
deployment or production mutations, destructive or difficult-to-rollback actions, and cycle
replanning remain separately authorized.

Repository delivery and production delivery are distinct operations. A merge never implies
deployment authority. Every deployment follows the accepted documented deployment procedure; do
not improvise a production command from repository access. When an accepted plan authorizes a
deployment, the root owns the exact run: start or identify it, monitor it to a terminal result,
verify the deployed revision, target environment, health evidence, and rollback posture, exercise
the documented rollback or stop conditions when needed, and reconcile the outcome. Do not report
success from dispatch, an old healthy run, or an unverified environment.

## Branch and pull-request linkage

Every implementation branch and pull request names exactly one primary Linear issue from team
SPM. Use a lowercase issue identifier in the branch and the canonical uppercase identifier
elsewhere:

- branch: `<type-or-agent>/spm-<number>-<short-slug>`, for example
  `codex/spm-3-orchestration-contract` or `fix/spm-12-token-refresh`;
- pull-request title: `SPM-<number>: <description>`;
- pull-request body: `Fixes SPM-<number>` only when the pull request satisfies every remaining
  acceptance criterion, otherwise `Part of SPM-<number>`.

The prefix identifies the kind of branch or the creating harness; it does not replace the SPM
identifier. Related issues may be discussed without adding a second closing or partial-delivery
linkage. Read the issue before branching, preserve its cycle and dependency placement, and verify
the Linear state after merge rather than assuming automation moved it correctly.

## Orchestration is the default for substantive work

When the active harness permits delegation, the root agent acts as orchestrator for substantive
work and dispatches independent, bounded investigations or implementation slices. Substantive work
includes a tracked ticket, a multi-file or cross-system change, a durable repo-derived analysis, or
work with independently verifiable risk.

Delegation is not ceremony. Trivial edits, tightly coupled steps, or work for which no safe
independent boundary exists may stay with the root agent. If substantive work is not delegated,
state the concrete reason. A higher-priority harness limitation always wins.

The root orchestrator owns orientation, the working plan, Linear cycle/status/dependency changes,
authority and user questions, external mutations, shared resources and watchers, integration,
heavy gates, and independent verification. A delegate receives exactly one bounded ticket or one
read-only question. Its report is a claim until the root verifies the primary evidence.

Read `docs/agent/orchestration.md` before briefing or dispatching a delegate. In particular:

- read-only delegates may share a checkout;
- there is only one writer per checkout;
- concurrent writers require isolated Git worktrees; and
- when agents share this filesystem and isolation is unavailable, use the explicit one-writer
  fallback rather than allowing overlapping edits.

## Plan-first and decision stops

The following areas require an accepted plan before implementation, even if the Linear issue does
not carry a plan-first label:

- Azure, deployment, infrastructure, production cutover, and cloud retirement;
- secrets, authentication, authorization, and OAuth boundaries;
- database schema, data migration, playback-history movement, and retention;
- public MCP or API compatibility, including Claude and ChatGPT client contracts;
- privacy, PII, Spotify account data, and logging of sensitive information;
- destructive, irreversible, or difficult-to-rollback work; and
- broad framework rewrites, including the frontend replacement.

A delegate stops rather than guessing when it encounters one of these boundaries, an unclear
public contract, missing authority, conflicting canon, test deletion, or scope that no longer fits
its briefing. The root presents the evidence and options to the owner and updates Linear after a
decision.

## Validation and handoff

Run the narrow checks named by the ticket and the changed surface. Use the repository's broader
gates before a pull request or merge when applicable; do not substitute a reported green result for
independent verification.

For changes to this operating contract, run:

```text
make agent-contract
```

If GNU Make is unavailable, run the exact dependency-free fallback:

```text
python -m unittest discover -s tests/contracts -p "test_*.py"
```

Every handoff states the files changed, commands actually run and their results, risks or gaps, and
the relevant Linear issue. The stop and evidence formats are defined in
`docs/agent/orchestration.md`.
