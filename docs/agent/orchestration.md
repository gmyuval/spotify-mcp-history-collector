# Orchestrated delegation

This is the portable orchestration protocol for Spotify MCP modernization work. `AGENTS.md` is
canonical and wins if this document conflicts with it. Tool- or vendor-specific adapters must link
here rather than copy and fork the protocol.

## When to use it

Substantive work defaults to orchestration when the harness provides safe delegation. The root may
work directly on a trivial or tightly coupled change, or when delegation/isolation is unavailable,
but states why when the work is otherwise substantive. Delegation must reduce ambiguity or create
independent verification; it is not a quota to satisfy.

## Session batch

At orientation, the root builds a transient batch from Linear rather than creating a repository
queue. A ticket is eligible when it is in the current approved cycle, its acceptance criteria and
authority are clear, its blocking dependencies are satisfied, every applicable plan-first decision
is accepted, and its validation can run safely. Select two or more eligible tickets when available;
there is no fixed maximum. If only one ticket is eligible, work it and report why a multi-ticket
batch was unavailable. Order selected work by dependency order, then Linear's approved priority.

The batch is a session plan, not a delivery unit. Every delegate, branch, pull request, review, and
tracker reconciliation still owns exactly one primary issue. Record batch selection and progress
in the session working plan and Linear issue states; do not persist a second backlog in Markdown.

## Roles and authority

The **root orchestrator** owns:

- repository and live-state orientation, the execution plan, and scope boundaries;
- Linear cycle, status, estimate, milestone, and dependency bookkeeping;
- authority checks, owner questions, and all external mutations;
- shared-machine resources, ports, containers, long-running processes, API quota, and watchers;
- integration order, conflict resolution, and heavy or cross-service gates; and
- independent verification of every delegate report against primary evidence.

A **delegate** owns exactly one bounded ticket, implementation slice, or read-only question. It
reads the named sources, works only in its permitted surface, runs the stated narrow validation,
and reports evidence and uncertainty. It does not inherit unstated session context or authority.
Delegation never widens the root's authority, the user's request, or the active harness rules.

Reports are claims until the root verifies them. A plausible summary, pasted output, green badge,
or delegate assertion is not a substitute for reading the relevant diff, command result, tracker
state, or remote object.

## The briefing contract

The briefing is the delegate's complete contract. It includes all of the following:

1. **Goal and unit of work** - one Linear ticket or one bounded read-only question, with the desired
   outcome and acceptance criteria.
2. **Scope and permitted writes** - exact paths or surfaces the delegate may change.
3. **Explicit prohibitions and reasons** - what must not change and why the constraint exists.
4. **Required reading** - `AGENTS.md`, the Linear issue, relevant decisions, code, tests, and docs.
5. **Validation** - commands to run, expected evidence, and which heavy gates remain root-owned.
6. **Plan-first and decision stops** - the boundaries that require an accepted plan or owner choice.
7. **Reporting and evidence** - changed files, diff/state pins, commands and real output, risks,
   unresolved questions, and whether each claim is measured, inferred, or conjectural.
8. **Not-yours list** - tracker changes, unrelated cleanup, external writes, watchers, merges,
   credentials, deployment, or any other root-owned activity.
9. **Harness and isolation context** - the active harness's delegation and filesystem-isolation
   capabilities, checkout/worktree path, branch and starting revision, dirty state, concurrent
   agents, shared services, protected resources, and the required fallback when isolation is absent.
10. **Stops and progress** - when to report, when to stop, and the meaning of STOP 1 and STOP 2.

A claim in a briefing has the same evidence burden as a claim in a report:

- **Measured** names the command or primary source plus the checkout, revision, and scope.
- **Inferred** names the observation and the reasoning from it.
- **Conjectural** says what evidence would settle the claim and who will obtain it.

The delegate rechecks assertions against its actual tree. A disagreement supported by evidence is
a finding to report, not an instruction to suppress.

## Checkout and writer isolation

The root must establish the active harness's filesystem-sharing and isolation model in every
briefing. Read-only delegates may share a checkout only when they do not change branches or files.
**Only one writer may use a checkout.** If two delegates need to write concurrently, the root must
give each an isolated Git worktree with a named path, branch, starting revision, and ownership
boundary.

If isolated worktrees are unavailable, use the one-writer fallback: one delegate writes while the
root and all other delegates remain read-only, then the root verifies and releases the writer lane.
Never rely on good intentions to make simultaneous writers safe. Do not switch a shared checkout's
branch while a delegate is reading it, and never remove a worktree with unmerged or blocked work.

## Mandatory decision stops

A delegate stops and reports evidence and options before changing:

- Azure, deployment, infrastructure, production traffic, or the DigitalOcean estate;
- secrets, authentication, authorization, OAuth, or managed identity;
- a database schema, data migration, retention rule, or user playback history;
- a public MCP/API schema or Claude/ChatGPT compatibility contract;
- privacy, PII, logging, or real Spotify account data;
- destructive or irreversible state; or
- the frontend framework or another broad architectural boundary.

It also stops on unclear authority, conflicting instructions, an infeasible acceptance criterion,
a requested test deletion/weakening, or scope expansion. The delegate does not work around the
boundary. The root takes the question to the owner and records approved replanning in Linear.

## Execution and stops

The normal sequence is orient, brief, implement/investigate, validate, STOP 1, root verification,
integration/review, and STOP 2.

Sequential execution is the default: bring one ticket to STOP 1, verify it, preserve its branch or
worktree, then advance to the next eligible ticket. A ticket-local blocker pauses that ticket and
the root continues independent batch work. A **batch-wide stop** applies when the user stops or
redirects the session, no eligible ticket remains, or authority, plan-first, privacy/safety,
checkout isolation, shared resources, or integration order prevents every safe next action.

Preserving a writer lane means either a clean committed ticket branch or a dedicated worktree that
retains that ticket's dirty state. Never switch a dirty checkout to another ticket or mix ticket
changes in one branch. When safe isolation is unavailable, the blocked dirty lane stops further
writer work even if independent read-only work can continue.

### STOP 1 - implementation-ready (local-ready) or pull-request-ready

STOP 1 means the bounded work is ready for root verification. The report states which form applies:

- **Local-ready** - changes are uncommitted or intentionally local. Report checkout, branch,
  starting revision, `git status`, changed files, focused diff, validation command/output, and open
  risks. Do not call this pull-request-ready.
- **Pull-request-ready** - only when the authorized workflow has a branch/commit or pull request to
  inspect. Report its stable identifier and revision in addition to the same scope and validation
  evidence.

The root independently checks the actual file list and diff, scope and prohibitions, required docs,
tests and command results, and any environmental claim. The root, not the delegate, decides whether
the work advances.

### STOP 2 - merged or blocked

STOP 2 is terminal for the delegated unit:

- **Merged** - the authorized review workflow completed. The root verifies the merge revision,
  required checks, Linear completion/dependencies, and deployment/health evidence when applicable.
- **Blocked** - progress requires an owner decision, authority, unavailable dependency, or external
  state. Report the exact blocker, evidence, safe options, preserved worktree/state, and next owner.

Never translate "implementation finished" into "merged", "deployed", or "done" without primary
evidence for that later state.

## Progress, watching, and integration

Delegates report at phase transitions and before a long-running command, then return at the next
stop. They do not poll remote systems or arm background watchers. The root owns watchers and checks
their live output after sleeps, disconnects, or long quiet periods.

Parallelism is limited by independence: disjoint read-only investigations can run together;
implementation can overlap only in isolated worktrees and with disjoint surfaces. The root
serializes shared services, heavy gates, integration, external mutations, and owner decisions.

After each verified STOP 1 or ticket-local blocker, the root re-reads affected dependencies,
authority, plan-first posture, current-cycle membership, and eligibility before advancing. A newly
unblocked ticket may enter the transient batch only when it is already inside the approved cycle;
adding or swapping cycle scope still requires owner-approved replanning.

The root keeps Linear current but does not create a duplicate queue. Weekly cycle changes require
owner-approved replanning before issues are added, removed, or swapped. The standing
throughput-based replenishment procedure in `AGENTS.md` is such an approval for its deterministic
case: when the current cycle has no open work and time remains, calculate remaining capacity from
observed throughput, preserve carryover, and replenish it with dependency-ready work. Fill the
existing upcoming cycles to the same planning horizon, update and read back their Linear planning
evidence, then re-derive the transient batch and provide the copyable next-session prompt required
by `AGENTS.md`. Any departure from that rule returns to an owner decision.
