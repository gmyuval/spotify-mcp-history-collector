"""Dependency-free validation for the vendor-neutral agent contract."""

import re
import stat
import sys
from pathlib import Path

EXPECTED_SKILLS = frozenset({"adr-new", "coderabbit-review", "end-session", "pr-lifecycle", "session-start"})
PR_LIFECYCLE_MERGE_POLICY_TERMS = (
    "invoke the github merge operation with the `merge` method explicitly",
    "`merge` is this repository's default pull-request strategy",
    "squash and rebase remain enabled as explicit alternatives",
    "if an agent proposes either exception, it must prompt the owner with the requested method and rationale",
    # Enforce approval independently from the preceding owner-prompt requirement.
    "then obtain explicit approval before using it",
    "required linear history",
    "never mutate repository merge settings or branch protection",
)
REQUIRED_FILES = (
    "AGENTS.md",
    "CLAUDE.md",
    ".claude/agents/orchestrator.md",
    "docs/agent/orchestration.md",
    "docs/agent/current-state.md",
    "docs/agent/task-template.md",
    "docs/agent/review-checklist.md",
    "docs/agent/tool-policy.md",
    "docs/agent/memory/README.md",
    "docs/decisions/README.md",
    "docs/decisions/template.md",
)
EXPECTED_CLAUDE_ADAPTER = """# CLAUDE.md

This is the thin Claude Code adapter for this repository. Read [AGENTS.md](AGENTS.md) first;
it is the canonical, vendor-neutral operating contract and wins if this file conflicts with it.

Read [docs/agent/orchestration.md](docs/agent/orchestration.md) before delegating substantive work,
and use [.claude/agents/orchestrator.md](.claude/agents/orchestrator.md) as Claude's startup adapter.

Canonical project skills live under [.agents/skills/](.agents/skills/). Files under
[.claude/skills/](.claude/skills/) exist only for Claude Code discovery and point to those bodies.

For orientation, read [docs/agent/current-state.md](docs/agent/current-state.md),
[docs/agent/tool-policy.md](docs/agent/tool-policy.md), and the relevant accepted decisions under
[docs/decisions/](docs/decisions/). Linear team SPM remains the planning source of truth.
"""
WINDOWS_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)


def _issue(code: str, detail: str) -> str:
    return f"{code}: {detail}"


def _normalise(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _is_reparse_point(path: Path) -> bool:
    """Detect symlinks and Windows junctions without following them."""

    try:
        metadata = path.lstat()
    except OSError:
        return False
    return stat.S_ISLNK(metadata.st_mode) or bool(getattr(metadata, "st_file_attributes", 0) & WINDOWS_REPARSE_POINT)


def _has_reparse_component(path: Path, boundary: Path) -> bool:
    """Reject a reparse point at or below the repository boundary."""

    try:
        path.relative_to(boundary)
    except ValueError:
        return True
    current = path
    while True:
        if _is_reparse_point(current):
            return True
        if current == boundary:
            return False
        current = current.parent


def _read_text(path: Path, code: str, issues: list[str]) -> str | None:
    try:
        return _normalise(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        issues.append(_issue(code, f"{path}: {exc}"))
        return None


def _frontmatter(text: str, path: Path, issues: list[str]) -> tuple[str, str] | None:
    if not text.startswith("---\n"):
        issues.append(_issue("SKILL_FRONTMATTER_INVALID", f"{path}: missing opening delimiter"))
        return None
    closing = text.find("\n---\n", 4)
    if closing < 0:
        issues.append(_issue("SKILL_FRONTMATTER_INVALID", f"{path}: missing closing delimiter"))
        return None
    return text[: closing + 4], text[closing + 5 :]


def _frontmatter_name(frontmatter: str, path: Path, issues: list[str]) -> str | None:
    """Accept only the non-behavioral name/description schema used by project skills."""

    lines = frontmatter.splitlines()
    valid_shape = (
        len(lines) >= 5
        and lines[0] == "---"
        and lines[-1] == "---"
        and re.fullmatch(r"name: ([a-z0-9-]+)", lines[1]) is not None
        and lines[2] == "description: >-"
        and all(line.startswith("  ") and line.strip() for line in lines[3:-1])
    )
    if not valid_shape:
        issues.append(
            _issue(
                "SKILL_FRONTMATTER_SCHEMA",
                f"{path}: expected exactly one name and one folded description",
            )
        )
        return None
    match = re.fullmatch(r"name: ([a-z0-9-]+)", lines[1])
    assert match is not None
    return match.group(1)


def _expected_adapter(frontmatter: str, name: str) -> str:
    pointer = (
        f"Read [../../../.agents/skills/{name}/SKILL.md]"
        f"(../../../.agents/skills/{name}/SKILL.md) completely and follow it. "
        "That file is the canonical skill; this file only provides Claude Code discovery."
    )
    return f"{frontmatter}\n# Claude Code adapter\n\n{pointer}\n"


def _entry_names(path: Path, code: str, issues: list[str]) -> set[str] | None:
    try:
        return {entry.name for entry in path.iterdir()}
    except OSError as exc:
        issues.append(_issue(code, f"{path}: {exc}"))
        return None


def _validate_root(skill_root: Path, repository_root: Path, label: str, issues: list[str]) -> set[str] | None:
    if _has_reparse_component(skill_root, repository_root):
        issues.append(_issue("SKILL_REPARSE_POINT", f"{label} root: {skill_root}"))
        return None
    if not skill_root.is_dir():
        issues.append(_issue(f"SKILL_{label}_ROOT_UNREADABLE", f"missing directory: {skill_root}"))
        return None
    names = _entry_names(skill_root, f"SKILL_{label}_ROOT_UNREADABLE", issues)
    if names is None:
        return None

    missing = sorted(EXPECTED_SKILLS - names)
    extra = sorted(names - EXPECTED_SKILLS)
    if missing:
        issues.append(_issue(f"SKILL_{label}_MISSING", ", ".join(missing)))
    if extra:
        issues.append(_issue(f"SKILL_{label}_UNDECLARED", ", ".join(extra)))
    return names


def validate_skill_layout(root: Path) -> list[str]:
    """Return fail-closed skill-layout findings for a repository root."""

    issues: list[str] = []
    canonical_root = root / ".agents" / "skills"
    adapter_root = root / ".claude" / "skills"
    canonical_names = _validate_root(canonical_root, root, "CANONICAL", issues)
    adapter_names = _validate_root(adapter_root, root, "ADAPTER", issues)

    for name in sorted(EXPECTED_SKILLS):
        canonical_dir = canonical_root / name
        adapter_dir = adapter_root / name
        if canonical_names is None or name not in canonical_names:
            continue
        if _has_reparse_component(canonical_dir, root) or not canonical_dir.is_dir():
            issues.append(_issue("SKILL_REPARSE_POINT", f"invalid canonical directory: {canonical_dir}"))
            continue

        canonical_children = _entry_names(canonical_dir, "SKILL_CANONICAL_UNREADABLE", issues)
        if canonical_children is None:
            continue
        if canonical_children != {"SKILL.md"}:
            issues.append(_issue("SKILL_CANONICAL_EXTRA_ENTRY", f"{name}: {sorted(canonical_children)}"))
        canonical_path = canonical_dir / "SKILL.md"
        if _has_reparse_component(canonical_path, root) or not canonical_path.is_file():
            issues.append(_issue("SKILL_REPARSE_POINT", f"invalid canonical file: {canonical_path}"))
            continue
        canonical_text = _read_text(canonical_path, "SKILL_CANONICAL_UNREADABLE", issues)
        if canonical_text is None:
            continue
        canonical_parts = _frontmatter(canonical_text, canonical_path, issues)
        if canonical_parts is None:
            continue
        canonical_frontmatter, canonical_body = canonical_parts

        declared_name = _frontmatter_name(canonical_frontmatter, canonical_path, issues)
        if declared_name is None:
            continue
        if declared_name != name:
            issues.append(_issue("SKILL_NAME_MISMATCH", f"{canonical_path}: expected {name}"))
        if not canonical_body.strip():
            issues.append(_issue("SKILL_CANONICAL_BODY_EMPTY", str(canonical_path)))

        if adapter_names is None or name not in adapter_names:
            continue
        if _has_reparse_component(adapter_dir, root) or not adapter_dir.is_dir():
            issues.append(_issue("SKILL_REPARSE_POINT", f"invalid adapter directory: {adapter_dir}"))
            continue
        adapter_children = _entry_names(adapter_dir, "SKILL_ADAPTER_UNREADABLE", issues)
        if adapter_children is None:
            continue
        if adapter_children != {"SKILL.md"}:
            issues.append(_issue("SKILL_ADAPTER_BODY_NOT_THIN", f"{name}: {sorted(adapter_children)}"))
        adapter_path = adapter_dir / "SKILL.md"
        if _has_reparse_component(adapter_path, root) or not adapter_path.is_file():
            issues.append(_issue("SKILL_REPARSE_POINT", f"invalid adapter file: {adapter_path}"))
            continue
        adapter_text = _read_text(adapter_path, "SKILL_ADAPTER_UNREADABLE", issues)
        if adapter_text is None:
            continue
        adapter_parts = _frontmatter(adapter_text, adapter_path, issues)
        if adapter_parts is None:
            continue
        adapter_frontmatter, _ = adapter_parts
        if adapter_frontmatter != canonical_frontmatter:
            issues.append(_issue("SKILL_ADAPTER_FRONTMATTER_DRIFT", name))
            continue
        expected = _expected_adapter(canonical_frontmatter, name)
        if adapter_text != expected:
            issues.append(_issue("SKILL_ADAPTER_BODY_NOT_THIN", name))

    return issues


def validate_contract(root: Path) -> list[str]:
    """Return all repository agent-contract findings."""

    issues = validate_skill_layout(root)
    for relative_path in REQUIRED_FILES:
        path = root / relative_path
        if _has_reparse_component(path, root) or not path.is_file():
            issues.append(_issue("AGENT_CONTRACT_FILE_MISSING", relative_path))
            continue
        text = _read_text(path, "AGENT_CONTRACT_FILE_UNREADABLE", issues)
        if text is not None and not text.strip():
            issues.append(_issue("AGENT_CONTRACT_FILE_EMPTY", relative_path))

    lifecycle_path = root / ".agents" / "skills" / "pr-lifecycle" / "SKILL.md"
    lifecycle = _read_text(lifecycle_path, "SKILL_CANONICAL_UNREADABLE", issues)
    if lifecycle is not None:
        normalized_lifecycle = " ".join(lifecycle.lower().split())
        missing_policy_terms = [term for term in PR_LIFECYCLE_MERGE_POLICY_TERMS if term not in normalized_lifecycle]
        if missing_policy_terms:
            issues.append(
                _issue(
                    "PR_LIFECYCLE_MERGE_POLICY",
                    f"missing terms: {', '.join(missing_policy_terms)}",
                )
            )
    claude_path = root / "CLAUDE.md"
    claude = _read_text(claude_path, "CLAUDE_ADAPTER_UNREADABLE", issues)
    if claude is not None:
        if claude != EXPECTED_CLAUDE_ADAPTER:
            issues.append(_issue("CLAUDE_ADAPTER_DRIFT", "CLAUDE.md is not the exact thin adapter"))

    return issues


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    issues = validate_contract(root)
    if issues:
        for issue in issues:
            print(issue)
        return 1
    print(f"Agent contract OK ({len(EXPECTED_SKILLS)} canonical skills, {len(EXPECTED_SKILLS)} exact Claude adapters).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
