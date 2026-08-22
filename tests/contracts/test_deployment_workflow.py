"""Dependency-free contract checks for the production deployment workflow."""

import re
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy.yml"
RUNBOOK = Path(__file__).resolve().parents[2] / "docs" / "digitalocean-deployment.md"
PROVISION = Path(__file__).resolve().parents[2] / "deploy" / "provision.sh"
VALIDATION_GATES = (
    "lint",
    "typecheck",
    "test-api",
    "test-collector",
    "test-frontend",
    "test-explorer",
)


def mapping_body(document: str, key: str, indent: int = 0) -> str:
    """Return an indentation-delimited YAML mapping body without parsing YAML."""
    lines = document.splitlines(keepends=True)
    marker = f"{' ' * indent}{key}:"

    for start, line in enumerate(lines):
        if line.rstrip("\r\n") != marker:
            continue

        body = []
        for line in lines[start + 1 :]:
            stripped = line.strip()
            leading_spaces = len(line) - len(line.lstrip(" "))
            if stripped and leading_spaces <= indent:
                break
            body.append(line)
        return "".join(body)

    raise AssertionError(f"Missing mapping key {key!r} at indentation {indent}")


def direct_mapping_keys(body: str, indent: int) -> tuple[str, ...]:
    """Return only mapping keys at one exact indentation level."""
    pattern = re.compile(rf"^{' ' * indent}([A-Za-z0-9_-]+):(?:\s|$)", re.MULTILINE)
    return tuple(match.group(1) for match in pattern.finditer(body))


def mapping_value(document: str, key: str, indent: int) -> str:
    """Return the scalar value for one mapping key at an exact indentation."""
    pattern = re.compile(
        rf"^{' ' * indent}{re.escape(key)}:\s*(?P<value>[^#\r\n]*?)\s*$",
        re.MULTILINE,
    )
    match = pattern.search(document)
    if match is None:
        raise AssertionError(f"Missing scalar key {key!r} at indentation {indent}")
    return match.group("value")


def dependency_names(job: str) -> tuple[str, ...]:
    """Read a GitHub Actions needs scalar, inline list, or block sequence."""
    value = mapping_value(job, "needs", indent=4)
    if value.startswith("[") and value.endswith("]"):
        return tuple(item.strip() for item in value[1:-1].split(",") if item.strip())
    if value:
        return (value,)

    body = mapping_body(job, "needs", indent=4)
    return tuple(
        match.group("name") for match in re.finditer(r"^\s{6}-\s+(?P<name>[A-Za-z0-9_-]+)\s*$", body, re.MULTILINE)
    )


class DeploymentWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.runbook = RUNBOOK.read_text(encoding="utf-8")
        cls.provision = PROVISION.read_text(encoding="utf-8")
        cls.trigger_body = mapping_body(cls.workflow, "on")
        cls.jobs_body = mapping_body(cls.workflow, "jobs")

    def job_body(self, name: str) -> str:
        return mapping_body(self.jobs_body, name, indent=2)

    def job_needs(self, name: str) -> tuple[str, ...]:
        return dependency_names(self.job_body(name))

    def test_workflow_dispatch_is_the_only_trigger_and_requires_a_sha(self) -> None:
        self.assertEqual(
            direct_mapping_keys(self.trigger_body, 2),
            ("workflow_dispatch",),
            "production deployment must have workflow_dispatch as its only trigger",
        )
        dispatch_body = mapping_body(self.trigger_body, "workflow_dispatch", indent=2)
        inputs_body = mapping_body(dispatch_body, "inputs", indent=4)
        commit_sha_body = mapping_body(inputs_body, "commit_sha", indent=6)
        self.assertIn("required: true", commit_sha_body)
        self.assertNotIn("default:", commit_sha_body)
        self.assertIn(
            'run-name: "Deploy ${{ inputs.commit_sha }} to production"',
            self.workflow,
            "the run title must identify the immutable deployment SHA",
        )
        concurrency = mapping_body(self.workflow, "concurrency")
        self.assertIn("group: production-deployment", concurrency)
        self.assertIn("cancel-in-progress: false", concurrency)

    def test_production_jobs_keep_the_protected_environment(self) -> None:
        """Regression: removing environment protection must fail this contract."""
        for job in ("capture-production-state", "deploy"):
            self.assertIn("environment: production", self.job_body(job))

    def test_validation_gates_wait_for_sha_validation_and_test_that_sha(self) -> None:
        for gate in VALIDATION_GATES:
            gate_body = self.job_body(gate)
            self.assertIn(
                "validate-deploy-sha",
                self.job_needs(gate),
                f"{gate} must wait for SHA validation",
            )
            self.assertIn(
                "ref: ${{ inputs.commit_sha }}",
                gate_body,
                f"{gate} must test the requested immutable SHA",
            )

        sha_validation = self.job_body("validate-deploy-sha")
        self.assertIn('[[ "$DEPLOY_SHA" =~ ^[0-9a-fA-F]{40}$ ]]', sha_validation)
        self.assertLess(
            sha_validation.index("git fetch origin main"),
            sha_validation.index('git cat-file -e "$DEPLOY_SHA^{commit}"'),
        )
        self.assertIn('git merge-base --is-ancestor "$DEPLOY_SHA" origin/main', sha_validation)

    def test_state_capture_precedes_safe_exact_deployment(self) -> None:
        state_capture = self.job_body("capture-production-state")
        deploy = self.job_body("deploy")

        self.assertEqual(set(self.job_needs("capture-production-state")), set(VALIDATION_GATES))
        self.assertIn("previous_production_sha:", state_capture)
        self.assertIn("${{ steps.normalize.outputs.previous_production_sha }}", state_capture)
        self.assertIn("git status --porcelain --untracked-files=all", state_capture)
        self.assertIn("PREVIOUS_PRODUCTION_SHA=$(git rev-parse --verify HEAD^{commit})", state_capture)
        self.assertIn("capture_stdout: true", state_capture)

        self.assertIn("capture-production-state", self.job_needs("deploy"))
        self.assertIn('git cat-file -e "$DEPLOY_SHA^{commit}"', deploy)
        self.assertIn('git merge-base --is-ancestor "$DEPLOY_SHA" origin/main', deploy)
        self.assertGreaterEqual(
            deploy.count("git status --porcelain --untracked-files=all"),
            2,
            "deployment must reject a dirty tree before and after checkout",
        )
        checkout = 'git checkout --detach "$DEPLOY_SHA"'
        exact_head = '[ "$(git rev-parse HEAD)" != "$EXPECTED_DEPLOY_SHA" ]'
        self.assertIn(checkout, deploy)
        self.assertIn('EXPECTED_DEPLOY_SHA=$(git rev-parse "$DEPLOY_SHA^{commit}")', deploy)
        self.assertIn(exact_head, deploy)
        self.assertLess(deploy.index(checkout), deploy.index(exact_head))
        self.assertLess(deploy.index(exact_head), deploy.index("docker compose"))

    def test_protected_production_sequence_is_preserved(self) -> None:
        deploy = self.job_body("deploy")
        for required in (
            "environment: production",
            "DO_API_TOKEN: ${{ secrets.DO_API_TOKEN }}",
            "DB_CLUSTER_ID: ${{ secrets.DO_DB_CLUSTER_ID }}",
            "appleboy/ssh-action@v1",
            "docker compose --env-file .env.prod -f docker-compose.prod.yml build --pull",
            "=== Waiting for API health ===",
            "=== Waiting for database connectivity ===",
            "=== Stopping collector before migrations ===",
            "=== Running migrations ===",
            "=== Restarting collector ===",
            "=== Waiting for Explorer health ===",
        ):
            self.assertIn(required, deploy)

        sequence = (
            "build --pull",
            "=== Waiting for API health ===",
            "=== Waiting for database connectivity ===",
            "=== Stopping collector before migrations ===",
            "=== Running migrations ===",
            "=== Restarting collector ===",
        )
        positions = [deploy.index(item) for item in sequence]
        self.assertEqual(positions, sorted(positions))

    def test_summary_always_reports_captured_state_without_failed_step_stdout(self) -> None:
        summary = self.job_body("summary")
        expected_needs = {"validate-deploy-sha", *VALIDATION_GATES, "capture-production-state", "deploy"}

        self.assertIn("if: always()", summary)
        self.assertEqual(set(self.job_needs("summary")), expected_needs)
        self.assertIn(
            "${{ needs.capture-production-state.outputs.previous_production_sha }}",
            summary,
        )
        self.assertIn("production was never contacted", summary)
        self.assertNotIn("steps.deploy.outputs.stdout", summary)
        for field in (
            "Requested SHA:",
            "Previous production SHA:",
            "Environment: production",
            "Terminal health result:",
            "Rollback posture:",
        ):
            self.assertIn(field, summary)

    def test_runbook_identifies_and_monitors_the_exact_sha_named_run(self) -> None:
        self.assertIn(
            "Deploy $DEPLOY_SHA to production",
            self.runbook,
            "operators must correlate the run title with the requested SHA",
        )
        self.assertIn("displayTitle", self.runbook)
        self.assertIn('gh run watch "$RUN_ID" --exit-status', self.runbook)
        self.assertIn('gh run view "$RUN_ID"', self.runbook)
        self.assertNotIn("gh run list --workflow deploy.yml --limit 1", self.runbook)

    def test_provisioning_handoff_does_not_claim_merges_auto_deploy(self) -> None:
        self.assertNotIn("automatic via GitHub Actions on push to main", self.provision)
        self.assertIn("separately authorized manual GitHub Actions workflow", self.provision)


if __name__ == "__main__":
    unittest.main()
