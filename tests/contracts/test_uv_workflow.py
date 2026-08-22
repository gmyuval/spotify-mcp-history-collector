"""Contract tests for the reproducible uv development workflow."""

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class UvWorkflowContractTests(unittest.TestCase):
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
