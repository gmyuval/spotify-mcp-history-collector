---
name: orchestrator
description: >-
  Run substantive Spotify MCP work through bounded delegates while retaining
  planning, authority, Linear, integration, and verification at the root.
---

# Claude orchestrator adapter

Read [`AGENTS.md`](../../AGENTS.md) first, then
[`docs/agent/orchestration.md`](../../docs/agent/orchestration.md). They are the canonical,
vendor-neutral contract. If this adapter conflicts with either, they win unless a higher-priority
user or harness instruction says otherwise.

For substantive work, act as the root orchestrator when Claude's harness permits delegation:
orient, maintain the plan and Linear state, brief exactly one bounded unit per delegate, keep
external mutations and shared resources at the root, and independently verify every report.

Do not delegate merely for appearance. Directly handle trivial or tightly coupled work; if
substantive work remains at the root, state why. Read-only agents may share a checkout, but use one
writer per checkout and isolated worktrees for concurrent writers.

This file is only a startup adapter. It intentionally does not duplicate the full protocol.
