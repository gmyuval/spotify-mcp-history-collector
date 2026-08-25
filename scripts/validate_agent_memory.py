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
    link_count: int = 1
    text: str | None = None


@dataclass(frozen=True)
class _Win32HandleInfo:
    file_attributes: int
    identity: tuple[int, int]
    link_count: int
    file_size: int
    last_write_time: int


@dataclass(frozen=True)
class _MemoryRead:
    text: str | None
    link_count: int


@dataclass(frozen=True)
class _MemorySnapshot:
    children: tuple[_MemoryChild, ...]


def _posix_directory_flags() -> int:
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    no_follow_flag = getattr(os, "O_NOFOLLOW", 0)
    if directory_flag == 0 or no_follow_flag == 0:
        raise OSError(errno.ENOTSUP, "descriptor-bound directory scans are unavailable")
    return os.O_RDONLY | directory_flag | no_follow_flag


def _capture_memory_boundary_posix(root: Path) -> tuple[tuple[int, int], ...]:
    directory_flags = _posix_directory_flags()
    identities: list[tuple[int, int]] = []
    current_path = root
    for component in (None, *MEMORY_RELATIVE.parts):
        if component is not None:
            current_path /= component
        descriptor = os.open(current_path, directory_flags)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISDIR(metadata.st_mode):
                raise OSError(errno.ENOTDIR, "memory boundary is not a directory")
            identities.append((metadata.st_dev, metadata.st_ino))
        finally:
            os.close(descriptor)
    return tuple(identities)


def _verify_posix_visible_directory(path: Path, descriptor: int) -> None:
    retained = os.fstat(descriptor)
    visible = os.stat(path, follow_symlinks=False)
    if not stat.S_ISDIR(visible.st_mode) or (visible.st_dev, visible.st_ino) != (
        retained.st_dev,
        retained.st_ino,
    ):
        raise OSError(errno.ESTALE, "visible directory identity changed")


def _verify_posix_file_after_read(
    path: Path,
    descriptor: int,
    before: os.stat_result,
    expected_identity: tuple[int, int],
) -> os.stat_result:
    after = os.fstat(descriptor)
    visible = os.stat(path, follow_symlinks=False)
    if (after.st_dev, after.st_ino) != expected_identity:
        raise OSError(errno.ESTALE, "file identity changed during read")
    if not stat.S_ISREG(visible.st_mode) or (visible.st_dev, visible.st_ino) != expected_identity:
        raise OSError(errno.ESTALE, "visible file identity changed during read")
    if (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ):
        raise OSError(errno.ESTALE, "file content metadata changed during read")
    return after


def _read_posix_memory_child(memory: Path, memory_handle: int, child: _MemoryChild) -> _MemoryRead:
    no_follow_flag = getattr(os, "O_NOFOLLOW", 0)
    if no_follow_flag == 0:
        raise OSError(errno.ENOTSUP, "descriptor-bound no-follow reads are unavailable")
    _verify_posix_visible_directory(memory, memory_handle)
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
        if metadata.st_nlink != 1:
            return _MemoryRead(None, metadata.st_nlink)
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 64 * 1024):
            chunks.append(chunk)
        _verify_posix_visible_directory(memory, memory_handle)
        after = os.fstat(descriptor)
        if after.st_nlink != 1:
            return _MemoryRead(None, after.st_nlink)
        after = _verify_posix_file_after_read(memory / child.name, descriptor, metadata, child.identity)
        text = b"".join(chunks).decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        return _MemoryRead(text, after.st_nlink)
    finally:
        os.close(descriptor)


def _snapshot_memory_posix(
    root: Path,
    expected_boundary: tuple[tuple[int, int], ...],
) -> _MemorySnapshot:
    directory_flags = _posix_directory_flags()
    descriptor = os.open(root, directory_flags)
    current_path = root
    try:
        root_metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(root_metadata.st_mode):
            raise OSError(errno.ENOTDIR, "repository root is not a directory")
        if (root_metadata.st_dev, root_metadata.st_ino) != expected_boundary[0]:
            raise OSError(errno.ESTALE, "repository root identity changed")
        for index, component in enumerate(MEMORY_RELATIVE.parts, start=1):
            child_descriptor = os.open(component, directory_flags, dir_fd=descriptor)
            try:
                metadata = os.fstat(child_descriptor)
                if not stat.S_ISDIR(metadata.st_mode):
                    raise OSError(errno.ENOTDIR, "memory ancestor is not a directory")
                if (metadata.st_dev, metadata.st_ino) != expected_boundary[index]:
                    raise OSError(errno.ESTALE, "memory boundary identity changed")
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
                    link_count=metadata.st_nlink,
                )
                for child in iterator
                for metadata in (child.stat(follow_symlinks=False),)
            ]
        snapshotted: list[_MemoryChild] = []
        for child in sorted(children, key=lambda item: (item.name.casefold(), item.name)):
            text = None
            link_count = child.link_count
            if stat.S_ISREG(child.mode) and child.name.lower().endswith(".md") and link_count == 1:
                result = _read_memory_child(root / MEMORY_RELATIVE, descriptor, child)
                text = result.text
                link_count = result.link_count
            snapshotted.append(
                _MemoryChild(
                    child.name,
                    child.mode,
                    child.file_attributes,
                    child.identity,
                    link_count,
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
    file_size = (information.file_size_high << 32) | information.file_size_low
    last_write_time = (information.last_write_time.dwHighDateTime << 32) | information.last_write_time.dwLowDateTime
    return _Win32HandleInfo(
        information.file_attributes,
        (information.volume_serial_number, file_id),
        information.number_of_links,
        file_size,
        last_write_time,
    )


def _validate_win32_directory_handle(handle: int) -> _Win32HandleInfo:
    information = _win32_handle_info(handle)
    if information.file_attributes & WINDOWS_REPARSE_POINT:
        raise OSError(errno.ELOOP, "memory boundary is a reparse point")
    if not information.file_attributes & WINDOWS_DIRECTORY:
        raise OSError(errno.ENOTDIR, "memory boundary is not a directory")
    return information


def _capture_memory_boundary_windows(root: Path) -> tuple[tuple[int, int], ...]:
    identities: list[tuple[int, int]] = []
    current_path = root
    for component in (None, *MEMORY_RELATIVE.parts):
        if component is not None:
            current_path /= component
        handle = _win32_open_directory(current_path)
        try:
            identities.append(_validate_win32_directory_handle(handle).identity)
        finally:
            _win32_close_handle(handle)
    return tuple(identities)


def _verify_win32_visible_directory(path: Path, expected_identity: tuple[int, int]) -> None:
    handle = _win32_open_directory(path)
    try:
        if _validate_win32_directory_handle(handle).identity != expected_identity:
            raise OSError(errno.ESTALE, "visible directory identity changed")
    finally:
        _win32_close_handle(handle)


def _verify_win32_visible_file(path: Path, expected_identity: tuple[int, int]) -> None:
    handle = _win32_open_file(path)
    try:
        information = _win32_handle_info(handle)
        if information.file_attributes & (WINDOWS_REPARSE_POINT | WINDOWS_DIRECTORY):
            raise OSError(errno.EINVAL, "visible file is not a no-follow regular file")
        if information.identity != expected_identity:
            raise OSError(errno.ESTALE, "visible file identity changed during read")
    finally:
        _win32_close_handle(handle)


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
    file_share_read = 0x0001
    open_existing = 3
    file_flag_open_reparse_point = 0x00200000
    handle = create_file(
        str(path),
        generic_read,
        file_share_read,
        None,
        open_existing,
        file_flag_open_reparse_point,
        None,
    )
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    return int(handle)


def _read_win32_handle_text(handle: int, _name: str) -> str:
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


def _read_win32_memory_child(memory: Path, memory_handle: int, child: _MemoryChild) -> _MemoryRead:
    parent_identity = _validate_win32_directory_handle(memory_handle).identity
    _verify_win32_visible_directory(memory, parent_identity)
    handle = _win32_open_file(memory / child.name)
    try:
        information = _win32_handle_info(handle)
        if information.file_attributes & (WINDOWS_REPARSE_POINT | WINDOWS_DIRECTORY):
            raise OSError(errno.EINVAL, "memory child is not a no-follow regular file")
        if information.identity != child.identity:
            raise OSError(errno.ESTALE, "memory child identity changed")
        if information.link_count != 1:
            return _MemoryRead(None, information.link_count)
        _verify_win32_visible_directory(memory, parent_identity)
        text = _read_win32_handle_text(handle, child.name)
        after = _win32_handle_info(handle)
        _verify_win32_visible_directory(memory, parent_identity)
        if after.identity != child.identity:
            raise OSError(errno.ESTALE, "memory child identity changed during read")
        if after.link_count != 1:
            return _MemoryRead(None, after.link_count)
        _verify_win32_visible_file(memory / child.name, child.identity)
        if (after.file_size, after.last_write_time) != (information.file_size, information.last_write_time):
            raise OSError(errno.ESTALE, "memory child content metadata changed during read")
        return _MemoryRead(text, after.link_count)
    finally:
        _win32_close_handle(handle)


def _read_memory_child(memory: Path, memory_handle: int, child: _MemoryChild) -> _MemoryRead:
    if sys.platform == "win32":
        return _read_win32_memory_child(memory, memory_handle, child)
    return _read_posix_memory_child(memory, memory_handle, child)


def _snapshot_memory_windows(
    root: Path,
    expected_boundary: tuple[tuple[int, int], ...],
) -> _MemorySnapshot:
    current_path = root
    handle = _win32_open_directory(root)
    try:
        if _validate_win32_directory_handle(handle).identity != expected_boundary[0]:
            raise OSError(errno.ESTALE, "repository root identity changed")
        for index, component in enumerate(MEMORY_RELATIVE.parts, start=1):
            matches = [child for child in _win32_memory_children(handle) if child.name == component]
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
                if actual.identity != expected_boundary[index]:
                    raise OSError(errno.ESTALE, "memory boundary changed after precheck")
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
            link_count = child.link_count
            if stat.S_ISREG(child.mode) and child.name.lower().endswith(".md"):
                result = _read_memory_child(current_path, handle, child)
                text = result.text
                link_count = result.link_count
            snapshotted.append(
                _MemoryChild(
                    child.name,
                    child.mode,
                    child.file_attributes,
                    child.identity,
                    link_count,
                    text,
                )
            )
        return _MemorySnapshot(tuple(snapshotted))
    finally:
        _win32_close_handle(handle)


def _capture_memory_boundary(root: Path) -> tuple[tuple[int, int], ...]:
    if sys.platform == "win32":
        return _capture_memory_boundary_windows(root)
    return _capture_memory_boundary_posix(root)


def _snapshot_memory(
    root: Path,
    expected_boundary: tuple[tuple[int, int], ...] | None = None,
) -> _MemorySnapshot:
    boundary = expected_boundary if expected_boundary is not None else _capture_memory_boundary(root)
    if sys.platform == "win32":
        return _snapshot_memory_windows(root, boundary)
    return _snapshot_memory_posix(root, boundary)


def _validate_repository_relative(relative: Path) -> None:
    if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise OSError(errno.EINVAL, "repository file path is not a strict relative path")


def _capture_repository_file_boundary_posix(root: Path, relative: Path) -> tuple[tuple[int, int], ...]:
    _validate_repository_relative(relative)
    directory_flags = _posix_directory_flags()
    identities: list[tuple[int, int]] = []
    current_path = root
    for component in (None, *relative.parts[:-1]):
        if component is not None:
            current_path /= component
        descriptor = os.open(current_path, directory_flags)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISDIR(metadata.st_mode):
                raise OSError(errno.ENOTDIR, "repository ancestor is not a directory")
            identities.append((metadata.st_dev, metadata.st_ino))
        finally:
            os.close(descriptor)

    no_follow_flag = getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(current_path / relative.name, os.O_RDONLY | no_follow_flag)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise OSError(errno.EINVAL, "repository instruction is not a unique regular file")
        identities.append((metadata.st_dev, metadata.st_ino))
    finally:
        os.close(descriptor)
    return tuple(identities)


def _capture_repository_file_boundary_windows(root: Path, relative: Path) -> tuple[tuple[int, int], ...]:
    _validate_repository_relative(relative)
    identities: list[tuple[int, int]] = []
    current_path = root
    for component in (None, *relative.parts[:-1]):
        if component is not None:
            current_path /= component
        handle = _win32_open_directory(current_path)
        try:
            identities.append(_validate_win32_directory_handle(handle).identity)
        finally:
            _win32_close_handle(handle)

    handle = _win32_open_file(current_path / relative.name)
    try:
        information = _win32_handle_info(handle)
        if information.file_attributes & (WINDOWS_REPARSE_POINT | WINDOWS_DIRECTORY):
            raise OSError(errno.EINVAL, "repository instruction is not a regular file")
        if information.link_count != 1:
            raise OSError(errno.EINVAL, "repository instruction is not a unique regular file")
        identities.append(information.identity)
    finally:
        _win32_close_handle(handle)
    return tuple(identities)


def _capture_repository_file_boundary(root: Path, relative: Path) -> tuple[tuple[int, int], ...]:
    if sys.platform == "win32":
        return _capture_repository_file_boundary_windows(root, relative)
    return _capture_repository_file_boundary_posix(root, relative)


def _read_repository_file_posix(
    root: Path,
    relative: Path,
    expected_boundary: tuple[tuple[int, int], ...],
) -> str:
    _validate_repository_relative(relative)
    directory_flags = _posix_directory_flags()
    descriptor = os.open(root, directory_flags)
    current_path = root
    try:
        root_metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(root_metadata.st_mode):
            raise OSError(errno.ENOTDIR, "repository root is not a directory")
        if (root_metadata.st_dev, root_metadata.st_ino) != expected_boundary[0]:
            raise OSError(errno.ESTALE, "repository root identity changed")
        for index, component in enumerate(relative.parts[:-1], start=1):
            child_descriptor = os.open(component, directory_flags, dir_fd=descriptor)
            try:
                metadata = os.fstat(child_descriptor)
                if not stat.S_ISDIR(metadata.st_mode):
                    raise OSError(errno.ENOTDIR, "repository ancestor is not a directory")
                if (metadata.st_dev, metadata.st_ino) != expected_boundary[index]:
                    raise OSError(errno.ESTALE, "repository ancestor identity changed")
                current_path /= component
                visible = os.stat(current_path, follow_symlinks=False)
                if (visible.st_dev, visible.st_ino) != (metadata.st_dev, metadata.st_ino):
                    raise OSError(errno.ESTALE, "visible repository ancestor identity changed")
            except BaseException:
                os.close(child_descriptor)
                raise
            os.close(descriptor)
            descriptor = child_descriptor

        no_follow_flag = getattr(os, "O_NOFOLLOW", 0)
        _verify_posix_visible_directory(current_path, descriptor)
        file_descriptor = os.open(relative.name, os.O_RDONLY | no_follow_flag, dir_fd=descriptor)
        try:
            metadata = os.fstat(file_descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise OSError(errno.EINVAL, "repository instruction is not a unique regular file")
            if (metadata.st_dev, metadata.st_ino) != expected_boundary[-1]:
                raise OSError(errno.ESTALE, "repository instruction identity changed")
            visible = os.stat(current_path / relative.name, follow_symlinks=False)
            if (visible.st_dev, visible.st_ino) != (metadata.st_dev, metadata.st_ino):
                raise OSError(errno.ESTALE, "visible repository file identity changed")
            chunks: list[bytes] = []
            while chunk := os.read(file_descriptor, 64 * 1024):
                chunks.append(chunk)
            _verify_posix_visible_directory(current_path, descriptor)
            after = os.fstat(file_descriptor)
            if after.st_nlink != 1:
                raise OSError(errno.ESTALE, "repository instruction changed during read")
            _verify_posix_file_after_read(
                current_path / relative.name,
                file_descriptor,
                metadata,
                (metadata.st_dev, metadata.st_ino),
            )
            return b"".join(chunks).decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        finally:
            os.close(file_descriptor)
    finally:
        os.close(descriptor)


def _read_repository_file_windows(
    root: Path,
    relative: Path,
    expected_boundary: tuple[tuple[int, int], ...],
) -> str:
    _validate_repository_relative(relative)
    current_path = root
    handle = _win32_open_directory(root)
    try:
        if _validate_win32_directory_handle(handle).identity != expected_boundary[0]:
            raise OSError(errno.ESTALE, "repository root identity changed")
        for index, component in enumerate(relative.parts[:-1], start=1):
            matches = [child for child in _win32_memory_children(handle) if child.name == component]
            if len(matches) != 1:
                raise OSError(errno.ENOENT, "repository ancestor is missing")
            expected = matches[0]
            if stat.S_ISLNK(expected.mode) or not stat.S_ISDIR(expected.mode):
                raise OSError(errno.ENOTDIR, "repository ancestor is not a directory")
            if expected.file_attributes & WINDOWS_REPARSE_POINT:
                raise OSError(errno.ELOOP, "repository ancestor is a reparse point")

            current_path /= component
            child_handle = _win32_open_directory(current_path)
            try:
                actual = _validate_win32_directory_handle(child_handle)
                if actual.identity != expected.identity:
                    raise OSError(errno.ESTALE, "repository ancestor identity changed")
                if actual.identity != expected_boundary[index]:
                    raise OSError(errno.ESTALE, "repository ancestor changed after precheck")
            except BaseException:
                _win32_close_handle(child_handle)
                raise
            _win32_close_handle(handle)
            handle = child_handle

        matches = [child for child in _win32_memory_children(handle) if child.name == relative.name]
        if len(matches) != 1:
            raise OSError(errno.ENOENT, "repository instruction is missing")
        expected = matches[0]
        if stat.S_ISLNK(expected.mode) or not stat.S_ISREG(expected.mode):
            raise OSError(errno.EINVAL, "repository instruction is not a regular file")
        if expected.file_attributes & WINDOWS_REPARSE_POINT:
            raise OSError(errno.ELOOP, "repository instruction is a reparse point")
        if expected.identity != expected_boundary[-1]:
            raise OSError(errno.ESTALE, "repository instruction changed after precheck")
        result = _read_win32_memory_child(current_path, handle, expected)
        if result.link_count != 1 or result.text is None:
            raise OSError(errno.EINVAL, "repository instruction is not a unique regular file")
        return result.text
    finally:
        _win32_close_handle(handle)


def _read_repository_file(
    root: Path,
    relative: Path,
    expected_boundary: tuple[tuple[int, int], ...] | None = None,
) -> str | None:
    try:
        boundary = (
            expected_boundary if expected_boundary is not None else _capture_repository_file_boundary(root, relative)
        )
        if sys.platform == "win32":
            return _read_repository_file_windows(root, relative, boundary)
        return _read_repository_file_posix(root, relative, boundary)
    except OSError, UnicodeError:
        return None


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
        key = child.name
        is_reparse = stat.S_ISLNK(child.mode) or bool(child.file_attributes & WINDOWS_REPARSE_POINT)
        if is_reparse or (stat.S_ISREG(child.mode) and child.link_count != 1):
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
        try:
            expected_boundary = _capture_repository_file_boundary(root, relative)
        except OSError:
            issues.append(f"MEMORY_INSTRUCTION_POINTER: {relative.as_posix()}: instruction path boundary")
            continue
        text = _read_repository_file(root, relative, expected_boundary)
        if text is None:
            issues.append(f"MEMORY_INSTRUCTION_POINTER: {relative.as_posix()}: instruction path boundary")
            continue
        normalized = " ".join(text.lower().split())
        for label, pattern in concepts:
            if re.search(pattern, normalized) is None:
                issues.append(f"MEMORY_INSTRUCTION_POINTER: {relative.as_posix()}: {label}")
    return issues


def _validate_memory(root: Path) -> tuple[list[str], int]:
    root = root.absolute()
    memory = root / MEMORY_RELATIVE
    readme_path = root / README_RELATIVE

    try:
        expected_boundary = _capture_memory_boundary(root)
        snapshot = _snapshot_memory(root, expected_boundary)
    except OSError, UnicodeError:
        return [_diagnostic("MEMORY_TREE_SCAN", memory, root)], 0

    children_by_name: dict[str, list[_MemoryChild]] = {}
    for child in snapshot.children:
        children_by_name.setdefault(child.name, []).append(child)

    readme_matches = children_by_name.get("README.md", [])
    if len(readme_matches) != 1:
        return [_diagnostic("MEMORY_INDEX_LINK_MISSING", readme_path, root)], 0
    readme_child = readme_matches[0]
    readme_reparse = stat.S_ISLNK(readme_child.mode) or bool(readme_child.file_attributes & WINDOWS_REPARSE_POINT)
    if readme_reparse:
        return [_diagnostic("MEMORY_INDEX_LINK_INVALID", readme_path, root)], 0
    if readme_child.link_count != 1:
        return [_diagnostic("MEMORY_INDEX_LINK_INVALID", readme_path, root)], 0
    if not stat.S_ISREG(readme_child.mode) or readme_child.text is None:
        return [_diagnostic("MEMORY_INDEX_LINK_MISSING", readme_path, root)], 0
    readme = readme_child.text

    index = _index_body(readme)
    if index is None:
        return [_diagnostic("MEMORY_INDEX_LINK_INVALID", readme_path, root)], 0

    issues: list[str] = []
    indexed_names: dict[str, tuple[str, int]] = {}
    indexed_entry_names: set[str] = set()
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
        key = raw_target
        if key == "README.md":
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
        if child.link_count != 1:
            issues.append(_diagnostic("MEMORY_INDEX_LINK_INVALID", candidate, root))
            blocked_entries.add(key)
            continue
        if not stat.S_ISREG(child.mode):
            issues.append(_diagnostic("MEMORY_INDEX_LINK_MISSING", candidate, root))
            continue
        if child.identity == readme_child.identity:
            issues.append(_diagnostic("MEMORY_INDEX_LINK_INVALID", readme_path, root))
            continue
        indexed_entry_names.add(key)
        if child.text is None or not _entry_has_schema(child.text):
            issues.append(_diagnostic("MEMORY_ENTRY_SCHEMA", candidate, root))

    entries, scan_issues = _scan_memory_tree(memory, root, blocked_entries, snapshot.children)
    issues.extend(scan_issues)

    for entry in entries:
        path = memory / entry.name
        if entry is readme_child:
            continue
        key = entry.name
        if key not in indexed_entry_names:
            issues.append(_diagnostic("MEMORY_ENTRY_UNINDEXED", path, root))
        if KEBAB_MARKDOWN.fullmatch(entry.name) is None:
            issues.append(_diagnostic("MEMORY_ENTRY_FILENAME", path, root))
        if key not in indexed_entry_names and (entry.text is None or not _entry_has_schema(entry.text)):
            issues.append(_diagnostic("MEMORY_ENTRY_SCHEMA", path, root))

    issues.extend(_validate_instruction_pointers(root))
    return issues, len(indexed_names)


def validate_memory(root: Path) -> list[str]:
    """Return sanitized, fail-closed findings for the repository memory tree."""

    issues, _ = _validate_memory(root)
    return issues


def main() -> int:
    if len(sys.argv) > 2:
        print("usage: validate_agent_memory.py [repository-root]", file=sys.stderr)
        return 2
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
