# Task template

Linear team **SPM** is the operational task system. Use this vendor-neutral shape when creating or
reviewing a Linear issue; do not maintain completed copies here or turn this file into a second
queue.

```markdown
## Goal
<one checkable outcome>

## Context and sources
<why now; Linear/project/milestone, code, test, incident, ADR, or live-state evidence>

## Measured baseline
<revision/environment/command or external object that pins the starting facts>

## Scope
<included files, systems, behaviours, and permitted writes>

## Non-goals and prohibitions
<excluded work and why it is excluded>

## Plan-first and authority
Plan-first boundary: yes / no
Accepted plan or owner decision: <link or n/a>
External writes authorized: <standing repository delivery; exact additional systems/actions; or none>
Destructive or difficult-to-rollback action: yes / no

## Dependencies and cycle
<blocking/blocked issues, milestone, estimate, and approved weekly-cycle placement>

## Privacy and security
<Spotify account data, listening history, tokens, credentials, logs, fixtures, or none>

## Acceptance criteria
- [ ] <observable outcome>

## Validation
- [ ] <command or read-back plus expected evidence>
- [ ] Environment gaps are reported separately from passing checks.

## Review focus
<highest-uncertainty or highest-impact part of the change>

## Rollback or revisit trigger
<how to undo/recover, or why rollback is limited; observable trigger to reconsider>

## Follow-ups
<known deferrals that remain in Linear and do not expand this task>
```

The issue is context, not independent authority for a new external mutation. When acceptance
criteria, scope, dependencies, or cycle membership change, record the owner-approved result in
Linear before implementation proceeds.
