"""Dependency-free contract checks for the production deployment workflow."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy.yml"


class DeploymentWorkflowContractTests(unittest.TestCase):
    def test_production_deploy_is_manual_and_uses_a_verified_immutable_sha(self) -> None:
        """A production deploy may use only an origin/main-reachable commit SHA."""
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertRegex(
            workflow,
            r"(?m)^\s{2}workflow_dispatch:\s*$",
            "production deployment must be manually dispatched",
        )
        self.assertNotRegex(
            workflow,
            r"(?m)^\s{2}(?:push|pull_request):",
            "a push or pull request must not trigger a production deployment",
        )
        commit_sha_input = re.search(r"(?m)^\s{6}commit_sha:\s*\n(?P<body>(?:^\s{8}.*\n)+)", workflow)
        self.assertIsNotNone(commit_sha_input, "manual dispatch must define commit_sha")
        assert commit_sha_input is not None
        self.assertIn(
            "required: true",
            commit_sha_input.group("body"),
            "manual dispatch must require a commit_sha input",
        )
        self.assertNotIn(
            "default:",
            commit_sha_input.group("body"),
            "the deploy SHA must not default to a branch, tag, or checkout",
        )
        self.assertEqual(
            workflow.count("ref: ${{ inputs.commit_sha }}"),
            6,
            "each existing lint, typecheck, and service-test gate must use the SHA",
        )
        self.assertIn(
            "needs: [validate-deploy-sha, lint, typecheck, test-api, test-collector, test-frontend, test-explorer]",
            workflow,
            "production mutation must wait for SHA validation and every existing gate",
        )
        self.assertIn(
            '[[ "$DEPLOY_SHA" =~ ^[0-9a-fA-F]{40}$ ]]',
            workflow,
            "the workflow must reject non-40-character hexadecimal inputs",
        )
        self.assertRegex(
            workflow,
            r"git fetch origin main",
            "the deployment host must refresh origin/main before validation",
        )
        self.assertRegex(
            workflow,
            r"git cat-file -e \"\$DEPLOY_SHA\^\{commit\}\"",
            "the deployment host must reject a SHA that is not a commit",
        )
        self.assertRegex(
            workflow,
            r"git merge-base --is-ancestor \"\$DEPLOY_SHA\" origin/main",
            "the deployment host must reject commits outside origin/main",
        )
        self.assertRegex(
            workflow,
            r"git checkout --detach \"\$DEPLOY_SHA\"",
            "the deployment host must deploy a detached immutable revision",
        )
        self.assertRegex(
            workflow,
            r"PREVIOUS_PRODUCTION_SHA=\$\(git rev-parse HEAD\)",
            "the previous production revision must be captured before checkout",
        )
        self.assertRegex(
            workflow,
            r"GITHUB_STEP_SUMMARY",
            "the workflow must publish deployment and rollback evidence",
        )
        for summary_field in (
            "Requested SHA:",
            "Previous production SHA:",
            "Environment: production",
            "Terminal health result:",
            "Rollback posture:",
        ):
            self.assertIn(
                summary_field,
                workflow,
                f"the job summary must include {summary_field}",
            )


if __name__ == "__main__":
    unittest.main()
