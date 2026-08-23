"""Dependency-free validation for the repository's pinned uv workflow."""

import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

PYTHON_VERSION = "3.14.7"
UV_VERSION = "0.12.3"
SETUP_UV_ACTION = "astral-sh/setup-uv@37802adc94f370d6bfd71619e3f0bf239e1f3b78"
CHECKOUT_ACTION = "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803"
WORKSPACE_PACKAGES = {
    "spotify-mcp-api": "services/api",
    "spotify-history-collector": "services/collector",
    "spotify-mcp-explorer": "services/explorer",
    "spotify-mcp-frontend": "services/frontend",
    "spotify-mcp-shared": "services/shared",
}
LOCKED_SYNC = "uv sync --locked --all-packages --all-extras --all-groups"
TYPECHECK_PATHS = (
    "services/shared/src services/api/src services/collector/src services/frontend/src services/explorer/src"
)
CONDA_REFERENCE: re.Pattern[str] = re.compile(r"(?i)\b(?:(?:mini)?conda|anaconda3?)\b|(?<!\w)\.conda\b")


def _issue(code: str, detail: str) -> str:
    return f"{code}: {detail}"


def _read_text(root: Path, relative_path: str, issues: list[str]) -> str | None:
    path = root / relative_path
    try:
        return path.read_text(encoding="utf-8").replace("\r\n", "\n")
    except (OSError, UnicodeError) as exc:
        issues.append(_issue("UV_FILE_UNREADABLE", f"{relative_path}: {exc}"))
        return None


def _read_toml(root: Path, relative_path: str, issues: list[str]) -> dict[str, Any] | None:
    text = _read_text(root, relative_path, issues)
    if text is None:
        return None
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        issues.append(_issue("UV_TOML_INVALID", f"{relative_path}: {exc}"))
        return None


def _dependency_names(requirements: object) -> set[str]:
    if not isinstance(requirements, list):
        return set()
    names: set[str] = set()
    for requirement in requirements:
        if not isinstance(requirement, str):
            continue
        match = re.match(r"[A-Za-z0-9_.-]+", requirement)
        if match is not None:
            names.add(match.group(0).lower().replace("_", "-"))
    return names


def _action_refs(workflow: str) -> list[str]:
    return re.findall(r"(?m)^\s*(?:-\s+)?uses:\s+([^\s#]+)", workflow)


def _checkout_steps_missing_credentials(workflow: str) -> list[int]:
    missing: list[int] = []
    checkout_count = 0
    workflow_lines = workflow.splitlines()
    for line_number, line in enumerate(workflow_lines):
        if CHECKOUT_ACTION not in line:
            continue
        checkout_count += 1
        step_indent = len(line) - len(line.lstrip())
        step_lines: list[str] = []
        for following_line in workflow_lines[line_number + 1 :]:
            if not following_line.strip():
                continue
            following_indent = len(following_line) - len(following_line.lstrip())
            if following_indent < step_indent:
                break
            if following_indent == step_indent and following_line.lstrip().startswith("- "):
                break
            step_lines.append(following_line)
        step_key_indent: int | None = min(
            (
                len(step_line) - len(step_line.lstrip())
                for step_line in step_lines
                if step_line.strip() and not step_line.lstrip().startswith("#")
            ),
            default=None,
        )
        with_indent: int | None = None
        input_indent: int | None = None
        credentials_disabled = False
        for step_line in step_lines:
            stripped = step_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            indent = len(step_line) - len(step_line.lstrip())
            if with_indent is None:
                if indent == step_key_indent and re.fullmatch(r"with:\s*(?:#.*)?", stripped):
                    with_indent = indent
                continue
            if indent <= with_indent:
                with_indent = None
                input_indent = None
                continue
            if input_indent is None:
                input_indent = indent
            if indent == input_indent and re.fullmatch(
                r"persist-credentials:\s*false(?:\s+#.*)?",
                stripped,
            ):
                credentials_disabled = True
                break
        if not credentials_disabled:
            missing.append(checkout_count)
    return missing


def _elevated_permissions(workflow: str) -> list[str]:
    elevated: list[str] = []
    for permissions in re.finditer(
        r"""(?ms)^[ \t]*(?:permissions|["']permissions["']):\s*\{(.*?)\}""",
        workflow,
    ):
        for entry in permissions.group(1).split(","):
            permission = re.fullmatch(
                r"""\s*["']?([A-Za-z][A-Za-z0-9_-]*)["']?\s*:\s*["']?(write|write-all)["']?\s*""",
                entry,
            )
            if permission is not None:
                elevated.append(f"{permission.group(1)}: {permission.group(2)}")

    permissions_indent: int | None = None
    for line in workflow.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip())
        if permissions_indent is not None and indent > permissions_indent:
            permission = re.fullmatch(
                r"""["']?([A-Za-z][A-Za-z0-9_-]*)["']?\s*:\s*["']?(write|write-all)["']?(?:\s+#.*)?""",
                stripped,
            )
            if permission is not None:
                elevated.append(f"{permission.group(1)}: {permission.group(2)}")
            continue

        permissions_indent = None
        permissions = re.fullmatch(
            r"""(?:permissions|["']permissions["']):\s*([^#\s]+)?(?:\s+#.*)?""",
            stripped,
        )
        if permissions is None:
            continue
        access = permissions.group(1)
        if access is not None:
            access = access.strip("'\"")
        if access is not None and re.fullmatch(
            r"[|>](?:[1-9][+-]?|[+-][1-9]?)?",
            access,
        ):
            elevated.append("permissions: block-scalar")
        elif access == "write-all":
            elevated.append("permissions: write-all")
        elif access is None:
            permissions_indent = indent

    return elevated


def _check_root_metadata(root: Path, issues: list[str]) -> None:
    python_pin = _read_text(root, ".python-version", issues)
    if python_pin is not None and python_pin.strip() != PYTHON_VERSION:
        issues.append(_issue("UV_PYTHON_PIN", f"expected {PYTHON_VERSION}"))

    config = _read_toml(root, "pyproject.toml", issues)
    if config is None:
        return

    project = config.get("project", {})
    if project.get("requires-python") != "==3.14.*":
        issues.append(_issue("UV_PYTHON_RANGE", "root requires-python must be ==3.14.*"))
    dependencies = _dependency_names(project.get("dependencies"))
    if dependencies != set(WORKSPACE_PACKAGES):
        issues.append(_issue("UV_ROOT_DEPENDENCIES", f"expected {sorted(WORKSPACE_PACKAGES)}"))

    uv = config.get("tool", {}).get("uv", {})
    if uv.get("required-version") != f"=={UV_VERSION}":
        issues.append(_issue("UV_TOOL_PIN", f"expected =={UV_VERSION}"))
    if uv.get("package") is not False:
        issues.append(_issue("UV_ROOT_PACKAGE", "workspace root must be non-package"))

    members = set(uv.get("workspace", {}).get("members", []))
    if members != set(WORKSPACE_PACKAGES.values()):
        issues.append(_issue("UV_WORKSPACE_MEMBERS", f"expected {sorted(WORKSPACE_PACKAGES.values())}"))
    sources = uv.get("sources", {})
    for package_name in WORKSPACE_PACKAGES:
        if sources.get(package_name) != {"workspace": True}:
            issues.append(_issue("UV_WORKSPACE_SOURCE", package_name))

    dev_dependencies = _dependency_names(config.get("dependency-groups", {}).get("dev"))
    required_dev = {"pip", "pip-tools", "pre-commit", "ruff", "mypy", "pytest"}
    missing_dev = sorted(required_dev - dev_dependencies)
    if missing_dev:
        issues.append(_issue("UV_DEV_DEPENDENCIES", ", ".join(missing_dev)))


def _check_member_metadata(root: Path, issues: list[str]) -> None:
    for package_name, relative_path in WORKSPACE_PACKAGES.items():
        config = _read_toml(root, f"{relative_path}/pyproject.toml", issues)
        if config is None:
            continue
        actual_name = config.get("project", {}).get("name")
        if actual_name != package_name:
            issues.append(_issue("UV_MEMBER_NAME", f"{relative_path}: {actual_name!r}"))

    for relative_path in ("services/api", "services/collector"):
        config = _read_toml(root, f"{relative_path}/pyproject.toml", issues)
        if config is None:
            continue
        dependencies = _dependency_names(config.get("project", {}).get("dependencies"))
        if "spotify-mcp-shared" not in dependencies:
            issues.append(_issue("UV_CROSS_WORKSPACE_DEPENDENCY", relative_path))


def _check_lock(root: Path, issues: list[str]) -> None:
    lock = _read_toml(root, "uv.lock", issues)
    if lock is None:
        return
    if lock.get("requires-python") != "==3.14.*":
        issues.append(_issue("UV_LOCK_PYTHON_RANGE", "uv.lock"))
    locked_names = {package.get("name") for package in lock.get("package", []) if isinstance(package, dict)}
    missing = sorted(set(WORKSPACE_PACKAGES) - locked_names)
    if missing:
        issues.append(_issue("UV_LOCK_WORKSPACE_PACKAGES", ", ".join(missing)))


def _check_commands(root: Path, issues: list[str]) -> None:
    makefile = _read_text(root, "Makefile", issues)
    if makefile is not None:
        required_fragments = (
            "setup:",
            LOCKED_SYNC,
            "lock-check:",
            "uv lock --check",
            "lint:",
            "uv run --locked ruff check .",
            "uv run --locked ruff format --check .",
            "format:",
            "typecheck:",
            f"uv run --locked mypy {TYPECHECK_PATHS}",
            "precommit:",
            "uv run --locked pre-commit run --all-files",
            "test-shared:",
            "test-api:",
            "test-collector:",
            "test-frontend:",
            "test-explorer:",
            "compose-config:",
            "uv run --locked python scripts/validate_compose.py",
        )
        for fragment in required_fragments:
            if fragment not in makefile:
                issues.append(_issue("UV_ROOT_COMMAND", fragment))

    workflow = _read_text(root, ".github/workflows/ci.yml", issues)
    if workflow is not None:
        required_fragments = (
            f"UV_VERSION: '{UV_VERSION}'",
            f"PYTHON_VERSION: '{PYTHON_VERSION}'",
            CHECKOUT_ACTION,
            SETUP_UV_ACTION,
            "version: ${{ env.UV_VERSION }}",
            "python-version: ${{ env.PYTHON_VERSION }}",
            LOCKED_SYNC,
            "uv lock --check",
            "uv run --locked python scripts/validate_compose.py",
            'uv run --locked python -m unittest discover -s tests/contracts -p "test_*.py"',
            "uv run --locked ruff check .",
            "uv run --locked ruff format --check .",
            f"uv run --locked mypy {TYPECHECK_PATHS}",
            "uv run --locked pre-commit run --all-files",
            "uv run --locked pytest services/shared/tests/",
            "uv run --locked pytest services/api/tests/",
            "uv run --locked pytest services/collector/tests/",
            "uv run --locked pytest services/frontend/tests/",
            "uv run --locked pytest services/explorer/tests/",
        )
        for fragment in required_fragments:
            if fragment not in workflow:
                issues.append(_issue("UV_CI_COMMAND", fragment))

        if re.search(r"(?m)^permissions:\n  contents: read\s*$", workflow) is None:
            issues.append(_issue("UV_CI_PERMISSIONS", "top-level contents: read"))
        for permission in _elevated_permissions(workflow):
            issues.append(_issue("UV_CI_PERMISSIONS_ELEVATED", permission))

        action_refs = _action_refs(workflow)
        for action_ref in action_refs:
            if re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", action_ref) is None:
                issues.append(_issue("UV_CI_ACTION_NOT_PINNED", action_ref))

        for checkout_number in _checkout_steps_missing_credentials(workflow):
            issues.append(_issue("UV_CI_CHECKOUT_CREDENTIALS", f"checkout step {checkout_number}"))

        for forbidden in ("actions/setup-python", "pip install"):
            if forbidden.lower() in workflow.lower():
                issues.append(_issue("UV_CI_BYPASS", forbidden))
        if CONDA_REFERENCE.search(workflow):
            issues.append(_issue("UV_CI_BYPASS", "conda"))

    precommit = _read_text(root, ".pre-commit-config.yaml", issues)
    if precommit is not None:
        for command in (
            "entry: uv run --locked ruff check --fix",
            "entry: uv run --locked ruff format",
            f"entry: uv run --locked mypy {TYPECHECK_PATHS}",
        ):
            if command not in precommit:
                issues.append(_issue("UV_PRECOMMIT_COMMAND", command))


def _check_conda_retirement(root: Path, issues: list[str]) -> None:
    if (root / "environment.yml").exists():
        issues.append(_issue("UV_CONDA_FILE", "environment.yml"))

    active_paths = (
        "CLAUDE.md",
        "README.md",
        "Makefile",
        ".github/workflows/ci.yml",
        ".pre-commit-config.yaml",
        ".claude/settings.local.json",
    )
    active_texts: dict[str, str | None] = {}
    for relative_path in active_paths:
        text = _read_text(root, relative_path, issues)
        active_texts[relative_path] = text
        if text is not None and CONDA_REFERENCE.search(text):
            issues.append(_issue("UV_CONDA_REFERENCE", relative_path))

    settings_text = active_texts[".claude/settings.local.json"]
    if settings_text is None:
        return
    try:
        settings = json.loads(settings_text)
    except json.JSONDecodeError as exc:
        issues.append(_issue("UV_SETTINGS_JSON", str(exc)))
        return
    allowed = settings.get("permissions", {}).get("allow", [])
    if "Bash(uv:*)" in allowed:
        issues.append(_issue("UV_PERMISSION_TOO_BROAD", "Bash(uv:*)"))


def _check_current_state(root: Path, issues: list[str]) -> None:
    current_state = _read_text(root, "docs/agent/current-state.md", issues)
    if current_state is None:
        return
    for required_fragment in (
        f"uv {UV_VERSION}",
        f"Python {PYTHON_VERSION}",
        LOCKED_SYNC,
        "docker-requirements.lock",
        "SPM-4",
        "No production health",
    ):
        if required_fragment not in current_state:
            issues.append(_issue("UV_CURRENT_STATE", required_fragment))


def _check_production_boundary(root: Path, issues: list[str]) -> None:
    docker_expectations = {
        "services/api/Dockerfile": (
            "COPY shared/requirements.txt ./shared_requirements.txt",
            "RUN pip install --no-cache-dir -r shared_requirements.txt",
            "COPY api/requirements.txt api/requirements-dev.txt ./",
            "RUN pip install --no-cache-dir -r requirements-dev.txt",
        ),
        "services/collector/Dockerfile": (
            "COPY shared/requirements.txt ./shared_requirements.txt",
            "RUN pip install --no-cache-dir -r shared_requirements.txt",
            "COPY collector/requirements.txt collector/requirements-dev.txt ./",
            "RUN pip install --no-cache-dir -r requirements-dev.txt",
        ),
        "services/frontend/Dockerfile": (
            "COPY requirements.txt requirements-dev.txt ./",
            "RUN pip install --no-cache-dir -r requirements-dev.txt",
        ),
        "services/explorer/Dockerfile": (
            "COPY requirements.txt ./",
            "RUN pip install --no-cache-dir -r requirements.txt",
        ),
    }
    for relative_path, fragments in docker_expectations.items():
        text = _read_text(root, relative_path, issues)
        if text is None:
            continue
        for fragment in fragments:
            if fragment not in text:
                issues.append(_issue("UV_DOCKER_BOUNDARY", f"{relative_path}: {fragment}"))
        if re.search(r"uv\.lock|uv sync|uv export", text, re.IGNORECASE):
            issues.append(_issue("UV_DOCKER_DECISION_LEAK", relative_path))

    compose_expectations = {
        "docker-compose.yml": (
            "context: ./services",
            "dockerfile: api/Dockerfile",
            "dockerfile: collector/Dockerfile",
            "context: ./services/frontend",
            "context: ./services/explorer",
        ),
        "docker-compose.prod.yml": (
            "context: ./services",
            "dockerfile: api/Dockerfile",
            "dockerfile: collector/Dockerfile",
            "context: ./services/frontend",
            "context: ./services/explorer",
        ),
    }
    for relative_path, fragments in compose_expectations.items():
        text = _read_text(root, relative_path, issues)
        if text is None:
            continue
        for fragment in fragments:
            if fragment not in text:
                issues.append(_issue("UV_COMPOSE_BOUNDARY", f"{relative_path}: {fragment}"))
        if "uv.lock" in text:
            issues.append(_issue("UV_COMPOSE_DECISION_LEAK", relative_path))

    requirement_paths = (
        "services/shared/requirements.txt",
        "services/api/requirements.txt",
        "services/api/requirements-dev.txt",
        "services/collector/requirements.txt",
        "services/collector/requirements-dev.txt",
        "services/frontend/requirements.txt",
        "services/frontend/requirements-dev.txt",
        "services/explorer/requirements.txt",
        "services/explorer/requirements-dev.txt",
    )
    for relative_path in requirement_paths:
        if not (root / relative_path).is_file():
            issues.append(_issue("UV_DOCKER_REQUIREMENTS_MISSING", relative_path))

    deploy = _read_text(root, ".github/workflows/deploy.yml", issues)
    if deploy is not None and re.search(r"uv\.lock|uv sync|uv export", deploy, re.IGNORECASE):
        issues.append(_issue("UV_DEPLOY_DECISION_LEAK", ".github/workflows/deploy.yml"))


def validate_uv_workflow(root: Path) -> list[str]:
    """Return fail-closed findings for the uv and temporary Docker contracts."""

    issues: list[str] = []
    _check_root_metadata(root, issues)
    _check_member_metadata(root, issues)
    _check_lock(root, issues)
    _check_commands(root, issues)
    _check_conda_retirement(root, issues)
    _check_current_state(root, issues)
    _check_production_boundary(root, issues)
    return issues


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    issues = validate_uv_workflow(root)
    if issues:
        for issue in issues:
            print(issue)
        return 1
    print(
        f"uv workflow OK (uv {UV_VERSION}, Python {PYTHON_VERSION}, "
        f"{len(WORKSPACE_PACKAGES)} workspace packages; Docker boundary preserved)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
