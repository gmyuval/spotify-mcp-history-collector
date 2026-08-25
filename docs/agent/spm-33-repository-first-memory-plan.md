# SPM-33 Repository-First Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a reviewed repository-first memory model, thin tool-local boundary, migration
inventory, and dependency-free enforcement for SPM-33.

**Architecture:** `docs/agent/memory/README.md` owns the repository index and entry schema;
`scripts/validate_agent_memory.py` validates that schema plus required policy pointers. Canonical
policy lives in `AGENTS.md`; tool and lifecycle surfaces point to it without duplicating the full
procedure. A root-only platform memory update note establishes the Codex-local pointer only after
the issue-linked PR is merged and GitHub, Linear, and `main` are read back.

**Tech Stack:** Python 3.14 standard library, `unittest`, Markdown, GNU Make compatibility target.

**Spec:** `docs/agent/spm-33-repository-first-memory-design.md`

## Global Constraints

- Linear SPM-33 is the only primary issue; the branch and pull request name only SPM-33.
- Repository memory is context, never authority; Linear remains the sole work tracker.
- Tool-local memory is repository pointer plus genuinely transient or personal bookmarks only.
- Do not commit machine-specific executable paths or private tool-local source content.
- Exclude credentials, tokens, production identifiers, Spotify/account data, email addresses,
  database content, raw diagnostics, and other PII.
- Keep canonical procedure in `AGENTS.md` and `.agents/skills/`; keep Claude adapters thin.
- Every validator diagnostic contains only a repository-relative path and rule/category.
- Use the issue-supplied pinned uv 0.12.3 binary first on PATH; keep its absolute path out of Git.
- One writer uses the isolated SPM-33 worktree; delegates do not mutate GitHub, Linear, or memory.
- Delegates stop with an uncommitted STOP 1 report; only the root stages explicit paths and commits
  after independent verification. Standing repository-delivery authority never passes to a delegate.
- Do not deploy, access production/cloud/credentials/Spotify data, alter cycle scope, or broaden
  repository-delivery authority.

---

## Root-owned per-task commit protocol

Before Task 1, the root independently reviews, stages, and commits this design and plan as the
planning baseline. For every implementation task, the delegate edits and validates but does not
stage or commit. The root then verifies the real worktree diff and reported tests, stages only the
task's named paths, commits with the task's stated subject, builds the fixed-base review package,
and dispatches the task reviewer. Review fixes follow the same delegate STOP 1 -> root verify ->
root commit -> scoped re-review sequence.

### Task 1: Migration inventory, repository entry, and memory index validator

**Files:**
- Create: `scripts/validate_agent_memory.py`
- Create: `docs/agent/spm-33-memory-migration-inventory.md`
- Create: `docs/agent/memory/windows-pinned-uv-validation.md`
- Modify: `docs/agent/memory/README.md`
- Modify: `tests/contracts/test_agent_contract.py`
- Modify: `Makefile`

**Interfaces:**
- Produces: `validate_memory(root: Path) -> list[str]` and a CLI that accepts an optional repository
  root, prints sanitized findings, and exits `0` only for a valid memory tree.
- Produces: diagnostics `MEMORY_INDEX_LINK_MISSING`, `MEMORY_ENTRY_UNINDEXED`,
  `MEMORY_ENTRY_FILENAME`, `MEMORY_ENTRY_SCHEMA`, and `MEMORY_INDEX_LINK_INVALID`.
- Produces: a conclusion-oriented README index and one schema-valid durable entry.
- Consumes: the SPM-33 design classification and the existing dependency-free test fixture style.

- [ ] **Step 1: Write the failing control and mutation tests**

  Add a subprocess helper that invokes `scripts/validate_agent_memory.py` with the test interpreter.
  Add a live-control test requiring exit `0`. Add table-driven temporary-tree mutants for every
  fail-closed rule: unindexed topic; missing target; absolute/escaping path; README target; duplicate
  index path; non-kebab topic filename; duplicate H1 conclusion; and each missing or malformed
  schema field/section. Require the exact sanitized diagnostic for every mutant.

- [ ] **Step 2: Run the focused tests and observe RED**

  Run:
  `uv run --locked python -m unittest tests.contracts.test_agent_contract.AgentContractTests.test_live_memory_contract_passes_validator tests.contracts.test_agent_contract.AgentContractTests.test_memory_index_mutations_fail_closed`

  Expected RED: the live control fails because `scripts/validate_agent_memory.py` is absent; the
  failure must name the missing validator rather than a test typo.

- [ ] **Step 3: Implement the minimal validator**

  Implement `validate_memory(root: Path) -> list[str]` with standard-library `pathlib`, `re`, and
  `sys`. Parse only Markdown links under `## Index`. Resolve links without following paths outside
  `docs/agent/memory`, require one unique index link per topic, compare indexed topics to actual
  `*.md` files excluding `README.md`, and enforce this entry schema:

  ```text
  # <one conclusion>
  - Date: YYYY-MM-DD
  - Evidence: <non-empty primary evidence>
  - Affected surface: <non-empty surface>
  ## Measured
  <non-empty text>
  ## Inference
  <non-empty text or "None.">
  ## Revisit when
  <non-empty text>
  ```

  Keep diagnostics repository-relative and value-free. Add a CLI optional root argument for
  temporary mutation tests.

- [ ] **Step 4: Add the evidence-backed inventory and approved entry**

  Use only the design's sanitized migration snapshot; do not inspect private memory. Reproduce its
  complete candidate-group classification in the issue evidence inventory, with primary repository,
  Linear, PR, commit, or rollout-ID pins where available. Use the categories repository memory, ADR,
  Linear work, code/test/documentation truth, transient local bookmark, stale/incorrect, and
  sensitive and excluded. Do not paste private source text. Record why only the reproduced Windows
  uv lesson is graduated.

  Add `windows-pinned-uv-validation.md` with the exact schema. State the measured WindowsApps shim
  failure, uv 0.12.3, Python 3.14.7, the affected local validation surface, the inference that pinned
  uv is the reliable entrypoint on this host, and a revisit condition tied to Python discovery or
  repository toolchain changes. Add its conclusion-oriented README index link.

- [ ] **Step 5: Integrate the validator with Make**

  Add `memory-contract` to `.PHONY`; run
  `uv run --locked python scripts/validate_agent_memory.py` in that target; make `agent-contract`
  depend on both `uv-contract` and `memory-contract` without changing CI's existing command.

- [ ] **Step 6: Run GREEN and the task gate**

  Run the focused tests from Step 2, then `make agent-contract`, then
  `uv run --locked python scripts/validate_agent_memory.py`, and `git diff --check`.
  Expected GREEN: focused tests pass; the full dependency-free gate passes; the validator prints a
  sanitized success summary; whitespace check exits `0`.

- [ ] **Step 7: Stop for root verification and commit**

  Leave the six named files unstaged and report STOP 1 with RED/GREEN evidence. The root verifies,
  stages only those files, and commits:
  `feat(agent): validate repository memory index (SPM-33)`.

### Task 2: Canonical two-layer contract and thin tool adapter

**Files:**
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `docs/agent/tool-policy.md`
- Modify: `scripts/validate_agent_contract.py`
- Modify: `scripts/validate_agent_memory.py`
- Modify: `tests/contracts/test_agent_contract.py`

**Interfaces:**
- Consumes: `validate_memory(root)` from Task 1.
- Produces: canonical two-layer language in `AGENTS.md`, source-selection guidance in tool policy,
  and an exact thin Claude adapter that points to the repository index.
- Produces: fail-closed pointer diagnostics through `validate_memory` and exact Claude content
  through `validate_contract`.

- [ ] **Step 1: Write the failing cross-document and pointer mutation tests**

  Add a test that reads the three instruction surfaces and requires the repository index,
  repository-first retrieval, same-PR durable recording/correction, tool-local pointer-plus-
  transient boundary, authority hierarchy, and Linear-only queue. Add a temporary fixture mutation
  that removes the Claude repository-memory pointer and requires a specific validator diagnostic.

- [ ] **Step 2: Run the focused tests and observe RED**

  Run:
  `uv run --locked python -m unittest tests.contracts.test_agent_contract.AgentContractTests.test_repository_first_two_layer_memory_contract tests.contracts.test_agent_contract.AgentContractTests.test_memory_instruction_pointer_mutation_fails_closed`

  Expected RED: existing policy surfaces lack the complete two-layer and same-PR pointer contract.

- [ ] **Step 3: Implement the canonical and adapter changes**

  Add one `AGENTS.md` subsection that owns retrieval, admissibility, thin local memory, correction,
  and authority hierarchy. Update `tool-policy.md` to route durable/private memory through that
  canonical section. Keep `CLAUDE.md` at no more than 24 lines while adding the README pointer,
  relevant-indexed-entry orientation, same-PR durable recording, and Claude private-memory
  pointer/transient rule. Update `EXPECTED_CLAUDE_ADAPTER` exactly.

  Extend `validate_memory` with a small mapping of repository-relative instruction paths to
  behaviorally necessary pointer terms. Return `MEMORY_INSTRUCTION_POINTER` with only the relative
  path and missing concept label; do not print source text.

- [ ] **Step 4: Run GREEN and the task gate**

  Run the focused tests from Step 2, `make agent-contract`, the direct memory validator, and
  `git diff --check`. Expected GREEN: all commands exit `0` with no warning or unsanitized content.

- [ ] **Step 5: Stop for root verification and commit**

  Leave the six named files unstaged and report STOP 1 with RED/GREEN evidence. The root verifies,
  stages only those files, and commits:
  `docs(agent): define repository-first memory (SPM-33)`.

### Task 3: Session, pull-request, wind-down, and review integration

**Files:**
- Modify: `.agents/skills/session-start/SKILL.md`
- Modify: `.agents/skills/pr-lifecycle/SKILL.md`
- Modify: `.agents/skills/end-session/SKILL.md`
- Modify: `docs/agent/review-checklist.md`
- Modify: `scripts/validate_agent_memory.py`
- Modify: `tests/contracts/test_agent_contract.py`

**Interfaces:**
- Consumes: the canonical `AGENTS.md` two-layer contract and `validate_memory(root)`.
- Produces: lifecycle pointers that retrieve only relevant indexed entries, write only earned
  durable lessons in the same PR, remove landed transient bookmarks, and correct/delete stale
  repository entries rather than contradicting them privately.

- [ ] **Step 1: Write the failing lifecycle integration and mutation tests**

  Add a cross-document test requiring: session-start reads README before relevant entries;
  PR lifecycle evaluates memory affected by the change and uses the issue-linked PR for correction;
  end-session distinguishes earned durable updates from transient bookmarks and removes landed
  bookmarks; review guidance says memory is considered and updated only when earned. Add a fixture
  mutation that removes one lifecycle pointer and require `MEMORY_INSTRUCTION_POINTER`.

- [ ] **Step 2: Run the focused tests and observe RED**

  Run:
  `uv run --locked python -m unittest tests.contracts.test_agent_contract.AgentContractTests.test_memory_lifecycle_integration tests.contracts.test_agent_contract.AgentContractTests.test_memory_lifecycle_pointer_mutation_fails_closed`

  Expected RED: current lifecycle prose has partial memory references but lacks the full retrieval,
  correction, and transient-bookmark cleanup behavior.

- [ ] **Step 3: Implement minimal lifecycle pointers**

  Update each canonical skill with a short pointer to `docs/agent/memory/README.md` and the exact
  lifecycle behavior it owns. Do not copy the entire two-layer contract into a skill. Correct the
  review checklist's unconditional memory-update wording so a reviewer checks consideration,
  source-of-truth placement, earned updates, index integrity, and transient/private exclusion.
  Extend the validator's required-path concepts for these four surfaces.

- [ ] **Step 4: Run GREEN, fresh pressure, and the task gate**

  Run the focused tests from Step 2. Run a fresh control, then copy the worktree to a temporary
  contract fixture, remove one lifecycle pointer, require the exact non-zero diagnostic, discard
  the fixture, and rerun the restored control. Then run `make agent-contract`, the direct memory
  validator, and `git diff --check`.

- [ ] **Step 5: Stop for root verification and commit**

  Leave the six named files unstaged and report STOP 1 with RED/GREEN evidence. The root verifies,
  stages only those files, and commits:
  `docs(agent): integrate memory lifecycle (SPM-33)`.

## Root-owned integration actions after the three reviewed tasks

These are not delegated implementation tasks and never widen authority:

1. Independently verify every task diff, TDD evidence, focused gate, and per-task review.
2. Put pinned uv 0.12.3 first on PATH and run `make agent-contract`,
   `uv run --locked python scripts/validate_agent_memory.py`, `make lint`, `make typecheck`,
   `make precommit`, `git diff --check`, `git diff --cached --check`, and
   `git diff --check 99a58b5aec0b7e6e650d8c42f001dd15bdf1b1ab...HEAD`. Run a fresh memory
   control, each table-driven mutant, and the restored control. Generate a fixed-base package with
   the commit list, stat, and `git diff -U10 99a58b5aec0b7e6e650d8c42f001dd15bdf1b1ab...HEAD`;
   dispatch the final whole-branch review against that package.
3. Publish one `codex/spm-33-repository-first-memory` branch and one `SPM-33:` pull request, then
   follow `coderabbit-review`, `gate-oracle`, and the canonical merge method only if the PR qualifies.
4. Reconcile GitHub, Linear, and local `main`; require the merged repository index to be present on
   verified `main`. Never dispatch deployment or production.
5. Only after Step 4, re-check direct user/platform authority and use the Codex memory update-note
   mechanism to request a repository-index pointer and removal or graduation of duplicated/stale
   Spotify project shadow entries. Read the note back; do not write private source text into Git or
   the task transcript.
