"""Dependency-free contract checks for the production deployment workflow."""

import os
import re
import subprocess
import unittest
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

from scripts import validate_compose

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy.yml"
RUNBOOK = Path(__file__).resolve().parents[2] / "docs" / "digitalocean-deployment.md"
OAUTH_RUNBOOK = Path(__file__).resolve().parents[2] / "docs" / "google-oauth-setup.md"
PROVISION = Path(__file__).resolve().parents[2] / "deploy" / "provision.sh"
COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.prod.yml"
ENV_PROD_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.prod.example"
TRACKED_ALLOWLIST = Path(__file__).resolve().parents[2] / "deploy" / "authenticated-emails.txt"
ALLOWLIST_TEMPLATE = Path(__file__).resolve().parents[2] / "deploy" / "authenticated-emails.txt.example"
VALIDATION_GATES = (
    "lint",
    "typecheck",
    "test-api",
    "test-collector",
    "test-frontend",
    "test-explorer",
)
REVIEWED_ACTIONS = {
    "actions/checkout": "d23441a48e516b6c34aea4fa41551a30e30af803",
    "actions/setup-python": "ece7cb06caefa5fff74198d8649806c4678c61a1",
    "appleboy/ssh-action": "0ff4204d59e8e51228ff73bce53f80d53301dee2",
}
UUID_V4_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"


def mapping_body(document: str, key: str, indent: int = 0) -> str:
    """Return an indentation-delimited YAML mapping body without parsing YAML."""
    lines = document.splitlines(keepends=True)
    markers = {
        f"{' ' * indent}{key}:",
        f'{" " * indent}"{key}":',
        f"{' ' * indent}'{key}':",
    }

    for start, line in enumerate(lines):
        if line.rstrip("\r\n") not in markers:
            continue

        body = []
        for line in lines[start + 1 :]:
            stripped = line.strip()
            leading_spaces = len(line) - len(line.lstrip(" "))
            comment_only = line.lstrip(" ").startswith("#")
            if stripped and not comment_only and leading_spaces <= indent:
                break
            body.append(line)
        return "".join(body)

    raise AssertionError(f"Missing mapping key {key!r} at indentation {indent}")


def direct_mapping_keys(body: str, indent: int) -> tuple[str, ...]:
    """Return only mapping keys at one exact indentation level."""
    pattern = re.compile(
        rf"^{' ' * indent}(?P<key>[A-Za-z0-9_-]+|\"[A-Za-z0-9_-]+\"|'[A-Za-z0-9_-]+'):(?:\s|$)",
        re.MULTILINE,
    )
    return tuple(match.group("key").strip("\"'") for match in pattern.finditer(body))


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


def deployment_run_title(workflow: str, commit_sha: str, deployment_id: str) -> str:
    """Render the title from the workflow's actual run-name mapping."""
    template = mapping_value(workflow, "run-name", indent=0)
    if len(template) >= 2 and template[0] == template[-1] and template[0] in "\"'":
        template = template[1:-1]
    rendered = template.replace("${{ inputs.commit_sha }}", commit_sha).replace(
        "${{ inputs.deployment_id }}", deployment_id
    )
    if "${{" in rendered:
        raise AssertionError("run-name contains an unsupported expression")
    return rendered


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


def workflow_steps(job: str) -> tuple[str, ...]:
    """Return top-level GitHub Actions step bodies from one job."""
    lines = job.splitlines(keepends=True)
    starts = [index for index, line in enumerate(lines) if line.startswith("      - ")]
    return tuple(
        "".join(lines[start : starts[offset + 1] if offset + 1 < len(starts) else len(lines)])
        for offset, start in enumerate(starts)
    )


class DeploymentWorkflowContractTests(unittest.TestCase):
    workflow: ClassVar[str]
    runbook: ClassVar[str]
    oauth_runbook: ClassVar[str]
    provision: ClassVar[str]
    compose: ClassVar[str]
    env_prod_example: ClassVar[str]
    trigger_body: ClassVar[str]
    jobs_body: ClassVar[str]

    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.runbook = RUNBOOK.read_text(encoding="utf-8")
        cls.oauth_runbook = OAUTH_RUNBOOK.read_text(encoding="utf-8")
        cls.provision = PROVISION.read_text(encoding="utf-8")
        cls.compose = COMPOSE.read_text(encoding="utf-8")
        cls.env_prod_example = ENV_PROD_EXAMPLE.read_text(encoding="utf-8")
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
        deployment_id_body = mapping_body(inputs_body, "deployment_id", indent=6)
        self.assertIn("required: true", deployment_id_body)
        self.assertNotIn("default:", deployment_id_body)
        self.assertIn("Canonical lowercase UUID v4", deployment_id_body)
        self.assertNotIn("fresh", deployment_id_body.lower())
        self.assertIn(
            'run-name: "Deploy ${{ inputs.commit_sha }} to production [${{ inputs.deployment_id }}]"',
            self.workflow,
            "the run title must identify both the immutable SHA and authorized dispatch",
        )
        concurrency = mapping_body(self.workflow, "concurrency")
        self.assertIn("group: production-deployment", concurrency)
        self.assertIn("cancel-in-progress: false", concurrency)

    def test_trigger_parser_detects_comment_separated_and_quoted_push_keys(self) -> None:
        adversarial_documents = {
            "comment separated": "on:\n  workflow_dispatch:\n# deceptive separator\n  push:\n",
            "double quoted": 'on:\n  workflow_dispatch:\n  "push":\n',
            "single quoted": "on:\n  workflow_dispatch:\n  'push':\n",
        }
        for case, document in adversarial_documents.items():
            with self.subTest(case=case):
                trigger_body = mapping_body(document, "on")
                self.assertIn("push", direct_mapping_keys(trigger_body, 2))

    def test_external_actions_are_immutable_and_permissions_are_read_only(self) -> None:
        uses = re.findall(r"(?m)^\s*-?\s*uses:\s*([^\s#]+)", self.workflow)
        self.assertGreater(len(uses), 0)
        for reference in uses:
            with self.subTest(reference=reference):
                self.assertRegex(reference, r"^[^@]+@[0-9a-f]{40}$")
                action, revision = reference.rsplit("@", 1)
                self.assertEqual(revision, REVIEWED_ACTIONS[action])

        permissions = mapping_body(self.workflow, "permissions")
        self.assertEqual(direct_mapping_keys(permissions, 2), ("contents",))
        self.assertEqual(mapping_value(permissions, "contents", indent=2), "read")

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
            self.assertIn(
                "persist-credentials: false",
                gate_body,
                f"{gate} must not retain Git credentials",
            )

        sha_validation = self.job_body("validate-deploy-sha")
        self.assertNotIn("persist-credentials: false", sha_validation)
        self.assertIn('[[ "$DEPLOY_SHA" =~ ^[0-9a-fA-F]{40}$ ]]', sha_validation)
        self.assertIn("DEPLOYMENT_ID: ${{ inputs.deployment_id }}", sha_validation)
        self.assertIn(f'[[ "$DEPLOYMENT_ID" =~ {UUID_V4_PATTERN} ]]', sha_validation)
        self.assertNotIn("fresh canonical", sha_validation.lower())
        self.assertLess(
            sha_validation.index("git fetch origin main"),
            sha_validation.index('git cat-file -e "$DEPLOY_SHA^{commit}"'),
        )
        self.assertIn('git merge-base --is-ancestor "$DEPLOY_SHA" origin/main', sha_validation)

    def test_deployment_id_pattern_rejects_canonical_non_v4_uuid(self) -> None:
        canonical_v4 = "11111111-1111-4111-8111-111111111111"
        canonical_non_v4 = "11111111-1111-1111-8111-111111111111"
        self.assertIsNotNone(re.fullmatch(UUID_V4_PATTERN, canonical_v4))
        self.assertIsNone(re.fullmatch(UUID_V4_PATTERN, canonical_non_v4))

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
            f"appleboy/ssh-action@{REVIEWED_ACTIONS['appleboy/ssh-action']}",
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

    def test_oauth_allowlist_is_external_and_preflight_fails_closed(self) -> None:
        """Regression: a checkout-tracked allowlist makes exact-SHA deployment dirty."""
        external_allowlist = "/opt/spotify-mcp-config/authenticated-emails.txt"
        mount = f"{external_allowlist}:/etc/oauth2-proxy/authenticated-emails.txt:ro"
        state_capture = self.job_body("capture-production-state")
        deploy = self.job_body("deploy")

        self.assertFalse(TRACKED_ALLOWLIST.exists())
        self.assertTrue(ALLOWLIST_TEMPLATE.is_file())
        self.assertIn(mount, self.compose)
        self.assertNotIn("./deploy/authenticated-emails.txt:", self.compose)
        self.assertIn(f'AUTHENTICATED_EMAILS_FILE="{external_allowlist}"', state_capture)
        self.assertIn(f'AUTHENTICATED_EMAILS_FILE="{external_allowlist}"', deploy)
        self.assertIn('! -r "$AUTHENTICATED_EMAILS_FILE"', state_capture)
        self.assertIn('[[ ! -s "$AUTHENTICATED_EMAILS_FILE" ]]', state_capture)
        self.assertIn('! -r "$AUTHENTICATED_EMAILS_FILE"', deploy)
        self.assertIn('[[ ! -s "$AUTHENTICATED_EMAILS_FILE" ]]', deploy)
        self.assertIn(
            "install -d -o deploy -g deploy -m 0750 /opt/spotify-mcp-config",
            self.provision,
        )
        self.assertIn(
            'install -o deploy -g deploy -m 0644 /dev/null "$AUTHENTICATED_EMAILS_FILE"',
            self.provision,
        )
        self.assertIn(external_allowlist, self.runbook)
        self.assertIn(external_allowlist, self.oauth_runbook)
        self.assertIn('git restore --source=HEAD -- "$LEGACY_ALLOWLIST"', self.runbook)
        self.assertIn('cmp -s "$LEGACY_ALLOWLIST" "$EXTERNAL_ALLOWLIST"', self.runbook)
        self.assertLess(
            deploy.index("- name: Verify external OAuth allowlist"),
            deploy.index("- name: Ensure DB firewall allows spotify-mcp droplets"),
            "the external allowlist must be checked before any production mutation",
        )
        self.assertLess(
            state_capture.index('! -r "$AUTHENTICATED_EMAILS_FILE"'),
            state_capture.index("sudo -n chown"),
            "the external allowlist must be checked before state capture mutates production",
        )
        self.assertLess(
            deploy.index('! -r "$AUTHENTICATED_EMAILS_FILE"'),
            deploy.index("docker compose"),
            "the external allowlist must be checked before service mutation",
        )

    def test_required_compose_environment_is_supplied_by_production_contract(self) -> None:
        required_names = set(re.findall(r"\$\{([A-Z][A-Z0-9_]*):\?", self.compose))
        template_names = set(re.findall(r"(?m)^([A-Z][A-Z0-9_]*)=", self.env_prod_example))
        generated_environment = re.search(
            r'ENV_PROD_CONTENT="(?P<body>.*?)"\n\necho "\$ENV_PROD_CONTENT"',
            self.provision,
            re.DOTALL,
        )

        self.assertIn(
            "INTERNAL_API_KEY",
            required_names,
            "the production Compose contract must continue requiring the internal key",
        )
        self.assertIsNotNone(generated_environment)
        provisioned_names = set(
            re.findall(
                r"(?m)^([A-Z][A-Z0-9_]*)=",
                generated_environment.group("body") if generated_environment else "",
            )
        )
        self.assertEqual(
            required_names - template_names,
            set(),
            "every required Compose name must be present in .env.prod.example",
        )
        self.assertEqual(
            required_names - provisioned_names,
            set(),
            "every required Compose name must be generated by deploy/provision.sh",
        )

    def test_compose_validation_uses_the_production_template_without_placeholders(self) -> None:
        completed = subprocess.CompletedProcess[str]([], 0, "", "")
        with (
            patch("scripts.validate_compose.shutil.which", return_value="docker"),
            patch(
                "scripts.validate_compose.subprocess.run",
                return_value=completed,
            ) as run,
            patch.dict(os.environ, {}, clear=True),
        ):
            result = validate_compose.main()

        self.assertEqual(result, 0)
        production_call = run.call_args_list[1]
        self.assertEqual(
            production_call.args[0],
            [
                "docker",
                "compose",
                "--env-file",
                ".env.prod.example",
                "-f",
                "docker-compose.prod.yml",
                "config",
                "--quiet",
            ],
        )
        required_names = set(re.findall(r"\$\{([A-Z][A-Z0-9_]*):\?", self.compose))
        validator_environment = production_call.kwargs["env"]
        self.assertTrue(
            required_names.isdisjoint(validator_environment),
            "Compose validation must not inject placeholders for required production names",
        )

    def test_legacy_allowlist_revision_is_rejected_before_production_contact(self) -> None:
        """Regression: generic rollback must not start legacy tracked authorization."""
        validate = self.job_body("validate-deploy-sha")

        self.assertIn('git show "${DEPLOY_SHA}:docker-compose.prod.yml"', validate)
        self.assertIn(
            "/opt/spotify-mcp-config/authenticated-emails.txt:/etc/oauth2-proxy/authenticated-emails.txt:ro",
            validate,
        )
        self.assertIn("selected revision predates the external OAuth allowlist contract", validate)
        self.assertIn("separately authorized legacy rollback procedure", validate)
        self.assertIn("Generic workflow redispatch is limited to revisions", self.runbook)
        self.assertIn("Do not dispatch the workflow for a legacy revision", self.runbook)

    def test_fresh_provision_has_interactive_checkpoint_and_narrow_resume(self) -> None:
        """Regression: a fresh empty allowlist must have a safe completion path."""
        checkpoint = 'log "Pre-Step-10: Verifying external OAuth allowlist"'

        self.assertIn("--resume-after-allowlist <full-commit-sha>", self.provision)
        self.assertIn("RESUME_AFTER_ALLOWLIST=true", self.provision)
        self.assertIn('RESUME_DEPLOY_SHA="$2"', self.provision)
        self.assertIn(checkpoint, self.provision)
        self.assertIn("if [[ -t 0 ]]", self.provision)
        self.assertIn('read -r -p "Press Enter after the allowlist is populated: "', self.provision)
        self.assertGreaterEqual(self.provision.count("allowlist_ready"), 3)
        self.assertLess(self.provision.index(checkpoint), self.provision.index('log "Step 10:'))
        self.assertIn("--resume-after-allowlist", self.runbook)
        self.assertRegex(self.runbook, r"skips Steps\s+1-9")

    def test_resume_requires_clean_exact_eligible_revision_before_mutation(self) -> None:
        """Regression: resume must not deploy an arbitrary existing checkout."""
        heredoc = self.provision.index("<<'REMOTE_RESUME'")
        resume_start = self.provision.index("set -euo pipefail", heredoc)
        resume_end = self.provision.index("\nREMOTE_RESUME", resume_start)
        resume = self.provision[resume_start:resume_end]
        for required in (
            "git fetch origin main:refs/remotes/origin/main",
            'git cat-file -e "$RESUME_DEPLOY_SHA^{commit}"',
            'git merge-base --is-ancestor "$RESUME_DEPLOY_SHA" origin/main',
            'git checkout --detach "$EXPECTED_RESUME_SHA"',
            '[[ "$(git rev-parse HEAD)" == "$EXPECTED_RESUME_SHA" ]]',
            '[[ -z "$(git status --porcelain --untracked-files=all)" ]]',
        ):
            self.assertIn(required, resume)
        self.assertIn('[[ "$RESUME_DEPLOY_SHA" =~ ^[0-9a-fA-F]{40}$ ]]', self.provision[:heredoc])
        self.assertIn("INITIAL_DEPLOY_REVISION=", self.provision)
        self.assertIn("INITIAL_DEPLOY_API_HEALTH_RESULT=healthy", self.provision)
        self.assertIn('bash deploy/provision.sh --resume-after-allowlist "$DEPLOY_SHA"', self.runbook)

    def test_initial_deploy_rechecks_api_health_after_migrations(self) -> None:
        """Regression: pre-migration health cannot support terminal health evidence."""
        migration = self.provision.index(
            "docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T api alembic upgrade head"
        )
        post_migration = self.provision.index('echo "--- Verifying post-migration API health ---"')
        health = self.provision.index(
            "docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T api curl -sf",
            post_migration,
        )
        evidence = self.provision.index('echo "INITIAL_DEPLOY_API_HEALTH_RESULT=healthy"')

        self.assertLess(migration, post_migration)
        self.assertLess(post_migration, health)
        self.assertLess(health, evidence)

    def test_production_ssh_authenticates_the_trusted_host_identity(self) -> None:
        """Regression: discovered host keys must not silently become trusted keys."""
        capture = self.job_body("capture-production-state")
        deploy = self.job_body("deploy")
        action_ref = f"appleboy/ssh-action@{REVIEWED_ACTIONS['appleboy/ssh-action']}"
        ssh_steps = [step for job in (capture, deploy) for step in workflow_steps(job) if action_ref in step]

        self.assertEqual(len(ssh_steps), 3)
        for step in ssh_steps:
            self.assertIn(
                "fingerprint: ${{ secrets.DROPLET_SSH_HOST_FINGERPRINT }}",
                step,
            )
        for job in (capture, deploy):
            self.assertIn("Validate production SSH host fingerprint", job)
            self.assertIn("DROPLET_SSH_HOST_FINGERPRINT", job)
            self.assertIn(r"^SHA256:[A-Za-z0-9+/]{43}$", job)
            self.assertLess(
                job.index("Validate production SSH host fingerprint"),
                job.index(action_ref),
            )

        self.assertNotIn("StrictHostKeyChecking=no", self.provision)
        self.assertIn("ssh-keyscan -T 5 -t ed25519", self.provision)
        self.assertIn('ssh-keygen -lf "$OFFERED_HOST_KEY_FILE" -E sha256', self.provision)
        self.assertIn('[[ "$OFFERED_HOST_FINGERPRINT" == "$DROPLET_SSH_HOST_FINGERPRINT" ]]', self.provision)
        self.assertIn("StrictHostKeyChecking=yes", self.provision)
        self.assertIn("UserKnownHostsFile=$KNOWN_HOSTS_FILE", self.provision)
        self.assertIn('chmod 600 "$KNOWN_HOSTS_FILE"', self.provision)
        self.assertIn("trap cleanup_ssh_trust EXIT", self.provision)

        ssh_invocations = [
            line
            for line in self.provision.splitlines()
            if re.search(r"(?<![-\w])ssh\s", line) and not line.lstrip().startswith("#")
        ]
        self.assertGreater(len(ssh_invocations), 5)
        for invocation in ssh_invocations:
            self.assertIn('"${SSH_OPTIONS[@]}"', invocation)

        execution = self.provision[self.provision.index("# Step 1:") :]
        self.assertLess(
            execution.index('prepare_known_hosts "$DROPLET_IP"'),
            execution.index('wait_for_ssh "$DROPLET_IP"'),
        )
        resume = execution[execution.index('log "Resume:') :]
        self.assertLess(
            resume.index('prepare_known_hosts "$DROPLET_IP"'),
            resume.index('wait_for_ssh "$DROPLET_IP"'),
        )
        self.assertIn("authenticated DigitalOcean console", self.runbook)
        self.assertIn("DROPLET_SSH_HOST_FINGERPRINT", self.runbook)
        self.assertIn("ssh-keyscan is discovery, not authentication", self.runbook)

    def test_legacy_rollback_is_exact_revision_bound_and_monitored(self) -> None:
        """Regression: legacy rollback must bind state, revision, and health evidence."""
        for required in (
            'LEGACY_DEPLOY_SHA="0123456789abcdef0123456789abcdef01234567"',
            'git cat-file -e "$LEGACY_DEPLOY_SHA^{commit}"',
            'git merge-base --is-ancestor "$LEGACY_DEPLOY_SHA" origin/main',
            'git checkout --detach "$EXPECTED_LEGACY_SHA"',
            'test "$(git rev-parse HEAD)" = "$EXPECTED_LEGACY_SHA"',
            'test -z "$(git status --porcelain --untracked-files=all)"',
            "LEGACY_ROLLBACK_REVISION=",
            "LEGACY_ROLLBACK_HEALTH_RESULT=healthy",
            "database compatibility decision",
        ):
            self.assertIn(required, self.runbook)

    def test_allowlist_permissions_and_oauth_runtime_are_verified(self) -> None:
        """Regression: deploy readability does not prove UID 65532 can consume the file."""
        state_capture = self.job_body("capture-production-state")
        deploy = self.job_body("deploy")
        summary = self.job_body("summary")

        self.assertGreaterEqual(state_capture.count("750:deploy:deploy"), 1)
        self.assertGreaterEqual(state_capture.count("644:deploy:deploy"), 1)
        self.assertGreaterEqual(deploy.count("750:deploy:deploy"), 2)
        self.assertGreaterEqual(deploy.count("644:deploy:deploy"), 2)
        self.assertIn("750:deploy:deploy", self.provision)
        self.assertIn("644:deploy:deploy", self.provision)
        self.assertIn("http://oauth2-proxy:4180/ping", deploy)
        self.assertIn("OAUTH2_PROXY_HEALTH_RESULT=healthy", deploy)
        self.assertLess(
            deploy.index("http://oauth2-proxy:4180/ping"),
            deploy.index("TERMINAL_HEALTH_RESULT=healthy"),
        )
        self.assertIn("oauth2-proxy /ping", summary)

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

    def test_rollback_is_limited_to_code_and_stops_at_database_decisions(self) -> None:
        summary = self.job_body("summary").lower()
        runbook = self.runbook.lower()
        for document in (summary, runbook):
            normalized = re.sub(r"\s+", " ", document)
            self.assertIn("application-code rollback candidate", normalized)
            self.assertIn("never a complete rollback", normalized)
            self.assertIn("migrations may have started or applied", normalized)
            self.assertIn("database compatibility or recovery decision", normalized)
            self.assertNotIn("alembic downgrade", normalized)

    def test_runbook_identifies_and_monitors_the_exact_sha_named_run(self) -> None:
        normalized_runbook = re.sub(r"\s+", " ", self.runbook)
        self.assertIn("uuid.uuid4()", self.runbook)
        self.assertIn("Never reuse an earlier deployment UUID", normalized_runbook)
        self.assertIn('-f deployment_id="$DEPLOYMENT_ID"', self.runbook)
        self.assertIn("DISPATCH_OUTPUT=$(gh workflow run", normalized_runbook)
        self.assertIn(
            'EXPECTED_RUN_TITLE="Deploy $DEPLOY_SHA to production [$DEPLOYMENT_ID]"',
            self.runbook,
        )
        self.assertIn("RUN_URL", self.runbook)
        self.assertIn("RUN_ID", self.runbook)
        self.assertIn(
            "Deploy $DEPLOY_SHA to production [$DEPLOYMENT_ID]",
            self.runbook,
            "operators must correlate the run title with both authorized values",
        )
        self.assertIn("displayTitle", self.runbook)
        self.assertIn('gh run watch "$RUN_ID" --exit-status', self.runbook)
        self.assertIn('gh run view "$RUN_ID"', self.runbook)
        self.assertNotIn("gh run list --workflow deploy.yml --limit 1", self.runbook)
        self.assertNotIn("gh api", self.runbook)

    def test_run_title_renderer_is_bound_to_the_workflow_mapping(self) -> None:
        commit_sha = "a" * 40
        deployment_id = "11111111-1111-4111-8111-111111111111"
        variant_workflow = self.workflow.replace(
            'run-name: "Deploy ${{ inputs.commit_sha }} to production [${{ inputs.deployment_id }}]"',
            'run-name: "Authorized ${{ inputs.deployment_id }} for ${{ inputs.commit_sha }}"',
        )
        self.assertEqual(
            deployment_run_title(variant_workflow, commit_sha, deployment_id),
            f"Authorized {deployment_id} for {commit_sha}",
        )

    def test_same_sha_dispatches_have_distinct_matchable_run_titles(self) -> None:
        commit_sha = "1" * 40
        first_id = "11111111-1111-4111-8111-111111111111"
        second_id = "22222222-2222-4222-a222-222222222222"
        runs = (
            {
                "databaseId": 101,
                "displayTitle": deployment_run_title(self.workflow, commit_sha, first_id),
            },
            {
                "databaseId": 102,
                "displayTitle": deployment_run_title(self.workflow, commit_sha, second_id),
            },
        )

        expected_title = deployment_run_title(self.workflow, commit_sha, first_id)
        matches = [run["databaseId"] for run in runs if run["displayTitle"] == expected_title]
        self.assertEqual(matches, [101])
        self.assertNotEqual(runs[0]["displayTitle"], runs[1]["displayTitle"])

    def test_provisioning_handoff_does_not_claim_merges_auto_deploy(self) -> None:
        self.assertNotIn("automatic via GitHub Actions on push to main", self.provision)
        self.assertIn("separately authorized manual GitHub Actions workflow", self.provision)


if __name__ == "__main__":
    unittest.main()
