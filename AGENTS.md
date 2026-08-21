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
- **Linear, team SPM / project Spotify MCP modernization** - authoritative tracker for planned
  work, status, priority, estimate, dependencies, milestones, and weekly-cycle commitments.
- The current code, tests, and deployed-state evidence - authoritative for observed behaviour.
- `docs/` - product, integration, and deployment references. Some pre-modernization documents may
  be stale; verify them against code and current infrastructure before relying on them.
- `CLAUDE.md` - transitional Claude adapter followed by a legacy technical snapshot. It is not
  authoritative and does not override this file.

Do not create a second issue queue in Markdown, comments, private memory, or another tracker.
Durable work belongs in Linear; repository documents may explain decisions and execution evidence.

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

Every handoff states the files changed, commands actually run and their results, risks or gaps, and
the relevant Linear issue. The stop and evidence formats are defined in
`docs/agent/orchestration.md`.
