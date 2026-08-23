---
name: adr-new
description: >-
  Create, accept, amend, or supersede a Spotify MCP architecture decision record when a
  consequential convention or plan-first boundary needs durable owner-approved history.
---

# New or changed ADR

Decision records live in [`docs/decisions/`](../../../docs/decisions/). An ADR records a decision;
it does not create authority, approve its own plan, or serve as an implementation backlog.

## When to use an ADR

Use one for a consequential convention future changes must follow, a material architecture or
security boundary, or an amendment/supersession of an accepted decision. Routine, reversible,
in-scope implementation normally needs only its Linear issue, tests, and PR.

The following remain plan-first even when an ADR is the desired record: Azure/DigitalOcean,
deployment/infrastructure/cloud retirement, secrets/authentication/authorization/OAuth, database
schema/data movement/playback-history retention, public MCP/API compatibility, privacy/PII,
destructive work, and broad framework replacement. Obtain the owner's decision before marking an
ADR Accepted or changing implementation.

## Procedure

1. Read `AGENTS.md`, the SPM issue and accepted plan, relevant code/tests, existing accepted ADRs,
   and [`docs/decisions/README.md`](../../../docs/decisions/README.md).
2. Take the exact `Next number` from the index. Confirm that it is unused; never renumber or reuse
   an identifier.
3. Copy the structure from [`docs/decisions/template.md`](../../../docs/decisions/template.md) into
   `docs/decisions/NNNN-kebab-case-title.md`.
4. Use the real UTC date. Name the decision owners and SPM issue. Use `Proposed` unless the owner
   has already accepted the decision.
5. Ground Context in verified constraints. Record meaningful drivers and competing options, the
   precise Decision, positive and negative Consequences, validation, and an observable rollback or
   revisit trigger.
6. Update the index row and increment `Next number` in the same change. If an ADR is amended or
   superseded, preserve its history and update every affected index row; never silently rewrite or
   delete an accepted record.
7. Update `AGENTS.md`, current-state, product/architecture, integration, security, or deployment
   documentation in the same change when the decision makes an existing canonical statement
   false. Keep volatile status out of the ADR.
8. Validate links, numbering, index/file/status agreement, `git diff --check`, and the changed
   surface. Run `make agent-contract` whenever the agent contract or referenced paths change.
9. Follow [`pr-lifecycle`](../pr-lifecycle/SKILL.md) for commit/review/publication, within the exact
   authority granted for GitHub and production effects.

An ADR may link follow-up Linear issues but must not embed a second issue queue. Separate accepted
and provisional decisions explicitly. If evidence later disproves an accepted premise, amend or
supersede the record rather than working around it in private memory.
