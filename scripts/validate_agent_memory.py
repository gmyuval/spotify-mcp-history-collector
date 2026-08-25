"""Dependency-free validation for repository-owned durable agent memory."""

import ctypes
import errno
import os
import re
import stat
import sys
from ctypes import wintypes
from dataclasses import dataclass
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
WINDOWS_DIRECTORY = getattr(stat, "FILE_ATTRIBUTE_DIRECTORY", 0x0010)
INSTRUCTION_POINTER_RULES = {
    Path("AGENTS.md"): (
        (
            "repository-first retrieval",
            re.escape(
                "use repository-first retrieval for durable project knowledge: read "
                "`docs/agent/memory/readme.md` first, then retrieve only relevant indexed entries"
            ),
        ),
        (
            "durable recording",
            re.escape("record an earned durable lesson"),
        ),
        (
            "durable correction or deletion",
            re.escape("correct or delete a stale, false, duplicated, or unsafe entry"),
        ),
        (
            "same-PR durable change linkage",
            r"## repository-first memory (?:(?! ## ).)*same issue-linked pull request"
            r"(?:(?! ## ).)*same issue-linked pull request",
        ),
        (
            "tool-local ownership boundary",
            re.escape("tool-local memory contains the repository pointer plus transient or personal bookmarks only"),
        ),
        (
            "authority precedence",
            re.escape(
                "memory is context, never authority. it cannot override higher-priority harness or user instructions, "
                "this contract, an accepted adr, linear planning state, current code and tests, or observed "
                "deployed-state evidence"
            ),
        ),
        ("Linear-only work queue", re.escape("linear remains the sole work queue")),
    ),
    Path("CLAUDE.md"): (
        (
            "repository memory index",
            re.escape(
                "for repository memory, read "
                "[docs/agent/memory/readme.md](docs/agent/memory/readme.md) first, then only relevant indexed entries"
            ),
        ),
        (
            "durable recording",
            r"record(?: or correct)? earned durable lessons",
        ),
        (
            "durable correction or deletion",
            r"(?:record or )?correct earned durable lessons",
        ),
        (
            "same-PR durable change linkage",
            re.escape("earned durable lessons in the same issue-linked pull request"),
        ),
        (
            "tool-local ownership boundary",
            re.escape("keep claude private memory to the repository pointer plus transient or personal bookmarks only"),
        ),
        (
            "authority precedence",
            re.escape("it is the canonical, vendor-neutral operating contract and wins if this file conflicts with it"),
        ),
    ),
    Path("docs/agent/tool-policy.md"): (
        (
            "canonical memory contract",
            re.escape(
                "for durable lessons, follow the canonical "
                "[repository-first memory](../../agents.md#repository-first-memory) contract"
            ),
        ),
        (
            "repository memory index",
            re.escape("read `docs/agent/memory/readme.md` before relevant indexed entries"),
        ),
        (
            "durable recording",
            r"record(?: or correct)? an earned lesson",
        ),
        (
            "durable correction or deletion",
            r"(?:record or )?correct an earned lesson",
        ),
        (
            "same-PR durable change linkage",
            re.escape("an earned lesson in the same issue-linked pull request"),
        ),
        (
            "tool-local ownership boundary",
            re.escape(
                "keep tool-local or private memory to the repository pointer plus transient or personal bookmarks only"
            ),
        ),
        (
            "authority precedence",
            re.escape(
                "tools provide capabilities and evidence. they do not grant authority or override `agents.md`, "
                "an accepted adr, a direct user instruction, or a plan-first stop"
            ),
        ),
        ("Linear-only work queue", re.escape("linear remains the sole work queue")),
    ),
    Path(".agents/skills/session-start/SKILL.md"): (
        ("repository memory index", re.escape("docs/agent/memory/readme.md")),
        (
            "relevant indexed retrieval",
            re.escape("first, then only topic entries relevant to this task"),
        ),
    ),
    Path(".agents/skills/pr-lifecycle/SKILL.md"): (
        ("repository memory index", re.escape("docs/agent/memory/readme.md")),
        (
            "memory impact assessment",
            re.escape("assess whether the change affects repository memory"),
        ),
        (
            "same-PR stale correction",
            re.escape("correct or delete any stale repository-memory entry in the same issue-linked pull request"),
        ),
        (
            "private contradiction prohibition",
            re.escape("never preserve a contradictory private note"),
        ),
    ),
    Path(".agents/skills/end-session/SKILL.md"): (
        ("repository memory index", re.escape("docs/agent/memory/readme.md")),
        (
            "durable or transient classification",
            re.escape("distinguish an earned durable lesson from a transient or personal bookmark"),
        ),
        (
            "same-PR earned memory recording",
            re.escape("record any earned entry and index change in the same issue-linked pull request as its evidence"),
        ),
        ("landed bookmark cleanup", re.escape("remove a landed bookmark")),
        (
            "recoverable bookmark cleanup",
            re.escape("bookmark whose state is recoverable from git, github, linear, or the repository"),
        ),
    ),
    Path("docs/agent/review-checklist.md"): (
        ("memory consideration", re.escape("repository memory was considered")),
        ("source-of-truth placement", re.escape("correct source of truth")),
        ("earned updates only", re.escape("updated only when earned")),
        ("repository memory index", re.escape("docs/agent/memory/readme.md")),
        ("index integrity", re.escape("index integrity")),
        (
            "transient or private exclusion",
            re.escape("no transient, personal, or private content"),
        ),
    ),
}


def _diagnostic(code: str, path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = README_RELATIVE
    rendered = relative.as_posix().encode("unicode_escape").decode("ascii")
    return f"{code}: {rendered}"


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


@dataclass(frozen=True)
class _MemoryChild:
    name: str
    mode: int
    file_attributes: int = 0
    identity: tuple[int, int] = (0, 0)
    text: str | None = None


@dataclass(frozen=True)
class _Win32HandleInfo:
    file_attributes: int
    identity: tuple[int, int]


@dataclass(frozen=True)
class _MemorySnapshot:
    children: tuple[_MemoryChild, ...]


def _posix_directory_flags() -> int:
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    no_follow_flag = getattr(os, "O_NOFOLLOW", 0)
    if directory_flag == 0 or no_follow_flag == 0:
        raise OSError(errno.ENOTSUP, "descriptor-bound directory scans are unavailable")
    return os.O_RDONLY | directory_flag | no_follow_flag


def _read_posix_memory_child(memory: Path, memory_handle: int, child: _MemoryChild) -> str:
    no_follow_flag = getattr(os, "O_NOFOLLOW", 0)
    if no_follow_flag == 0:
        raise OSError(errno.ENOTSUP, "descriptor-bound no-follow reads are unavailable")
    descriptor = os.open(child.name, os.O_RDONLY | no_follow_flag, dir_fd=memory_handle)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError(errno.EINVAL, "memory child is not a regular file")
        if (metadata.st_dev, metadata.st_ino) != child.identity:
            raise OSError(errno.ESTALE, "memory child identity changed")
        visible = os.stat(memory / child.name, follow_symlinks=False)
        if (visible.st_dev, visible.st_ino) != child.identity:
            raise OSError(errno.ESTALE, "visible memory child identity changed")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 64 * 1024):
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    finally:
        os.close(descriptor)


def _snapshot_memory_posix(root: Path) -> _MemorySnapshot:
    directory_flags = _posix_directory_flags()
    descriptor = os.open(root, directory_flags)
    current_path = root
    try:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError(errno.ENOTDIR, "repository root is not a directory")
        for component in MEMORY_RELATIVE.parts:
            child_descriptor = os.open(component, directory_flags, dir_fd=descriptor)
            try:
                metadata = os.fstat(child_descriptor)
                if not stat.S_ISDIR(metadata.st_mode):
                    raise OSError(errno.ENOTDIR, "memory ancestor is not a directory")
                current_path /= component
                visible = os.stat(current_path, follow_symlinks=False)
                if (visible.st_dev, visible.st_ino) != (metadata.st_dev, metadata.st_ino):
                    raise OSError(errno.ESTALE, "visible memory boundary identity changed")
            except BaseException:
                os.close(child_descriptor)
                raise
            os.close(descriptor)
            descriptor = child_descriptor

        with os.scandir(descriptor) as iterator:
            children = [
                _MemoryChild(
                    child.name,
                    metadata.st_mode,
                    identity=(metadata.st_dev, metadata.st_ino),
                )
                for child in iterator
                for metadata in (child.stat(follow_symlinks=False),)
            ]
        snapshotted: list[_MemoryChild] = []
        for child in sorted(children, key=lambda item: (item.name.casefold(), item.name)):
            text = None
            if stat.S_ISREG(child.mode) and child.name.lower().endswith(".md"):
                text = _read_memory_child(root / MEMORY_RELATIVE, descriptor, child)
            snapshotted.append(
                _MemoryChild(
                    child.name,
                    child.mode,
                    child.file_attributes,
                    child.identity,
                    text,
                )
            )
        return _MemorySnapshot(tuple(snapshotted))
    finally:
        os.close(descriptor)


def _win32_open_directory(memory: Path) -> int:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE

    file_list_directory = 0x0001
    file_share_all = 0x0001 | 0x0002 | 0x0004
    open_existing = 3
    file_flag_backup_semantics = 0x02000000
    file_flag_open_reparse_point = 0x00200000
    handle = create_file(
        str(memory),
        file_list_directory,
        file_share_all,
        None,
        open_existing,
        file_flag_backup_semantics | file_flag_open_reparse_point,
        None,
    )
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    return int(handle)


def _win32_close_handle(handle: int) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    close_handle(wintypes.HANDLE(handle))


def _win32_handle_info(handle: int) -> _Win32HandleInfo:
    class _ByHandleFileInformation(ctypes.Structure):
        _fields_ = (
            ("file_attributes", wintypes.DWORD),
            ("creation_time", wintypes.FILETIME),
            ("last_access_time", wintypes.FILETIME),
            ("last_write_time", wintypes.FILETIME),
            ("volume_serial_number", wintypes.DWORD),
            ("file_size_high", wintypes.DWORD),
            ("file_size_low", wintypes.DWORD),
            ("number_of_links", wintypes.DWORD),
            ("file_index_high", wintypes.DWORD),
            ("file_index_low", wintypes.DWORD),
        )

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_information = kernel32.GetFileInformationByHandle
    get_information.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ByHandleFileInformation))
    get_information.restype = wintypes.BOOL
    information = _ByHandleFileInformation()
    if not get_information(wintypes.HANDLE(handle), ctypes.byref(information)):
        raise ctypes.WinError(ctypes.get_last_error())
    file_id = (information.file_index_high << 32) | information.file_index_low
    return _Win32HandleInfo(
        information.file_attributes,
        (information.volume_serial_number, file_id),
    )


def _validate_win32_directory_handle(handle: int) -> _Win32HandleInfo:
    information = _win32_handle_info(handle)
    if information.file_attributes & WINDOWS_REPARSE_POINT:
        raise OSError(errno.ELOOP, "memory boundary is a reparse point")
    if not information.file_attributes & WINDOWS_DIRECTORY:
        raise OSError(errno.ENOTDIR, "memory boundary is not a directory")
    return information


def _win32_memory_children(handle: int) -> list[_MemoryChild]:
    class _FileIdBothDirectoryInfo(ctypes.Structure):
        _fields_ = (
            ("next_entry_offset", wintypes.DWORD),
            ("file_index", wintypes.DWORD),
            ("creation_time", ctypes.c_int64),
            ("last_access_time", ctypes.c_int64),
            ("last_write_time", ctypes.c_int64),
            ("change_time", ctypes.c_int64),
            ("end_of_file", ctypes.c_int64),
            ("allocation_size", ctypes.c_int64),
            ("file_attributes", wintypes.DWORD),
            ("file_name_length", wintypes.DWORD),
            ("ea_size", wintypes.DWORD),
            ("short_name_length", ctypes.c_byte),
            ("short_name", wintypes.WCHAR * 12),
            ("file_id", ctypes.c_int64),
        )

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_information = kernel32.GetFileInformationByHandleEx
    get_information.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    get_information.restype = wintypes.BOOL

    parent = _validate_win32_directory_handle(handle)

    buffer_size = 64 * 1024
    buffer = ctypes.create_string_buffer(buffer_size)
    header_size = ctypes.sizeof(_FileIdBothDirectoryInfo)
    children: list[_MemoryChild] = []
    restart = True
    while True:
        information_class = 0x0B if restart else 0x0A
        restart = False
        if not get_information(
            wintypes.HANDLE(handle),
            information_class,
            buffer,
            buffer_size,
        ):
            error = ctypes.get_last_error()
            if error in {18, 38}:
                break
            raise ctypes.WinError(error)

        offset = 0
        while True:
            entry = _FileIdBothDirectoryInfo.from_buffer(buffer, offset)
            name_bytes = ctypes.string_at(
                ctypes.addressof(buffer) + offset + header_size,
                entry.file_name_length,
            )
            name = name_bytes.decode("utf-16-le", errors="surrogatepass")
            if name not in {".", ".."}:
                if entry.file_attributes & WINDOWS_REPARSE_POINT:
                    mode = stat.S_IFLNK
                elif entry.file_attributes & WINDOWS_DIRECTORY:
                    mode = stat.S_IFDIR
                else:
                    mode = stat.S_IFREG
                children.append(
                    _MemoryChild(
                        name,
                        mode,
                        entry.file_attributes,
                        (parent.identity[0], entry.file_id & ((1 << 64) - 1)),
                    )
                )
            if entry.next_entry_offset == 0:
                break
            offset += entry.next_entry_offset

    return children


def _win32_open_file(path: Path) -> int:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    generic_read = 0x80000000
    file_share_all = 0x0001 | 0x0002 | 0x0004
    open_existing = 3
    file_flag_open_reparse_point = 0x00200000
    handle = create_file(
        str(path),
        generic_read,
        file_share_all,
        None,
        open_existing,
        file_flag_open_reparse_point,
        None,
    )
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    return int(handle)


def _read_win32_memory_child(memory: Path, child: _MemoryChild) -> str:
    handle = _win32_open_file(memory / child.name)
    try:
        information = _win32_handle_info(handle)
        if information.file_attributes & (WINDOWS_REPARSE_POINT | WINDOWS_DIRECTORY):
            raise OSError(errno.EINVAL, "memory child is not a no-follow regular file")
        if information.identity != child.identity:
            raise OSError(errno.ESTALE, "memory child identity changed")

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        read_file = kernel32.ReadFile
        read_file.argtypes = (
            wintypes.HANDLE,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        )
        read_file.restype = wintypes.BOOL
        chunks: list[bytes] = []
        while True:
            buffer = ctypes.create_string_buffer(64 * 1024)
            read = wintypes.DWORD()
            if not read_file(
                wintypes.HANDLE(handle),
                buffer,
                len(buffer),
                ctypes.byref(read),
                None,
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            if read.value == 0:
                break
            chunks.append(buffer.raw[: read.value])
        return b"".join(chunks).decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    finally:
        _win32_close_handle(handle)


def _read_memory_child(memory: Path, memory_handle: int, child: _MemoryChild) -> str:
    if sys.platform == "win32":
        return _read_win32_memory_child(memory, child)
    return _read_posix_memory_child(memory, memory_handle, child)


def _snapshot_memory_windows(root: Path) -> _MemorySnapshot:
    current_path = root
    handle = _win32_open_directory(root)
    try:
        _validate_win32_directory_handle(handle)
        for component in MEMORY_RELATIVE.parts:
            matches = [
                child for child in _win32_memory_children(handle) if child.name.casefold() == component.casefold()
            ]
            if len(matches) != 1:
                raise OSError(errno.ENOENT, "memory boundary is missing")
            expected = matches[0]
            if stat.S_ISLNK(expected.mode) or not stat.S_ISDIR(expected.mode):
                raise OSError(errno.ENOTDIR, "memory boundary is not a directory")
            if expected.file_attributes & WINDOWS_REPARSE_POINT:
                raise OSError(errno.ELOOP, "memory boundary is a reparse point")

            current_path /= component
            child_handle = _win32_open_directory(current_path)
            try:
                actual = _validate_win32_directory_handle(child_handle)
                if actual.identity != expected.identity:
                    raise OSError(errno.ESTALE, "memory boundary identity changed")
            except BaseException:
                _win32_close_handle(child_handle)
                raise
            _win32_close_handle(handle)
            handle = child_handle

        children = sorted(
            _win32_memory_children(handle),
            key=lambda child: (child.name.casefold(), child.name),
        )
        snapshotted: list[_MemoryChild] = []
        for child in children:
            text = None
            if stat.S_ISREG(child.mode) and child.name.lower().endswith(".md"):
                text = _read_memory_child(current_path, handle, child)
            snapshotted.append(
                _MemoryChild(
                    child.name,
                    child.mode,
                    child.file_attributes,
                    child.identity,
                    text,
                )
            )
        return _MemorySnapshot(tuple(snapshotted))
    finally:
        _win32_close_handle(handle)


def _snapshot_memory(root: Path) -> _MemorySnapshot:
    if sys.platform == "win32":
        return _snapshot_memory_windows(root)
    return _snapshot_memory_posix(root)


def _scan_memory_tree(
    memory: Path,
    root: Path,
    blocked_entries: set[str],
    children: tuple[_MemoryChild, ...],
) -> tuple[list[_MemoryChild], list[str]]:
    entries: list[_MemoryChild] = []
    issues: list[str] = []

    for child in children:
        path = memory / child.name
        key = child.name.casefold() if sys.platform == "win32" else child.name
        is_reparse = stat.S_ISLNK(child.mode) or bool(child.file_attributes & WINDOWS_REPARSE_POINT)
        if is_reparse:
            if key not in blocked_entries:
                issues.append(_diagnostic("MEMORY_INDEX_LINK_INVALID", path, root))
            continue
        if stat.S_ISDIR(child.mode):
            issues.append(_diagnostic("MEMORY_ENTRY_LAYOUT", path, root))
            continue
        if path.suffix.lower() != ".md":
            continue
        if not stat.S_ISREG(child.mode):
            issues.append(_diagnostic("MEMORY_ENTRY_LAYOUT", path, root))
            continue
        entries.append(child)

    return entries, issues


def _validate_instruction_pointers(root: Path) -> list[str]:
    issues: list[str] = []
    for relative, concepts in INSTRUCTION_POINTER_RULES.items():
        instruction = root / relative
        if _has_reparse_component(instruction, root):
            issues.append(f"MEMORY_INSTRUCTION_POINTER: {relative.as_posix()}: instruction path boundary")
            continue
        text = _read(instruction)
        normalized = " ".join(text.lower().split()) if text is not None else ""
        for label, pattern in concepts:
            if re.search(pattern, normalized) is None:
                issues.append(f"MEMORY_INSTRUCTION_POINTER: {relative.as_posix()}: {label}")
    return issues


def _validate_memory(root: Path) -> tuple[list[str], int]:
    root = root.absolute()
    memory = root / MEMORY_RELATIVE
    readme_path = root / README_RELATIVE
    if _has_reparse_component(memory, root):
        return [_diagnostic("MEMORY_INDEX_LINK_INVALID", readme_path, root)], 0
    if _is_reparse_point(readme_path):
        return [_diagnostic("MEMORY_INDEX_LINK_INVALID", readme_path, root)], 0

    try:
        snapshot = _snapshot_memory(root)
    except OSError, UnicodeError:
        return [_diagnostic("MEMORY_TREE_SCAN", memory, root)], 0

    def name_key(name: str) -> str:
        return name.casefold() if sys.platform == "win32" else name

    children_by_name: dict[str, list[_MemoryChild]] = {}
    for child in snapshot.children:
        children_by_name.setdefault(name_key(child.name), []).append(child)

    readme_matches = children_by_name.get(name_key("README.md"), [])
    if len(readme_matches) != 1:
        return [_diagnostic("MEMORY_INDEX_LINK_MISSING", readme_path, root)], 0
    readme_child = readme_matches[0]
    readme_reparse = stat.S_ISLNK(readme_child.mode) or bool(readme_child.file_attributes & WINDOWS_REPARSE_POINT)
    if readme_reparse:
        return [_diagnostic("MEMORY_INDEX_LINK_INVALID", readme_path, root)], 0
    if not stat.S_ISREG(readme_child.mode) or readme_child.text is None:
        return [_diagnostic("MEMORY_INDEX_LINK_MISSING", readme_path, root)], 0
    readme = readme_child.text

    index = _index_body(readme)
    if index is None:
        return [_diagnostic("MEMORY_INDEX_LINK_INVALID", readme_path, root)], 0

    issues: list[str] = []
    indexed_names: dict[str, tuple[str, int]] = {}
    indexed_identities: set[tuple[int, int]] = set()
    blocked_entries: set[str] = set()
    for raw_target in MARKDOWN_LINK.findall(index):
        windows_absolute = re.match(r"^[A-Za-z]:[\\/]", raw_target) is not None
        target_path = Path(raw_target)
        if (
            windows_absolute
            or target_path.is_absolute()
            or "/" in raw_target
            or "\\" in raw_target
            or raw_target in {"", ".", ".."}
        ):
            issues.append(_diagnostic("MEMORY_INDEX_LINK_INVALID", readme_path, root))
            continue

        candidate = memory / target_path
        key = name_key(raw_target)
        if key == name_key("README.md"):
            issues.append(_diagnostic("MEMORY_INDEX_LINK_INVALID", readme_path, root))
            continue

        previous = indexed_names.get(key)
        indexed_names[key] = (raw_target, 1 if previous is None else previous[1] + 1)

    for key, (raw_target, count) in sorted(indexed_names.items()):
        candidate = memory / raw_target
        if count != 1:
            issues.append(_diagnostic("MEMORY_INDEX_LINK_INVALID", candidate, root))
        matches = children_by_name.get(key, [])
        if len(matches) != 1:
            issues.append(_diagnostic("MEMORY_INDEX_LINK_MISSING", candidate, root))
            continue
        child = matches[0]
        is_reparse = stat.S_ISLNK(child.mode) or bool(child.file_attributes & WINDOWS_REPARSE_POINT)
        if is_reparse:
            issues.append(_diagnostic("MEMORY_INDEX_LINK_INVALID", candidate, root))
            blocked_entries.add(key)
            continue
        if not stat.S_ISREG(child.mode):
            issues.append(_diagnostic("MEMORY_INDEX_LINK_MISSING", candidate, root))
            continue
        if child.identity == readme_child.identity:
            issues.append(_diagnostic("MEMORY_INDEX_LINK_INVALID", readme_path, root))
            continue
        indexed_identities.add(child.identity)
        if child.text is None or not _entry_has_schema(child.text):
            issues.append(_diagnostic("MEMORY_ENTRY_SCHEMA", candidate, root))

    entries, scan_issues = _scan_memory_tree(memory, root, blocked_entries, snapshot.children)
    issues.extend(scan_issues)

    for entry in entries:
        path = memory / entry.name
        if entry.identity == readme_child.identity:
            continue
        if entry.identity not in indexed_identities:
            issues.append(_diagnostic("MEMORY_ENTRY_UNINDEXED", path, root))
        if KEBAB_MARKDOWN.fullmatch(entry.name) is None:
            issues.append(_diagnostic("MEMORY_ENTRY_FILENAME", path, root))
        if entry.identity not in indexed_identities and (entry.text is None or not _entry_has_schema(entry.text)):
            issues.append(_diagnostic("MEMORY_ENTRY_SCHEMA", path, root))

    issues.extend(_validate_instruction_pointers(root))
    return issues, len(indexed_names)


def validate_memory(root: Path) -> list[str]:
    """Return sanitized, fail-closed findings for the repository memory tree."""

    issues, _ = _validate_memory(root)
    return issues


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) == 2 else Path(__file__).resolve().parents[1]
    issues, topic_count = _validate_memory(root)
    if issues:
        for issue in issues:
            print(issue)
        return 1
    print(f"Memory contract OK ({topic_count} indexed topic{'s' if topic_count != 1 else ''}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
