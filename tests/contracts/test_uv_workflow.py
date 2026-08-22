"""Contract tests for the reproducible uv development workflow."""

import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class UvWorkflowContractTests(unittest.TestCase):
    def test_ci_uses_read_only_checkout_and_immutable_action_refs(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

        self.assertRegex(workflow, r"(?m)^permissions:\n  contents: read\s*$")
        action_refs = re.findall(r"(?m)^\s*-\s+uses:\s+([^\s#]+)", workflow)
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


if __name__ == "__main__":
    unittest.main()
