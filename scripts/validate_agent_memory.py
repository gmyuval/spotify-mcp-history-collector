"""Dependency-free validation for repository-owned durable agent memory."""

import re
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


def _diagnostic(code: str, path: Path, root: Path) -> str:
    return f"{code}: {path.relative_to(root).as_posix()}"


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

    root = root.resolve()
    memory = root / MEMORY_RELATIVE
    readme_path = root / README_RELATIVE
    readme = _read(readme_path)
    if readme is None:
        return [_diagnostic("MEMORY_INDEX_LINK_MISSING", readme_path, root)]

    index = _index_body(readme)
    if index is None:
        return [_diagnostic("MEMORY_INDEX_LINK_INVALID", readme_path, root)]

    issues: list[str] = []
    indexed: dict[Path, int] = {}
    memory_boundary = memory.resolve()
    for raw_target in MARKDOWN_LINK.findall(index):
        windows_absolute = re.match(r"^[A-Za-z]:[\\/]", raw_target) is not None
        target_path = Path(raw_target)
        if windows_absolute or target_path.is_absolute():
            issues.append(_diagnostic("MEMORY_INDEX_LINK_INVALID", readme_path, root))
            continue

        candidate = (memory / target_path).resolve()
        try:
            candidate.relative_to(memory_boundary)
        except ValueError:
            issues.append(_diagnostic("MEMORY_INDEX_LINK_INVALID", readme_path, root))
            continue
        if candidate.parent != memory_boundary or candidate.name.casefold() == "readme.md":
            issues.append(_diagnostic("MEMORY_INDEX_LINK_INVALID", readme_path, root))
            continue

        indexed[candidate] = indexed.get(candidate, 0) + 1

    for candidate, count in sorted(indexed.items(), key=lambda item: item[0].as_posix()):
        if count != 1:
            issues.append(_diagnostic("MEMORY_INDEX_LINK_INVALID", candidate, root))
        if not candidate.is_file():
            issues.append(_diagnostic("MEMORY_INDEX_LINK_MISSING", candidate, root))

    try:
        entries = sorted(
            (path.resolve() for path in memory.glob("*.md") if path.name.casefold() != "readme.md"),
            key=lambda path: path.as_posix(),
        )
    except OSError:
        entries = []

    for entry in entries:
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
    topic_count = len(list((root / MEMORY_RELATIVE).glob("*.md"))) - 1
    print(f"Memory contract OK ({topic_count} indexed topic{'s' if topic_count != 1 else ''}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
