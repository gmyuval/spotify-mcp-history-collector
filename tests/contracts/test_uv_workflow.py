"""Contract tests for the reproducible uv development workflow."""

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import compile_docker_requirements as docker_requirements
from scripts import validate_uv_workflow as uv_workflow

ROOT: Path = Path(__file__).resolve().parents[2]


def _pinned_requirements(path: Path) -> dict[str, tuple[str, str | None]]:
    pins: dict[str, tuple[str, str | None]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)(?:\[[^]]+\])?==([^;\s]+)(?:\s*;\s*(.+))?", line)
        if match is not None:
            pins[match.group(1).lower().replace("_", "-")] = (match.group(2), match.group(3))
    return pins


class UvWorkflowContractTests(unittest.TestCase):
    def test_action_parser_includes_named_uses_steps(self) -> None:
        workflow = """\
steps:
  - name: Named action
    uses: example/named@v1
  - uses: example/direct@0123456789012345678901234567890123456789
"""
        self.assertEqual(
            [
                "example/named@v1",
                "example/direct@0123456789012345678901234567890123456789",
            ],
            uv_workflow._action_refs(workflow),
        )

    def test_checkout_credentials_scan_does_not_cross_job_boundary(self) -> None:
        workflow = f"""\
jobs:
  unsafe:
    steps:
      - uses: {uv_workflow.CHECKOUT_ACTION}
  unrelated:
    steps:
      - name: Not a checkout step
        with:
          persist-credentials: false
"""
        self.assertEqual([1], uv_workflow._checkout_steps_missing_credentials(workflow))

    def test_checkout_credentials_scan_ignores_nested_block_scalar_text(self) -> None:
        workflow = f"""\
jobs:
  safe:
    steps:
      - uses: {uv_workflow.CHECKOUT_ACTION}
        with:
          persist-credentials: false
  unsafe:
    steps:
      - uses: {uv_workflow.CHECKOUT_ACTION}
        with:
          sparse-checkout: |
            persist-credentials: false
  nested-with:
    steps:
      - uses: {uv_workflow.CHECKOUT_ACTION}
        env:
          with:
            persist-credentials: false
"""

        self.assertEqual([2, 3], uv_workflow._checkout_steps_missing_credentials(workflow))

    def test_ci_uses_read_only_checkout_and_immutable_action_refs(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

        self.assertRegex(workflow, r"(?m)^permissions:\n  contents: read\s*$")
        self.assertEqual([], uv_workflow._elevated_permissions(workflow))
        action_refs = uv_workflow._action_refs(workflow)
        self.assertGreater(len(action_refs), 0)
        for action_ref in action_refs:
            self.assertRegex(action_ref, r"^[^@\s]+@[0-9a-f]{40}$")

        checkout_count = sum(action_ref.startswith("actions/checkout@") for action_ref in action_refs)
        self.assertGreater(checkout_count, 0)
        self.assertEqual(checkout_count, workflow.count("persist-credentials: false"))

    def test_ci_permissions_scan_rejects_job_level_write_access(self) -> None:
        workflow = """\
permissions:
  contents: read
jobs:
  unsafe:
    permissions:
      contents: read
      id-token: write
  also-unsafe:
    permissions: write-all
"""

        self.assertEqual(
            ["id-token: write", "permissions: write-all"],
            uv_workflow._elevated_permissions(workflow),
        )

    def test_ci_permissions_scan_rejects_flow_map_write_access(self) -> None:
        workflow = """\
jobs:
  inline:
    permissions: {contents: read, id-token: write}
  multiline:
    permissions: {
      contents: write,
      issues: read
    }
  quoted:
    permissions: {"packages": "write-all"}
"""

        self.assertEqual(
            ["id-token: write", "contents: write", "packages: write-all"],
            uv_workflow._elevated_permissions(workflow),
        )

    def test_ci_permissions_scan_rejects_quoted_keys_and_values(self) -> None:
        workflow = """\
jobs:
  block:
    "permissions":
      "id-token": "write"
  flow:
    'permissions': {'contents': 'write'}
  scalar:
    "permissions": "write-all"
"""

        self.assertEqual(
            ["contents: write", "id-token: write", "permissions: write-all"],
            uv_workflow._elevated_permissions(workflow),
        )

    def test_conda_scan_distinguishes_words_that_contain_conda(self) -> None:
        for text in ("secondary", "secondary-cache", "preconditionals"):
            with self.subTest(text=text):
                self.assertIsNone(uv_workflow.CONDA_REFERENCE.search(text))
        for text in ("conda", "Miniconda", "Anaconda", "Anaconda3", "C:/tools/.conda/envs"):
            with self.subTest(text=text):
                self.assertIsNotNone(uv_workflow.CONDA_REFERENCE.search(text))

    def test_conda_retirement_reads_settings_once(self) -> None:
        issues: list[str] = []
        with mock.patch.object(uv_workflow, "_read_text", return_value="{}") as read_text:
            uv_workflow._check_conda_retirement(ROOT, issues)

        settings_calls = [call for call in read_text.call_args_list if call.args[1] == ".claude/settings.local.json"]
        self.assertEqual(1, len(settings_calls))

    def test_repository_uv_workflow_is_valid(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "validate_uv_workflow.py")],
            cwd=ROOT,
            capture_output=True,
            check=False,
            text=True,
        )

        self.assertEqual(
            0,
            completed.returncode,
            completed.stdout + completed.stderr,
        )

    def test_docker_requirements_match_package_metadata(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "compile_docker_requirements.py"),
                "--check",
            ],
            cwd=ROOT,
            capture_output=True,
            check=False,
            text=True,
        )

        self.assertEqual(
            0,
            completed.returncode,
            completed.stdout + completed.stderr,
        )

    def test_non_object_docker_manifest_returns_normal_failure(self) -> None:
        for manifest_content in ("[]\n", "null\n", '"text"\n', "1\n"):
            with self.subTest(manifest_content=manifest_content):
                with tempfile.TemporaryDirectory(dir=ROOT) as temporary_directory:
                    manifest_path = Path(temporary_directory) / "docker-requirements.lock"
                    manifest_path.write_text(manifest_content, encoding="utf-8")
                    with mock.patch.object(docker_requirements, "MANIFEST_PATH", manifest_path):
                        try:
                            issues = docker_requirements._check_manifest()
                        except Exception as exc:  # pragma: no cover - assertion records the regression clearly
                            self.fail(f"malformed manifest raised {type(exc).__name__}: {exc}")

                self.assertEqual(["docker-requirements.lock: manifest must be an object"], issues)

    def test_dev_requirement_compiles_are_constrained_by_runtime_lock(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary_directory:
            with (
                mock.patch.object(docker_requirements, "SCRATCH_ROOT", Path(temporary_directory) / "scratch"),
                mock.patch.object(docker_requirements, "_record_manifest"),
                mock.patch.object(docker_requirements.subprocess, "run") as run,
            ):
                docker_requirements._compile_all(upgrade=False)

        commands = [call.args[0] for call in run.call_args_list]
        for specification in docker_requirements.REQUIREMENT_SETS:
            runtime_command = next(
                command for command in commands if f"--output-file={specification.runtime_output}" in command
            )
            self.assertIn(f"--constraint={specification.runtime_output}", runtime_command)
            self.assertNotIn("--extra=dev", runtime_command)
            self.assertIn("--no-strip-extras", runtime_command)
            self.assertNotIn("\\", runtime_command[-1])
            self.assertEqual("pyproject.toml", Path(runtime_command[-1]).name)
            if specification.dev_output is None:
                continue
            dev_command = next(
                command for command in commands if f"--output-file={specification.dev_output}" in command
            )
            self.assertIn(f"--constraint={specification.runtime_output}", dev_command)
            self.assertIn("--extra=dev", dev_command)
            self.assertIn("--no-strip-extras", dev_command)
            self.assertNotIn("\\", dev_command[-1])
            self.assertEqual("pyproject.toml", Path(dev_command[-1]).name)

        for specification in docker_requirements.REQUIREMENT_SETS:
            outputs = [specification.runtime_output]
            if specification.dev_output is not None:
                outputs.append(specification.dev_output)
            for output in outputs:
                header = "\n".join((ROOT / output).read_text(encoding="utf-8").splitlines()[:7])
                with self.subTest(output=output):
                    self.assertNotIn("\\", header)

    def test_targeted_upgrades_release_only_the_runtime_self_constraint(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary_directory:
            with (
                mock.patch.object(docker_requirements, "SCRATCH_ROOT", Path(temporary_directory) / "scratch"),
                mock.patch.object(docker_requirements, "_record_manifest"),
                mock.patch.object(docker_requirements.subprocess, "run") as run,
            ):
                docker_requirements._compile_all(
                    upgrade=False,
                    upgrade_packages=("idna", "Mako"),
                )

        commands = [call.args[0] for call in run.call_args_list]
        for specification in docker_requirements.REQUIREMENT_SETS:
            runtime_command = next(
                command for command in commands if f"--output-file={specification.runtime_output}" in command
            )
            self.assertNotIn(f"--constraint={specification.runtime_output}", runtime_command)
            self.assertIn("--upgrade-package=idna", runtime_command)
            self.assertIn("--upgrade-package=Mako", runtime_command)
            if specification.dev_output is None:
                continue
            dev_command = next(
                command for command in commands if f"--output-file={specification.dev_output}" in command
            )
            self.assertIn(f"--constraint={specification.runtime_output}", dev_command)
            self.assertIn("--upgrade-package=idna", dev_command)
            self.assertIn("--upgrade-package=Mako", dev_command)

    def test_dev_requirement_outputs_retain_runtime_pins_and_markers(self) -> None:
        for specification in docker_requirements.REQUIREMENT_SETS:
            if specification.dev_output is None:
                continue
            runtime_pins = _pinned_requirements(ROOT / specification.runtime_output)
            dev_pins = _pinned_requirements(ROOT / specification.dev_output)
            for package, runtime_pin in runtime_pins.items():
                with self.subTest(output=specification.dev_output, package=package):
                    self.assertEqual(runtime_pin, dev_pins.get(package))

        for output in ("services/api/requirements.txt", "services/api/requirements-dev.txt"):
            requirements = (ROOT / output).read_text(encoding="utf-8")
            self.assertRegex(requirements, r'(?m)^pywin32==\d+ ; sys_platform == "win32"$')
            self.assertRegex(requirements, r"(?m)^pyjwt\[crypto\]==[^\s]+$")
            self.assertRegex(requirements, r"(?m)^uvicorn\[standard\]==[^\s]+$")
        self.assertRegex(
            (ROOT / "services/collector/requirements-dev.txt").read_text(encoding="utf-8"),
            r"(?m)^coverage\[toml\]==[^\s]+$",
        )

    def test_generated_requirement_project_preserves_external_requirement_syntax(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary_directory:
            with mock.patch.object(
                docker_requirements,
                "SCRATCH_ROOT",
                Path(temporary_directory) / "scratch",
            ):
                project_path = docker_requirements._write_project_input(docker_requirements.REQUIREMENT_SETS[1])
                project = project_path.read_text(encoding="utf-8")

        self.assertIn('"uvicorn[standard]>=0.32.0"', project)
        self.assertIn('"types-python-dateutil"', project)
        self.assertNotIn('"spotify-mcp-shared"', project)

    def test_dev_marker_source_merges_runtime_and_dev_markers(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary_directory:
            root = Path(temporary_directory)
            runtime_path = root / "requirements.txt"
            dev_path = root / "requirements-dev.txt"
            runtime_path.write_text(
                'common==1 ; python_version >= "3.14"\n',
                encoding="utf-8",
            )
            dev_path.write_text(
                'common==2 ; python_version >= "3.14"\ndev-only==3 ; sys_platform == "win32"\n',
                encoding="utf-8",
            )

            retained = docker_requirements._retained_marked_requirements(
                output_path=dev_path,
                runtime_constraint_path=runtime_path,
            )

        self.assertEqual(
            {
                "common": 'common==2 ; python_version >= "3.14"',
                "dev-only": 'dev-only==3 ; sys_platform == "win32"',
            },
            retained,
        )

    def test_missing_or_non_file_requirement_outputs_have_no_retained_markers(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary_directory:
            root = Path(temporary_directory)
            retained = docker_requirements._retained_marked_requirements(
                output_path=root / "requirements-dev.txt",
                runtime_constraint_path=root / "requirements.txt",
            )
            directory_output = root / "directory-requirements.txt"
            directory_output.mkdir()
            marked_directory = docker_requirements._marked_requirements(directory_output)

        self.assertEqual({}, retained)
        self.assertEqual({}, marked_directory)

    def test_docker_requirements_exclude_known_vulnerable_pins(self) -> None:
        for specification in docker_requirements.REQUIREMENT_SETS:
            outputs = [specification.runtime_output]
            if specification.dev_output is not None:
                outputs.append(specification.dev_output)
            for output in outputs:
                pins = _pinned_requirements(ROOT / output)
                minimum_versions = {"idna": (3, 15)}
                if output.startswith("services/api/"):
                    minimum_versions["mako"] = (1, 3, 12)
                for package, minimum in minimum_versions.items():
                    with self.subTest(output=output, package=package):
                        self.assertIn(package, pins)
                        version = tuple(int(part) for part in pins[package][0].split("."))
                        self.assertGreaterEqual(version, minimum)

    def test_marker_constraints_preserve_environment_marker_without_freezing_version(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary_directory:
            output_path = Path(temporary_directory) / "requirements.txt"
            output_path.write_text(
                'pywin32==311 ; sys_platform == "win32"\nhttpx==0.28.1\n',
                encoding="utf-8",
            )
            with mock.patch.object(
                docker_requirements,
                "SCRATCH_ROOT",
                Path(temporary_directory) / "scratch",
            ):
                constraint_path = docker_requirements._write_marker_constraints(output_path)

            self.assertIsNotNone(constraint_path)
            assert constraint_path is not None
            self.assertEqual(
                'pywin32 ; sys_platform == "win32"\n',
                constraint_path.read_text(encoding="utf-8"),
            )

    def test_manifest_digest_normalizes_checkout_line_endings(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary_directory:
            root = Path(temporary_directory)
            tracked_path = root / "requirements.txt"
            with mock.patch.object(docker_requirements, "ROOT", root):
                tracked_path.write_bytes(b"httpx==0.28.1\r\n")
                windows_digest = docker_requirements._sha256("requirements.txt")
                tracked_path.write_bytes(b"httpx==0.28.1\n")
                linux_digest = docker_requirements._sha256("requirements.txt")

        self.assertEqual(windows_digest, linux_digest)

    def test_marked_requirements_are_restored_after_host_specific_resolution(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary_directory:
            output_path = Path(temporary_directory) / "requirements.txt"
            output_path.write_text(
                "httpx==0.28.1\npywin32==312\npyyaml==6.0.3\n",
                encoding="utf-8",
            )
            docker_requirements._restore_marked_requirements(
                output_path,
                {"pywin32": 'pywin32==311 ; sys_platform == "win32"'},
            )

            self.assertEqual(
                "httpx==0.28.1\n"
                'pywin32==312 ; sys_platform == "win32"\n'
                "    # retained from committed cross-platform marker set\n"
                "pyyaml==6.0.3\n",
                output_path.read_text(encoding="utf-8"),
            )
            self.assertNotIn(b"\r\n", output_path.read_bytes())

            output_path.write_text("httpx==0.28.1\npyyaml==6.0.3\n", encoding="utf-8")
            docker_requirements._restore_marked_requirements(
                output_path,
                {"pywin32": 'pywin32==311 ; sys_platform == "win32"'},
            )
            self.assertIn(
                'pywin32==311 ; sys_platform == "win32"\n',
                output_path.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
