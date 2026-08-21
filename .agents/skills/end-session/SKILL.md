---
name: end-session
description: >-
  Reconcile and hand off Spotify MCP repository work before stopping, including local-only
  committed work, an unpushed branch, a blocked PR, or a completed merge.
---

# End session

Leave enough repository and tracker evidence for another session to resume without reconstructing
the work from chat. The terminal state is the one the user authorized: a clean local commit on an
unpushed branch is valid when publication was withheld; it must be reported, not silently pushed.

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

## 2. Reconcile scope and sensitive content

Review the actual changed-file list and the diff against the issue/base. Confirm it contains only
the authorized SPM slice. Inspect content without rendering secret or PII matches into the
transcript.

Publication is blocked by any credential, Spotify token, `.env` value, key material, personal
listening history, imported account data, email allowlist, database dump, raw diagnostic, or other
PII. Report only the path and rule/category. A clean heuristic scan lowers risk; it does not prove
that no secret exists.

## 3. Run and pin validation

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

## 4. Preserve work under the granted authority

- Commit only when authorized, staging explicit in-scope paths rather than the whole tree.
- Push, open/update a PR, merge, deploy, change cloud state, and update shared services only when
  separately authorized.
- Never use force push, `--no-verify`, check bypasses, or a destructive cleanup as a shortcut.
- Do not delete a branch merely because its remote is absent. Prove its work landed or keep it.

If the user requested a local commit without publication, verify the clean tree, full commit SHA,
missing/present upstream, absent/present remote branch, and absent/present PR. That is a complete
local-ready handoff, not a pull-request-ready claim.

## 5. Reconcile Linear from evidence

For each SPM issue touched:

- check only acceptance criteria supported by the final diff and validation;
- leave the issue started when work is local/unpushed or criteria remain;
- move it to review only when a real PR exists;
- complete it only after the required delivery state is verified;
- preserve dependencies, milestone, estimate, and owner-approved cycle scope;
- add one concise evidence comment when it materially improves the handoff.

Read the resulting issue back after any write. Do not create a second issue queue or invent a
follow-up during wind-down.

## 6. Update durable repository context only when earned

Update `docs/agent/current-state.md` when the observed repository/deployed posture changed. Add a
memory topic under `docs/agent/memory/` only for a non-obvious, evidence-backed lesson that is not
already expressed by code, tests, Git history, an ADR, or this contract. Never store a transient
resume bookmark or action-bearing instruction as durable memory.

## 7. Hand off

Report all of the following:

- relevant Linear issue and reconciled status/criteria;
- changed files and final diff scope;
- commands actually run, revision, exit/result, and environment gaps;
- branch, full commit SHA, clean/dirty state, upstream, remote branch, and PR state;
- risks, plan-first decisions, unresolved review findings, and the exact next action/owner;
- confirmation that no unauthorized push, PR, merge, deployment, cycle change, or production
  mutation occurred.

Include a concise copyable continuation prompt when another session is expected. State what cannot
be recovered from the repository; do not repeat everything that the repository already records.
