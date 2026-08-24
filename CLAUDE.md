# CLAUDE.md

This is the thin Claude Code adapter for this repository. Read [AGENTS.md](AGENTS.md) first;
it is the canonical, vendor-neutral operating contract and wins if this file conflicts with it.

Read [docs/agent/orchestration.md](docs/agent/orchestration.md) before delegating substantive work,
and use [.claude/agents/orchestrator.md](.claude/agents/orchestrator.md) as Claude's startup adapter.

Canonical project skills live under [.agents/skills/](.agents/skills/). Files under
[.claude/skills/](.claude/skills/) exist only for Claude Code discovery and point to those bodies.

For orientation, read [docs/agent/current-state.md](docs/agent/current-state.md),
[docs/agent/tool-policy.md](docs/agent/tool-policy.md), and the relevant accepted decisions under
[docs/decisions/](docs/decisions/). Linear team SPM remains the planning source of truth.

For repository memory, read [docs/agent/memory/README.md](docs/agent/memory/README.md) first, then
only relevant indexed entries. Record or correct earned durable lessons in the same issue-linked
pull request. Keep Claude private memory to the repository pointer plus transient or personal
bookmarks only.
