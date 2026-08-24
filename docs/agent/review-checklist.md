# Review checklist

Use this for every repository change. The reviewer verifies primary evidence; a delegate report,
tool summary, green badge, or issue checkbox is only a claim until checked.

## Scope and decisions

- [ ] The diff implements one primary SPM issue and stays inside its accepted scope.
- [ ] The branch, PR title, and PR body use the SPM linkage convention in `AGENTS.md`.
- [ ] Required plans and owner decisions predate changes to deployment/cloud, secrets/auth/OAuth,
      database/data movement/retention, public MCP/API contracts, privacy/PII, destructive work,
      or broad frameworks.
- [ ] Accepted ADRs and canonical docs still agree; a proposal is not treated as accepted.
- [ ] No unrelated cleanup, test deletion, or silent acceptance-criterion/cycle change entered the
      diff.

## Privacy and safety

- [ ] No credential, Spotify token, personal listening history, imported account data, email
      allowlist, database dump, or other PII appears in the diff, fixtures, logs, issue, or PR.
- [ ] Logging and error paths do not newly expose sensitive values.
- [ ] External and destructive actions had explicit authority, a stated blast radius, and a
      rollback or an honest statement that rollback is limited.
- [ ] Production and shared services were not changed merely to validate a repository edit.

## Behaviour and validation

- [ ] Behaviour or contract changes have the narrowest useful tests, with red-phase evidence when
      practical.
- [ ] No test was weakened to obtain green output.
- [ ] Commands ran against the reported revision and surface; real exit codes and relevant output
      were captured.
- [ ] Missing tools, empty results, malformed output, partial reads, and crashed checks fail closed
      and are reported as gaps rather than passes.
- [ ] `make agent-contract` (or its exact Python command) passes for agent-contract changes.
- [ ] Ruff, mypy, and the affected package suites pass where available; any environment gap names
      its owning Linear issue.
- [ ] `git diff --check` passes and the final file list matches the issue scope.

## Documentation and evidence

- [ ] Current-state, product, integration, deployment, decision, and memory documents were updated
      at the correct source-of-truth location, without creating a duplicate issue queue.
- [ ] Durable claims identify whether they are measured, inferred, or conjectural and include a
      revision, date, command, or external-object pin where useful.
- [ ] Every review finding has a disposition, and valid findings are fixed and revalidated.

## Pull-request and merge evidence

- [ ] The reviewed revision is the current PR head and GitHub reports it mergeable.
- [ ] `coderabbit-review` produced a validator-accepted transient evidence bundle after proving
      `build/review-evidence/` ignored; that directory was never staged, and validator success was
      not treated as merge authority.
- [ ] Reviews, PR conversation comments, review threads, nested comments/counter-replies, check
      runs, and commit statuses have complete terminal-page proof. API totals, unique item counts,
      audited source counts, and extracted finding counts reconcile without an omitted population.
- [ ] Any review reply and thread resolution used the expected current head and the correct comment
      database-ID/thread-node-ID domains. Reply preceded resolution; the created reply and resolved
      thread were each read back exactly. An API success response alone was not accepted.
- [ ] The current branch-protection rules were read live; every required check is green on that
      head and the required approving review targets that head.
- [ ] No unresolved review thread or known review still in flight remains.
- [ ] `gate-oracle` produced the final current-head readiness verdict from a known-good control,
      its motivating negative mutation, complete validated review evidence, and distinct live
      check-run and commit-status populations; its technical result was not treated as merge or
      deployment authority.
- [ ] Standing repository-delivery authority covered commit, normal push, PR creation/update, and
      any qualifying merge; deployment and production effects were separately authorized, and no
      gate was bypassed.
- [ ] Any authorized deployment followed the accepted documented deployment procedure, was
      monitored to a terminal result, and had its exact revision, environment, health evidence,
      and rollback posture verified; dispatch alone was not reported as success.
- [ ] After merge, the landed revision and Linear issue/dependency state were read back rather than
      inferred from automation.
