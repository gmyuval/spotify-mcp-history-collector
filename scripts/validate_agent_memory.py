"""Dependency-free validation for repository-owned durable agent memory."""

import re
import stat
import sys
from pathlib import Path

MEMORY_RELATIVE = Path("docs/agent/memory")
README_RELATIVE = MEMORY_RELATIVE / "README.md"
KEBAB_MARKDOWN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\.md")
MARKDOWN_LINK = re.compile(r"\[[^\]\n]+\]\(([^)\n]+)\)")
ENTRY_SCHEMA = re.compile(
    r"\A# [^\n]+\n"
    r"- Date: \d{4}-\d{2}-\d{2}\n"
    r"- Evidence: \S[^\n]*\n"
    r"- Affected surface: \S[^\n]*\n"
    r"\n## Measured\n(\S(?:.*?\S)?)\n"
    r"\n## Inference\n(\S(?:.*?\S)?)\n"
    r"\n## Revisit when\n(\S(?:.*?\S)?)\n?\Z",
    re.DOTALL,
)
WINDOWS_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)


def _diagnostic(code: str, path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = README_RELATIVE
    return f"{code}: {relative.as_posix()}"


def _is_reparse_point(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    return stat.S_ISLNK(metadata.st_mode) or bool(getattr(metadata, "st_file_attributes", 0) & WINDOWS_REPARSE_POINT)


def _has_reparse_component(path: Path, boundary: Path) -> bool:
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


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    except OSError, UnicodeError:
        return None


def _index_body(readme: str) -> str | None:
    heading = re.search(r"^## Index[ \t]*$", readme, re.MULTILINE)
    if heading is None:
        return None
    following = readme[heading.end() :]
    next_heading = re.search(r"^## [^\n]+$", following, re.MULTILINE)
    return following if next_heading is None else following[: next_heading.start()]


def _entry_has_schema(text: str) -> bool:
    if len(re.findall(r"^# [^\n]+$", text, re.MULTILINE)) != 1:
        return False
    if re.findall(r"^## [^\n]+$", text, re.MULTILINE) != [
        "## Measured",
        "## Inference",
        "## Revisit when",
    ]:
        return False
    return ENTRY_SCHEMA.fullmatch(text) is not None


def validate_memory(root: Path) -> list[str]:
    """Return sanitized, fail-closed findings for the repository memory tree."""

    root = root.absolute()
    memory = root / MEMORY_RELATIVE
    readme_path = root / README_RELATIVE
    if _has_reparse_component(memory, root):
        return [_diagnostic("MEMORY_INDEX_LINK_INVALID", readme_path, root)]
    readme = _read(readme_path)
    if readme is None:
        return [_diagnostic("MEMORY_INDEX_LINK_MISSING", readme_path, root)]

    index = _index_body(readme)
    if index is None:
        return [_diagnostic("MEMORY_INDEX_LINK_INVALID", readme_path, root)]

    issues: list[str] = []
    indexed: dict[Path, int] = {}
    blocked_entries: set[Path] = set()
    for raw_target in MARKDOWN_LINK.findall(index):
        windows_absolute = re.match(r"^[A-Za-z]:[\\/]", raw_target) is not None
        target_path = Path(raw_target)
        if windows_absolute or target_path.is_absolute():
            issues.append(_diagnostic("MEMORY_INDEX_LINK_INVALID", readme_path, root))
            continue

        candidate = memory / target_path
        if _has_reparse_component(candidate, memory):
            issues.append(_diagnostic("MEMORY_INDEX_LINK_INVALID", candidate, root))
            blocked_entries.add(candidate)
            continue

        resolved_candidate = candidate.resolve()
        try:
            resolved_candidate.relative_to(memory)
        except ValueError:
            issues.append(_diagnostic("MEMORY_INDEX_LINK_INVALID", readme_path, root))
            continue
        if resolved_candidate.parent != memory or resolved_candidate.name == "README.md":
            issues.append(_diagnostic("MEMORY_INDEX_LINK_INVALID", readme_path, root))
            continue

        indexed[resolved_candidate] = indexed.get(resolved_candidate, 0) + 1

    for candidate, count in sorted(indexed.items(), key=lambda item: item[0].as_posix()):
        if count != 1:
            issues.append(_diagnostic("MEMORY_INDEX_LINK_INVALID", candidate, root))
        if not candidate.is_file():
            issues.append(_diagnostic("MEMORY_INDEX_LINK_MISSING", candidate, root))

    try:
        entries = sorted(
            (path for path in memory.glob("*.md") if path.name != "README.md"),
            key=lambda path: path.as_posix(),
        )
    except OSError:
        entries = []

    for entry in entries:
        if _has_reparse_component(entry, memory):
            if entry not in blocked_entries:
                issues.append(_diagnostic("MEMORY_INDEX_LINK_INVALID", entry, root))
            continue
        if entry not in indexed:
            issues.append(_diagnostic("MEMORY_ENTRY_UNINDEXED", entry, root))
        if KEBAB_MARKDOWN.fullmatch(entry.name) is None:
            issues.append(_diagnostic("MEMORY_ENTRY_FILENAME", entry, root))
        text = _read(entry)
        if text is None or not _entry_has_schema(text):
            issues.append(_diagnostic("MEMORY_ENTRY_SCHEMA", entry, root))

    return issues


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) == 2 else Path(__file__).resolve().parents[1]
    issues = validate_memory(root)
    if issues:
        for issue in issues:
            print(issue)
        return 1
    topic_count = sum(path.name != "README.md" for path in (root / MEMORY_RELATIVE).glob("*.md"))
    print(f"Memory contract OK ({topic_count} indexed topic{'s' if topic_count != 1 else ''}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
