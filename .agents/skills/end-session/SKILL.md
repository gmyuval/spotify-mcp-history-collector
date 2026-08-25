---
name: end-session
description: >-
  Reconcile and hand off Spotify MCP repository work before stopping, including local-only
  committed work, an unpushed branch, a blocked PR, or a completed merge.
---

# End session

Leave enough repository and tracker evidence for another session to resume without reconstructing
the work from chat. The normal terminal state uses the root's standing repository-delivery
authority. A clean local commit on an unpushed branch remains valid when a concrete publication
gate or user hold exists; report the reason instead of silently treating it as complete.

## 1. Account for every local state

Run from the repository root:

```text
git status --short --branch
git branch --show-current
git rev-parse HEAD
git branch -vv
git stash list
git diff --check
git diff --cached --check
```

Inventory untracked, unstaged, staged, and committed-but-unpushed work. After identifying a
verified base revision, also run `git diff --check <verified-base>...HEAD` so committed branch work
is covered. Git diff does not inspect untracked content: validate each intended untracked file
directly, or stage only its explicit path after review when a commit is authorized, then rerun the
cached check. Preserve unrelated user changes. Do not clean, stash, discard, switch, delete
branches, or rewrite history merely to make the report tidy.

If remote freshness matters, classify `git fetch --prune origin` honestly: it contacts GitHub and
writes remote-tracking refs under `.git`. A cached upstream comparison is not proof of current
remote state.

## 2. Update durable repository context only when earned

Read [`docs/agent/memory/README.md`](../../../docs/agent/memory/README.md) before relevant indexed
entries. Distinguish an earned durable lesson from a transient or personal bookmark. Record any
earned entry and index change in the same issue-linked pull request as its evidence. Remove a landed
bookmark and any bookmark whose state is recoverable from Git, GitHub, Linear, or the repository.

Before updating durable context, evaluate whether an owner request, a substantive escape or
incident, or repeated evidence of a shared cause earns a retrospective. A single ordinary
correction does not trigger one. When a trigger is present, read
[`.agents/skills/retro/SKILL.md`](../retro/SKILL.md) completely and follow it; do not duplicate its
procedure here.

Update `docs/agent/current-state.md` when the observed repository/deployed posture changed. Add a
memory topic under `docs/agent/memory/` only for a non-obvious, evidence-backed lesson that is not
already expressed by code, tests, Git history, an ADR, or this contract. Never store a transient
resume bookmark or action-bearing instruction as durable memory.

## 3. Reconcile scope and sensitive content

Review the actual changed-file list and the diff against the issue/base. Confirm it contains only
the authorized SPM slice. Inspect content without rendering secret or PII matches into the
transcript.

Publication is blocked by any credential, Spotify token, `.env` value, key material, personal
listening history, imported account data, email allowlist, database dump, raw diagnostic, or other
PII. Report only the path and rule/category. A clean heuristic scan lowers risk; it does not prove
that no secret exists.

## 4. Run and pin validation

For agent-contract, skill, adapter, `CLAUDE.md`, or `docs/agent` changes, run:

```text
make agent-contract
```

If `make` is unavailable, run and report the exact underlying command:

```text
python -m unittest discover -s tests/contracts -p "test_*.py"
```

Run the unstaged, cached, verified-base-through-HEAD, and intended-untracked whitespace checks
described above, plus the focused/CI-parity gates for every changed code surface. Reuse fresh,
revision-matched evidence rather than rerunning expensive checks for ceremony. Never convert an
unavailable tool into a pass; record the environment gap and its Linear owner (mypy is tracked by
SPM-2 on the known local host).

After any commit attempt, inspect `git status` again because pre-commit hooks may modify files or
reject the commit. Pin successful evidence to the final commit or explicitly say it was run on the
pre-commit working tree.

## 5. Preserve work under the granted authority

- The root creates in-scope commits, non-force pushes issue-linked branches, opens or updates pull
  requests, handles review, and merges qualifying pull requests under standing authority. Stage
  explicit in-scope paths rather than the whole tree. This authority never passes to delegates.
- Preserve a local or merge-ready state when a concrete user hold, missing credential, unsafe or
  ambiguous checkout, failed gate, unresolved plan-first decision, or unauthorized downstream
  effect blocks the next operation.
- Deploy, change cloud or production state, and update shared services only when separately
  authorized. Do not merge when it would trigger one of those unauthorized effects. When a
  deployment is authorized, follow the accepted documented deployment procedure, monitor the exact
  run to a terminal result, and verify its revision, environment, health, and rollback evidence.
- Never use force push, `--no-verify`, check bypasses, or a destructive cleanup as a shortcut.
- Do not delete a branch merely because its remote is absent. Prove its work landed or keep it.

If the user requested a local commit without publication, verify the clean tree, full commit SHA,
missing/present upstream, absent/present remote branch, and absent/present PR. That is a complete
local-ready handoff, not a pull-request-ready claim.

## 6. Reconcile Linear from evidence

For each selected ticket and every additional SPM issue touched:

- check only acceptance criteria supported by the final diff and validation;
- leave the issue started when work is local/unpushed or criteria remain;
- move it to review only when a real PR exists;
- complete it only after the required delivery state is verified;
- preserve dependencies, milestone, estimate, and owner-approved cycle scope;
- add one concise evidence comment when it materially improves the handoff.

Record each selected ticket's terminal session state: verified STOP 1; verified STOP 2/merged;
blocked with its exact reason/owner; or not started with the eligibility change that prevented it.
Name the next eligible ticket. A ticket-local blocker is not a reason to wrap while independent
eligible work remains; identify the user direction or batch-wide stop that ended the session.

Read the resulting issue back after any write. Do not create a second issue queue or invent a
follow-up during wind-down.

## 7. Hand off

Report all of the following:

- relevant Linear issue and reconciled status/criteria;
- the selected batch, per-ticket outcome, blocked/skipped reasons, and next eligible work;
- changed files and final diff scope;
- commands actually run, revision, exit/result, and environment gaps;
- branch, full commit SHA, clean/dirty state, upstream, remote branch, and PR state;
- risks, plan-first decisions, unresolved review findings, and the exact next action/owner;
- confirmation that no unauthorized push, PR, merge, deployment, cycle change, or production
  mutation occurred; for an authorized deployment, name the exact monitored run, terminal result,
  deployed revision, and verified health or rollback outcome.

Include a concise copyable continuation prompt when another session is expected. State what cannot
be recovered from the repository; do not repeat everything that the repository already records.
