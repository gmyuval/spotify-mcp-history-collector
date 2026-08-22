"""Maintain the temporary pip-tools lock consumed by production Dockerfiles.

SPM-4 owns the decision to replace this path with direct ``uv.lock``
consumption or uv exports. Until then, this script keeps package metadata and
the committed pip-tools outputs tied together without changing Docker build
contexts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "docker-requirements.lock"
SCRATCH_ROOT = ROOT / "build" / "docker-requirements"
WORKSPACE_DEPENDENCIES = {
    "spotify-history-collector",
    "spotify-mcp-api",
    "spotify-mcp-explorer",
    "spotify-mcp-frontend",
    "spotify-mcp-shared",
}


@dataclass(frozen=True)
class RequirementSet:
    package_dir: str
    runtime_output: str
    dev_output: str | None = None


REQUIREMENT_SETS = (
    RequirementSet("services/shared", "services/shared/requirements.txt"),
    RequirementSet(
        "services/api",
        "services/api/requirements.txt",
        "services/api/requirements-dev.txt",
    ),
    RequirementSet(
        "services/collector",
        "services/collector/requirements.txt",
        "services/collector/requirements-dev.txt",
    ),
    RequirementSet(
        "services/frontend",
        "services/frontend/requirements.txt",
        "services/frontend/requirements-dev.txt",
    ),
    RequirementSet(
        "services/explorer",
        "services/explorer/requirements.txt",
        "services/explorer/requirements-dev.txt",
    ),
)


def _normalise_name(requirement: str) -> str:
    match = re.match(r"[A-Za-z0-9_.-]+", requirement)
    if match is None:
        raise ValueError(f"cannot parse requirement name: {requirement!r}")
    return match.group(0).lower().replace("_", "-")


def _load_project(specification: RequirementSet) -> dict[str, object]:
    path = ROOT / specification.package_dir / "pyproject.toml"
    with path.open("rb") as stream:
        return tomllib.load(stream)


def _external_requirements(
    specification: RequirementSet,
    *,
    include_dev: bool,
) -> list[str]:
    config = _load_project(specification)
    project = config.get("project")
    if not isinstance(project, dict):
        raise ValueError(f"{specification.package_dir}/pyproject.toml has no [project]")

    raw_requirements = project.get("dependencies", [])
    if not isinstance(raw_requirements, list):
        raise ValueError(f"{specification.package_dir}: dependencies must be a list")
    requirements = [item for item in raw_requirements if isinstance(item, str)]

    if include_dev:
        optional = project.get("optional-dependencies", {})
        if isinstance(optional, dict):
            raw_dev = optional.get("dev", [])
            if isinstance(raw_dev, list):
                requirements.extend(item for item in raw_dev if isinstance(item, str))

    external = {
        _normalise_name(requirement): requirement
        for requirement in requirements
        if _normalise_name(requirement) not in WORKSPACE_DEPENDENCIES
    }
    return [external[name] for name in sorted(external)]


def _pinned_names(relative_path: str) -> set[str]:
    names: set[str] = set()
    for line in (ROOT / relative_path).read_text(encoding="utf-8").splitlines():
        match = re.match(r"([A-Za-z0-9_.-]+)(?:\[[^]]+\])?==", line)
        if match is not None:
            names.add(match.group(1).lower().replace("_", "-"))
    return names


def _validate_direct_dependencies() -> list[str]:
    issues: list[str] = []
    for specification in REQUIREMENT_SETS:
        pairs = [(False, specification.runtime_output)]
        if specification.dev_output is not None:
            pairs.append((True, specification.dev_output))
        for include_dev, output in pairs:
            expected = {
                _normalise_name(requirement)
                for requirement in _external_requirements(
                    specification,
                    include_dev=include_dev,
                )
            }
            missing = sorted(expected - _pinned_names(output))
            if missing:
                issues.append(f"{output}: missing direct dependencies {', '.join(missing)}")
    return issues


def _tracked_paths() -> tuple[str, ...]:
    paths = ["uv.lock", *(f"{item.package_dir}/pyproject.toml" for item in REQUIREMENT_SETS)]
    for item in REQUIREMENT_SETS:
        paths.append(item.runtime_output)
        if item.dev_output is not None:
            paths.append(item.dev_output)
    return tuple(sorted(paths))


def _sha256(relative_path: str) -> str:
    return hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest()


def _manifest() -> dict[str, object]:
    return {
        "format": 1,
        "generator": "pip-tools 7.5.3 via uv.lock",
        "python": "3.14.7",
        "known-direct-gaps": _validate_direct_dependencies(),
        "files": {relative_path: _sha256(relative_path) for relative_path in _tracked_paths()},
    }


def _record_manifest() -> None:
    MANIFEST_PATH.write_text(
        json.dumps(_manifest(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _check_manifest() -> list[str]:
    issues: list[str] = []
    try:
        recorded = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [*issues, f"docker-requirements.lock: {exc}"]

    expected = _manifest()
    if recorded.get("format") != expected["format"]:
        issues.append("docker-requirements.lock: unsupported format")
    if recorded.get("generator") != expected["generator"]:
        issues.append("docker-requirements.lock: generator drift")
    if recorded.get("python") != expected["python"]:
        issues.append("docker-requirements.lock: Python drift")
    if recorded.get("known-direct-gaps") != expected["known-direct-gaps"]:
        issues.append("docker-requirements.lock: direct dependency gap set drift")

    recorded_files = recorded.get("files")
    if not isinstance(recorded_files, dict):
        issues.append("docker-requirements.lock: missing files map")
        return issues
    expected_files = expected["files"]
    assert isinstance(expected_files, dict)
    if set(recorded_files) != set(expected_files):
        issues.append("docker-requirements.lock: tracked file inventory drift")
    for relative_path, digest in expected_files.items():
        if recorded_files.get(relative_path) != digest:
            issues.append(f"docker-requirements.lock: stale {relative_path}")
    return issues


def _write_input(specification: RequirementSet, *, include_dev: bool) -> Path:
    suffix = "-dev" if include_dev else ""
    name = Path(specification.package_dir).name
    path = SCRATCH_ROOT / f"{name}{suffix}.in"
    path.parent.mkdir(parents=True, exist_ok=True)
    requirements = _external_requirements(specification, include_dev=include_dev)
    path.write_text("\n".join(requirements) + "\n", encoding="utf-8")
    return path


def _compile_output(
    specification: RequirementSet,
    *,
    include_dev: bool,
    output: str,
    upgrade: bool,
) -> None:
    input_path = _write_input(specification, include_dev=include_dev)
    command = [
        sys.executable,
        "-m",
        "piptools",
        "compile",
        "--strip-extras",
        f"--output-file={output}",
    ]
    if upgrade:
        command.append("--upgrade")
    command.append(str(input_path.relative_to(ROOT)))
    subprocess.run(command, cwd=ROOT, check=True)


def _compile_all(*, upgrade: bool) -> None:
    try:
        for specification in REQUIREMENT_SETS:
            _compile_output(
                specification,
                include_dev=False,
                output=specification.runtime_output,
                upgrade=upgrade,
            )
            if specification.dev_output is not None:
                _compile_output(
                    specification,
                    include_dev=True,
                    output=specification.dev_output,
                    upgrade=upgrade,
                )
        _record_manifest()
    finally:
        shutil.rmtree(SCRATCH_ROOT, ignore_errors=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--record", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--upgrade", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        if args.check:
            issues = _check_manifest()
            if issues:
                for issue in issues:
                    print(issue)
                return 1
            print("Docker requirements match their recorded package metadata.")
            return 0
        if args.record:
            _record_manifest()
            print("Recorded the current temporary Docker requirements boundary.")
            return 0
        _compile_all(upgrade=args.upgrade)
    except (OSError, RuntimeError, subprocess.CalledProcessError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print("Compiled Docker requirements and refreshed docker-requirements.lock.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
