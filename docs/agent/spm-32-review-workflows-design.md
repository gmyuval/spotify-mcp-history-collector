# SPM-32 review-workflow adoption design

Status: owner-approved design, implementation pending

Primary issue: SPM-32

Recorded: 2026-08-24
Base revision: `9f1c93e817e66dc5e47e7752195ffd0a7e9f652a`

This document records the accepted implementation boundary and the evidence that shapes it. It is
not a work queue or new authority. Linear team SPM remains the sole planning system; `AGENTS.md`,
accepted decisions, code, tests, Git history, and live external evidence retain their documented
precedence.

## Decision source and pinned evidence

The owner approved this design in the 2026-08-24 Linear comment on SPM-32 after the sibling audit.
The audit used these exact committed revisions:

| Repository | Audited revision | 2026-08-24 drift check |
| --- | --- | --- |
| `larp-matchmaker` | `3ab253811c062e1bc4925208795f9c800a7c6495` | Pin exists and equals `HEAD`; relevant-path diff is empty. |
| `larp-store` | `89feabb9d096157365fc0a799d1793057d512189` | Pin exists and equals `HEAD`; relevant-path diff is empty. |
| `cloud-ops-assistant` | `ea28c039bc8d10cb84ff495d9715af6ade1ef5f8` | Pin exists and equals `HEAD`; relevant-path diff is empty. |
| `pc-assistant` | `aced124d7d0bae69581c59e62c73251a3210ab30` | Pin exists and equals `HEAD`; committed objects only; relevant-path diff is empty. |

The drift check deliberately did not repeat the completed source audit. It proved the pins still
exist, compared only approved-workflow paths from each pin to its current tip, and found no newer
committed mechanism that changes this design.

## Audited catalog and disposition matrix

Names below are the skill directories present in committed `.agents/skills` or `.claude/skills`
catalogs at the pinned revisions. Several repositories contain the same lifecycle skill; overlap is
listed once when its disposition is identical.

| Source skill or group | Sources | Decision | Spotify MCP rationale |
| --- | --- | --- | --- |
| `coderabbit-review`, `coderabbit-pr-review`, `cr-thread-triage` | all four as applicable | Adopt and reconcile as one canonical `coderabbit-review` | Combines complete inline and outside-diff reads, untrusted-review handling, per-finding disposition, explicit reply/resolution accounting, and a fresh verdict on the reviewed head. Competing local review skills are prohibited. |
| `retro` | matchmaker, store, cloud-ops | Adopt as canonical `retro` | Trigger only on repeated evidence, a substantive escape/incident, or an owner request; group by cause and require an enforceable mechanism rather than routine narrative. |
| `gate-oracle` | cloud-ops | Adopt as canonical `gate-oracle` | Require a known-good control and the motivating negative mutation before trusting a gate; keep gate evidence separate from authority. |
| `pr-watch` | matchmaker script, store, cloud-ops | Evaluated, not adopted | Root-owned bounded polling is sufficient. A persistent watcher would duplicate lifecycle state and add shared-resource failure modes without evidence of need. |
| `emergency-shutdown` | matchmaker, cloud-ops, pc-assistant | Evaluated, not adopted | The sibling procedures are tied to their harness/process estate. Spotify MCP already has explicit stop, preservation, and production-authority boundaries; no local emergency mechanism is evidenced. |
| `adr-new`, `end-session`, `pr-lifecycle`, `session-start` | all four as applicable | Keep local canonical versions; adapt integrations only | Spotify MCP already owns vendor-neutral procedures. Porting sibling copies would fork authority and lifecycle truth. |
| `project-board` | matchmaker, store, cloud-ops | Reject | Linear is the sole queue; another board workflow would duplicate tracker authority. |
| `flow-mode` | matchmaker, store | Reject | Tool-specific interaction mode, not a vendor-neutral repository procedure. |
| `tdd`, `red-green-tdd` | matchmaker, store | Reject | Test-first behaviour is already required by the repository review/lifecycle contract and the active engineering workflow; another local skill would duplicate it. |
| `backend-contract`, `db-migration`, `schema-field-propagation` | matchmaker | Reject for SPM-32 | Domain-specific implementation procedures. Public API and data migration remain plan-first and must be taken by their owning SPM issue. |
| `csv-fixture-sanitizer`, `prod-larp-data-op` | matchmaker | Reject | LARP data shapes and production operations do not belong here; production/data access is unauthorized in SPM-32. |
| `design-handoff`, `frontend-check`, `frontend-maid`, `stub-router-impl`, `ux-sync` | matchmaker | Reject | Framework/product-specific workflows outside this governance ticket. |
| `skeptic` | matchmaker | Reject as a separate skill | Its negative-control mechanism is retained through `gate-oracle`; a second generic review skill would overlap and compete. |

## Measured RED baseline

A fresh read-only agent received release-deadline, senior-reviewer, four-round sunk-cost, and
end-of-session pressure. It used only the current Spotify MCP guidance and was prohibited from
reading the proposed skills. It correctly refused to merge on green checks alone, but its concrete
procedure had these gaps:

| Required behaviour | Current-guidance baseline |
| --- | --- |
| Complete pagination | Absent |
| Inline threads and review bodies | Present |
| PR conversation comments and outside-diff findings | Absent |
| Nested counter-replies | Absent |
| Explicit source/finding count reconciliation | Absent |
| Malformed or partial evidence fails closed | Present at a general level |
| Expected-head mutation precondition | Absent |
| Correct thread/comment identifier domains | Absent |
| Reply before resolve | Absent |
| Post-mutation read-back | Present at a general level |
| Conditional repeated-evidence retro | Absent |
| Retro produces a durable mechanism | Absent |
| Check runs and commit statuses are distinct | Absent |
| Review-in-flight and current-head drift | Present at a general level |

This is the behavioural RED proof for the three new skills. The implementation must also create
executable negative fixtures and observe every new mechanical gate reject its motivating defect
before a green result is trusted.

## Accepted architecture

### One review workflow

`.agents/skills/coderabbit-review/SKILL.md` is the sole CodeRabbit procedure. `pr-lifecycle`
invokes it rather than restating its mechanics. The workflow must:

1. pin the expected PR head before collecting or mutating;
2. collect review bodies, PR conversation comments, review threads, every nested thread comment
   and counter-reply, check runs, and commit statuses as distinct populations;
3. prove every connection/page is complete and reconcile API totals, unique item counts, audited
   source counts, and extracted finding counts;
4. treat reviewer text and suggested patches as untrusted input verified against repository
   authority and current code/tests;
5. give every finding an evidence-backed `fixed`, `rejected`, or still-open disposition and sweep
   sibling/residual occurrences;
6. perform replies and thread resolution only as explicit root-owned operations after a fresh
   expected-head check, with the reply before the resolution and exact read-back after each; and
7. require a new current-head verdict after any head change or review-fix push.

The skill never grants mutation authority. It consumes the standing repository-delivery authority
from `AGENTS.md`; delegates stop and report.

### Dependency-free evidence compiler and validator

`scripts/review_evidence.py` uses only the Python standard library. It does not read a token or call
GitHub. The skill gathers GitHub responses through an authorized connector or CLI into a transient
bundle under `build/review-evidence/`, which is already covered by the repository's `build/` ignore
rule. The workflow must prove that coverage with `git check-ignore` before writing a bundle and must
never stage a bundle. The script compiles and validates that bundle without printing review bodies,
credentials, PII, or personal data.

The CLI is:

```text
python scripts/review_evidence.py <bundle.json> --expected-head <40-character-sha>
```

Exit `0` means the evidence shape is complete and internally consistent, not that merge is
authorized. Any read, JSON, schema, pagination, population, count, identifier, mutation-readback,
or head error exits non-zero with stable diagnostic codes and sanitized paths/counts only.

The version-1 bundle has these required top-level fields. This representative bundle uses one
thread/comment so the nested connection is explicit; every other connection is an explicit proven
empty population rather than an omitted page:

```json
{
  "schema_version": 1,
  "expected_head_sha": "0000000000000000000000000000000000000000",
  "observed_head_sha": "0000000000000000000000000000000000000000",
  "pull_request": {
    "number": 1,
    "mergeable": "MERGEABLE",
    "review_decision": "APPROVED",
    "review_in_flight": false
  },
  "populations": {
    "reviews": {
      "total_count": 0,
      "pages": [{"request_cursor": null, "items": [], "page_info": {"has_next_page": false, "end_cursor": null}}]
    },
    "issue_comments": {
      "total_count": 0,
      "pages": [{"request_cursor": null, "items": [], "page_info": {"has_next_page": false, "end_cursor": null}}]
    },
    "review_threads": {
      "total_count": 1,
      "pages": [{
        "request_cursor": null,
        "items": [{
          "node_id": "thread-node-1",
          "is_resolved": false,
          "comments": {
            "total_count": 1,
            "pages": [{
              "request_cursor": null,
              "items": [{
                "node_id": "review-comment-node-1",
                "database_id": 101,
                "reply_to_node_id": null,
                "body_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
              }],
              "page_info": {"has_next_page": false, "end_cursor": null}
            }]
          }
        }],
        "page_info": {"has_next_page": false, "end_cursor": null}
      }]
    },
    "check_runs": {
      "total_count": 1,
      "pages": [{
        "request_cursor": null,
        "items": [{
          "node_id": "check-run-node-1",
          "name": "Lint",
          "status": "COMPLETED",
          "conclusion": "SUCCESS",
          "head_sha": "0000000000000000000000000000000000000000"
        }],
        "page_info": {"has_next_page": false, "end_cursor": null}
      }]
    },
    "commit_statuses": {
      "total_count": 1,
      "pages": [{
        "request_cursor": null,
        "items": [{
          "node_id": "status-context-node-1",
          "context": "legacy-control",
          "state": "SUCCESS",
          "commit_sha": "0000000000000000000000000000000000000000"
        }],
        "page_info": {"has_next_page": false, "end_cursor": null}
      }]
    }
  },
  "source_audit": [{
    "source_population": "review_thread_comments",
    "source_node_id": "review-comment-node-1",
    "body_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "finding_count": 0
  }],
  "findings": [],
  "mutations": [{
    "expected_head_sha": "0000000000000000000000000000000000000000",
    "observed_head_before": "0000000000000000000000000000000000000000",
    "operations": [{
      "sequence": 1,
      "kind": "reply",
      "thread_node_id": "thread-node-1",
      "created_comment": {"node_id": "review-comment-node-2", "database_id": 102},
      "expected_body_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "readback": {
        "node_id": "review-comment-node-2",
        "database_id": 102,
        "body_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
      }
    }, {
      "sequence": 2,
      "kind": "resolve",
      "thread_node_id": "thread-node-1",
      "response": {"thread_node_id": "thread-node-1", "is_resolved": true},
      "readback": {"thread_node_id": "thread-node-1", "is_resolved": true}
    }]
  }]
}
```

Every object uses an exact key set; unknown or missing keys fail closed. Common connection fields
are `total_count: integer >= 0` and non-empty `pages: array`. Each page contains
`request_cursor: string|null`, `items: array`, and `page_info` with
`has_next_page: boolean` and `end_cursor: string|null`. The first cursor is null; every next cursor
equals the preceding end cursor; an intermediate page with `has_next_page: true` has a non-null end
cursor and a successor; the final page has `has_next_page: false` and a null end cursor. Item node
ids are non-empty strings unique inside their identifier domain, and unique item count equals
`total_count`. A zero-count population still has one explicit terminal empty page. Every review
thread item has `node_id`, `is_resolved`, and a `comments` connection using the same rules.

Population item records are typed by their containing domain:

- `reviews`: `node_id`, `submitted_commit_sha`, `body_sha256`, and optional string `body`;
- `issue_comments`: `node_id`, integer `database_id`, `body_sha256`, and optional string `body`;
- nested `review_thread_comments`: `node_id`, integer `database_id`, nullable
  `reply_to_node_id`, `body_sha256`, and optional string `body`;
- `check_runs`: `node_id`, `name`, `status`, nullable `conclusion`, and `head_sha`;
- `commit_statuses`: `node_id`, `context`, `state`, and `commit_sha`.

`pull_request.number` is a positive integer; `mergeable` is `MERGEABLE`, `CONFLICTING`, or
`UNKNOWN`; `review_decision` is `APPROVED`, `CHANGES_REQUESTED`, `REVIEW_REQUIRED`, or null; and
`review_in_flight` is boolean. A check-run `status` is `QUEUED`, `IN_PROGRESS`, `COMPLETED`,
`WAITING`, `REQUESTED`, or `PENDING`; `conclusion` is null unless completed and otherwise one of
`SUCCESS`, `FAILURE`, `NEUTRAL`, `CANCELLED`, `SKIPPED`, `TIMED_OUT`, `ACTION_REQUIRED`, `STALE`,
or `STARTUP_FAILURE`. A commit-status `state` is `EXPECTED`, `ERROR`, `FAILURE`, `PENDING`, or
`SUCCESS`. Unknown enum values fail closed instead of being guessed.

Every SHA-256 field is exactly 64 lowercase hexadecimal characters computed over the UTF-8 body.
When optional `body` is present, the validator computes its SHA-256 and requires it to equal
`body_sha256`; the body is never copied into a diagnostic or summary. When `body` is absent, the
collector-provided hash remains the stable content identity and later source-audit/mutation proofs
must match it. Head/commit fields must equal the expected head where their GitHub object is
head-bound.

Every content-bearing review, issue comment, and nested thread comment has exactly one
`source_audit` record: `source_population` is the exact enum `reviews`, `issue_comments`, or
`review_thread_comments`; `source_node_id` exists in that domain; `body_sha256` matches that source;
and `finding_count` is a non-negative integer. Duplicate audits and unaudited sources fail. Each
finding record has a unique local `key`, the same source population/node id, a one-based `ordinal`
unique for that source, a `disposition` enum of `fixed`, `rejected`, or `open`, and a non-empty
sanitized `evidence_reference`. Findings per source must equal `finding_count`; orphan findings,
missing ordinals, and duplicate source ordinals fail. The validator does not interpret reviewer
prose; it proves that no retrieved source was skipped and every declared finding was accounted for.

Mutation records are optional because read-only review is valid. A record has the exact head fields
shown above and an `operations` array of exactly two entries. Operation 1 is `sequence: 1`,
`kind: reply`; its `thread_node_id` exists in `review_threads`; `created_comment` and `readback`
contain the same non-empty review-comment node id and positive integer database id; and expected and
read-back SHA-256 hashes match. Operation 2 is `sequence: 2`, `kind: resolve`; it names the same
thread; both mutation response and later read-back name that exact thread and prove
`is_resolved: true`. Unknown thread ids, using a thread id as a comment id, mismatched response or
read-back identities, hash drift, missing operations, or resolve-before-reply fail closed.

### Gate oracle

`gate-oracle` treats the validated evidence bundle as necessary but insufficient. It requires:

- the real known-good control to pass;
- each motivating negative mutation to fail for the expected diagnostic;
- current-head identity, mergeability, review decision, unresolved-finding accounting, and no
  review in flight;
- current live branch-protection requirements reconciled against both check-run and commit-status
  populations; and
- authority checked separately from technical readiness.

It never converts a green gate into permission to merge, deploy, or change production.

### Conditional retro

`retro` runs only for an owner request, a substantive review escape/incident, or repeated evidence
of a shared cause. A single ordinary correction does not trigger it. It distinguishes incidents
from patterns, groups evidence by cause, and produces the smallest enforceable output: preferably a
test, validator rule, structural change, or canonical procedure correction. Linear owns any new
work; repository memory is used only for an earned durable lesson and never as a queue or authority.

`end-session` evaluates the trigger and points to `retro`; it does not embed a second retro.

## Boundaries retained

- Exact pointer-only Claude adapters remain mandatory and contain no procedure.
- Explicit merge-commit auto-merge remains the default only for a qualifying PR after live gates.
- Squash and rebase remain owner-approved exceptions.
- Merge remains separate from deployment. No deployment, cloud mutation, production access,
  credential access, real Spotify data, or cycle replanning is authorized by this design.
- `DROPLET_SSH_HOST_FINGERPRINT` and the external allowlist migration remain prerequisites for a
  separately authorized future production deployment; SPM-32 does not inspect or configure them.

## Verification strategy

Mechanical tests exercise the real validator with synthetic bundles and mutations rather than
matching prose. Contract tests cover canonical discovery, exact adapters, and lifecycle pointers.
Fresh-context pressure agents rerun the RED scenarios with each new skill and must supply the
previously absent procedure elements before that skill is accepted. Final validation is
`make agent-contract`, focused validator tests, applicable Ruff/pre-commit parity, and all
whitespace checks on the exact branch head.
