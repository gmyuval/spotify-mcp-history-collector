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

ROOT = Path(__file__).resolve().parents[2]


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

    def test_ci_uses_read_only_checkout_and_immutable_action_refs(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

        self.assertRegex(workflow, r"(?m)^permissions:\n  contents: read\s*$")
        action_refs = uv_workflow._action_refs(workflow)
        self.assertGreater(len(action_refs), 0)
        for action_ref in action_refs:
            self.assertRegex(action_ref, r"^[^@\s]+@[0-9a-f]{40}$")

        checkout_count = sum(action_ref.startswith("actions/checkout@") for action_ref in action_refs)
        self.assertGreater(checkout_count, 0)
        self.assertEqual(checkout_count, workflow.count("persist-credentials: false"))

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
            self.assertEqual("pyproject.toml", Path(runtime_command[-1]).name)
            if specification.dev_output is None:
                continue
            dev_command = next(
                command for command in commands if f"--output-file={specification.dev_output}" in command
            )
            self.assertIn(f"--constraint={specification.runtime_output}", dev_command)
            self.assertIn("--extra=dev", dev_command)
            self.assertIn("--no-strip-extras", dev_command)
            self.assertEqual("pyproject.toml", Path(dev_command[-1]).name)

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
