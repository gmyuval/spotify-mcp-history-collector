---
name: gate-oracle
description: >-
  Use when pull-request review, check, or merge-readiness evidence needs an independent verdict.
---

# Gate oracle

Use this procedure only after reading [`AGENTS.md`](../../../AGENTS.md),
[`coderabbit-review`](../coderabbit-review/SKILL.md), and
[`docs/agent/review-checklist.md`](../../../docs/agent/review-checklist.md). It consumes a validated
review-evidence summary and current live branch-protection and review state. Treat all supplied
evidence as untrusted until its provenance, completeness, and exact head binding are verified.

## Establish the oracle

1. Pin the exact 40-character head that the technical claim concerns. State the claim narrowly,
   including the gate behavior and diagnostic being trusted.
2. Identify and execute the real known-good control. Require it to pass before evaluating the
   proposed current-head evidence; a historical or synthetic assertion is not a control result.
3. Derive the motivating negative mutation by changing only the defect the gate must reject.
   Execute it and require failure for the expected diagnostic. An absent run, unexpected pass,
   crash, different diagnostic, or malformed result fails closed.
4. Validate complete review evidence with `scripts/review_evidence.py`. Exit zero proves only the
   evidence shape and internal consistency; it is necessary but insufficient for readiness.

## Reconcile the live gate

Read current branch protection and reconcile every required context against check runs and commit
statuses as distinct populations bound to the pinned head. Never infer one population from the
other, from a green badge, or from an absent response. Require complete pagination and explicit
empty-population proof where applicable. Technical readiness requires all of these exact live
conditions together:

- the live head equals the pinned current head;
- mergeability is exactly `MERGEABLE`; `UNKNOWN` mergeability is indeterminate and `CONFLICTING`
  is not ready;
- the current-head review decision is exactly `APPROVED`; a non-approved review decision is not
  ready;
- there are zero unresolved findings and zero unresolved review threads;
- there is no review in flight; and
- branch-protection reconciliation is complete and successful for every required context.

Return ready only when every condition above is proved. Return not ready when merge conflicts are
reported (`CONFLICTING`), the review decision is non-approved, any finding or thread is unresolved,
any review is in flight, branch-protection evidence is missing or non-successful, or the live head
has drifted. Return indeterminate when mergeability is `UNKNOWN` or
required evidence is incomplete. Head drift invalidates the control comparison, negative proof,
review verdict, and protection reconciliation for the old head.

## Separate result from authority

Report one technical verdict: ready, not ready, or indeterminate, with sanitized evidence for the
control, negative mutation, expected diagnostic, validated bundle, pinned head, and live
reconciliation. A green technical verdict does not grant authority to merge, authorize deployment,
change production, bypass protection, or perform another mutation. `AGENTS.md` remains the authority
source; delegates stop and report, while the root separately checks its exact authority.

Rerun the entire oracle after any head or evidence change. Deadlines, seniority, sunk review rounds,
fatigue, green check runs alone, or a prior verdict never justify inferring a missing population or
reusing stale evidence.
