"""Contract tests for the sanitized SPM-20 estate capture."""

import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
CAPTURE_SCRIPT = ROOT / "scripts" / "capture_estate_baseline.py"
BASELINE_JSON = ROOT / "docs" / "migration" / "spm-20-live-estate-baseline.json"
BASELINE_DOC = ROOT / "docs" / "migration" / "spm-20-live-estate-baseline.md"


class EstateCaptureContractTests(unittest.TestCase):
    """The capture must summarize provider state without retaining identities."""

    @staticmethod
    def _load_capture_module() -> object:
        spec = importlib.util.spec_from_file_location("estate_capture", CAPTURE_SCRIPT)
        if spec is None or spec.loader is None:
            raise AssertionError("capture module could not be loaded")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_committed_baseline_is_complete_sanitized_and_hash_bound(self) -> None:
        # Break caught: the human handoff and machine evidence diverge, an estate
        # resource loses its disposition, or raw provider identity leaks into Git.
        baseline = json.loads(BASELINE_JSON.read_text(encoding="utf-8"))
        document = BASELINE_DOC.read_text(encoding="utf-8")

        self.assertEqual(baseline["schema_version"], 1)
        self.assertRegex(baseline["repository_revision"], r"^[0-9a-f]{40}$")
        self.assertRegex(baseline["deployed_revision"], r"^[0-9a-f]{40}$")

        capture = dict(baseline["provider_capture"])
        evidence_hash = capture.pop("evidence_sha256")
        canonical = json.dumps(capture, sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), evidence_hash)

        resources = baseline["resource_classifications"]
        aliases = [resource["resource_alias"] for resource in resources]
        self.assertEqual(len(aliases), len(set(aliases)))
        required_aliases = {
            "do-droplet-primary",
            "do-postgresql-primary",
            "do-valkey-primary",
            "do-project-production",
            "do-firewall-primary",
            "do-vpc-default",
            "do-dns-zone-shared",
            "do-dns-record-primary",
            "do-uptime-check-primary",
            "do-droplet-backup-set",
            "droplet-upload-data",
            "do-provider-certificate-primary",
            "do-trusted-source-tags",
            "droplet-caddy-data",
            "droplet-legacy-allowlist",
            "droplet-caddy-config",
        }
        self.assertEqual(set(aliases), required_aliases)
        allowed = {
            "migrate",
            "replace",
            "retain_temporarily",
            "retire",
            "explicit_exception",
        }
        for resource in resources:
            self.assertIn(resource["classification"], allowed)
            self.assertTrue(resource["evidence"])

        unavailable = baseline["unavailable_evidence"]
        self.assertTrue(unavailable)
        for gap in unavailable:
            self.assertEqual(gap["status"], "unavailable")
            self.assertRegex(gap["follow_up_owner"], r"^SPM-[0-9]+$")

        serialized = json.dumps(baseline, sort_keys=True)
        sensitive_text = serialized + "\n" + document
        self.assertNotIn("requirements-lock-docker.txt", sensitive_text)
        self.assertIsNone(re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+", sensitive_text))
        self.assertIsNone(re.search(r"(?<![0-9])[0-9]{1,3}(?:\.[0-9]{1,3}){3}(?![0-9])", sensitive_text))
        self.assertIsNone(
            re.search(
                r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
                sensitive_text,
                re.IGNORECASE,
            )
        )
        forbidden_keys = {
            "email",
            "host",
            "ip",
            "password",
            "secret_value",
            "token",
            "user",
        }

        def assert_safe_keys(value: object) -> None:
            if isinstance(value, dict):
                self.assertFalse(forbidden_keys.intersection(value), value.keys())
                for nested in value.values():
                    assert_safe_keys(nested)
            elif isinstance(value, list):
                for nested in value:
                    assert_safe_keys(nested)

        assert_safe_keys(baseline)
        for required_text in (
            "Measured evidence",
            "Inferences and decisions",
            "Unavailable evidence",
            baseline["repository_revision"],
            baseline["deployed_revision"],
            evidence_hash,
        ):
            self.assertIn(required_text, document)

    def test_committed_baseline_preserves_reviewed_operational_contracts(self) -> None:
        # Break caught: the artifact becomes a shallow inventory and drops the
        # provenance, routing, retention, provider-linkage, or Azure target evidence.
        baseline = json.loads(BASELINE_JSON.read_text(encoding="utf-8"))
        module = self._load_capture_module()

        capture = baseline["provider_capture"]
        self.assertEqual(
            set(capture["digitalocean"]["counts"]),
            set(module.DO_COLLECTIONS),
        )
        self.assertTrue(set(capture["digitalocean"]["droplet_sizes"]).issubset(module.DO_DROPLET_SIZES))
        self.assertTrue(set(capture["azure"]["resource_types"]).issubset(module.AZURE_RESOURCE_TYPES))
        self.assertEqual(baseline["capture_scope"]["aggregate_collector_digitalocean_collections"], 19)
        self.assertFalse(baseline["capture_scope"]["raw_selectors_persisted"])

        application = baseline["production_application"]
        self.assertEqual(
            application["contract"]["packaging_source"],
            "service-scoped requirements.txt and requirements-dev.txt files",
        )
        provenance = application["dependency_and_image_provenance"]
        self.assertFalse(provenance["current_developer_environment"]["environment_yml_present"])
        self.assertTrue(provenance["current_ci"]["locked_workspace_sync"])
        self.assertFalse(provenance["docker_requirements"]["package_hashes_present"])
        self.assertEqual(provenance["docker_requirements"]["recorded_files"], 15)
        self.assertEqual(provenance["unavailable_owner"], "SPM-23")
        for revision in provenance["dockerfile_git_sha1"].values():
            self.assertRegex(revision, r"^[0-9a-f]{40}$")

        self.assertEqual(set(provenance["base_image_references"].values()), {"python:3.14-slim"})
        self.assertEqual(provenance["compose_runtime_image_references"]["caddy"], "caddy:2-alpine")

        routes = application["ingress_route_map"]
        self.assertEqual(routes["/mcp/*"], "api_without_google_forward_auth")
        self.assertEqual(routes["/admin/*"], "frontend_with_google_forward_auth")
        self.assertEqual(application["database"]["configured_backup_retention"], "unavailable")
        self.assertRegex(application["durable_state"]["upload_manifest_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(application["database"]["schema_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(application["health"]["certificate_sha256"], r"^[0-9a-f]{64}$")

        azure = baseline["azure_readiness"]
        self.assertRegex(azure["tenant_sha256_12"], r"^[0-9a-f]{12}$")
        self.assertRegex(azure["subscription_sha256_12"], r"^[0-9a-f]{12}$")
        self.assertEqual(azure["authenticated_identity_type"], "user")
        self.assertEqual(azure["subscription_scope_role_assignments"], 4)
        self.assertEqual(azure["product_resource_group_boundary"], "not_established")
        for region in ("westeurope", "northeurope"):
            candidate = azure["candidate_regions"][region]
            self.assertEqual(candidate["postgresql_versions"], 8)
            self.assertGreater(candidate["container_apps_profile_count"], 0)

        couplings = baseline["external_couplings"]
        self.assertEqual(
            set(couplings["github"]["workflow_required_secret_names"]),
            {
                "DO_API_TOKEN",
                "DO_DB_CLUSTER_ID",
                "DROPLET_IP",
                "DROPLET_SSH_HOST_FINGERPRINT",
                "SSH_PRIVATE_KEY",
            },
        )
        self.assertEqual(couplings["dns"]["public_hostname"], "music.praxiscode.dev")
        self.assertEqual(couplings["dns"]["record_ttl_seconds"], 300)
        self.assertEqual(couplings["oauth"]["google_callback"], "https path /oauth2/callback")
        integrations = couplings["integrations"]
        self.assertEqual(
            set(integrations),
            {"spotify_accounts_and_web_api", "musicbrainz", "soundcharts", "external_valkey"},
        )
        gaps = {(gap["evidence"], gap["follow_up_owner"]) for gap in baseline["unavailable_evidence"]}
        self.assertIn(("configured managed PostgreSQL backup retention policy", "SPM-26"), gaps)
        self.assertIn(
            ("base-image digests resulting application image identities and build timestamps", "SPM-23"),
            gaps,
        )

    def test_hostile_fixture_categories_cannot_escape_the_sanitizer(self) -> None:
        module = self._load_capture_module()
        raw = {
            "captured_at": "2026-08-23T22:00:00Z",
            "digitalocean": {name: [] for name in module.DO_COLLECTIONS},
            "azure": {"accounts": [], "resource_groups": [], "resources": []},
        }
        raw["digitalocean"]["droplets"] = [
            {
                "region": "private-person@example.invalid",
                "size_slug": "s-private-token-value",
                "status": "person@example.invalid",
            }
        ]
        raw["azure"]["resources"] = [
            {
                "type": "Microsoft.Secret/privateToken",
                "location": "person@example.invalid",
            }
        ]

        capture = module.sanitize_capture(raw)
        serialized = json.dumps(capture, sort_keys=True)
        self.assertNotIn("example.invalid", serialized)
        self.assertNotIn("private-token", serialized)
        self.assertNotIn("privateToken", serialized)
        self.assertEqual(capture["digitalocean"]["droplet_states"], {"other": 1})
        self.assertEqual(capture["azure"]["resource_types"], {"other": 1})

        raw["captured_at"] = "person@example.invalid"
        with self.assertRaisesRegex(ValueError, "UTC timestamp"):
            module.sanitize_capture(raw)

    def test_fixture_capture_redacts_identifiers_and_summarizes_counts(self) -> None:
        # Break caught: a new provider field or careless serializer retains raw IDs,
        # names, addresses, credentials, or account identities in the committed output.
        fixture = {
            "captured_at": "2026-08-23T22:00:00Z",
            "digitalocean": {
                "droplets": [
                    {
                        "id": 123456,
                        "name": "private-product-host",
                        "status": "active",
                        "region": {"slug": "fra1"},
                        "size_slug": "s-2vcpu-2gb",
                        "networks": {"v4": [{"ip_address": "203.0.113.4"}]},
                    }
                ],
                "databases": [
                    {
                        "id": "private-db-id",
                        "name": "private-db-name",
                        "engine": "pg",
                        "version": "18",
                        "region": "fra1",
                        "status": "online",
                        "connection": {
                            "host": "private-db.example.invalid",
                            "user": "private-user",
                            "password": "private-password",
                        },
                    },
                    {
                        "id": "private-cache-id",
                        "name": "private-cache-name",
                        "engine": "valkey",
                        "version": "8",
                        "region": "fra1",
                        "status": "online",
                    },
                ],
                "domains": [{"name": "private.example", "ttl": 1800}],
                "firewalls": [{"id": "private-firewall-id", "status": "succeeded"}],
                "vpcs": [{"id": "private-vpc-id", "region": "fra1"}],
                "volumes": [],
                "snapshots": [{"id": "private-snapshot-id"}],
                "projects": [{"id": "private-project-id", "environment": "Production"}],
                "tags": [{"name": "private-tag"}],
                "alerts": [],
                "uptime": [{"id": "private-check-id", "type": "https", "enabled": True}],
            },
            "azure": {
                "accounts": [
                    {
                        "id": "private-subscription-id",
                        "tenantId": "private-tenant-id",
                        "state": "Enabled",
                        "isDefault": True,
                        "user": {"name": "person@example.invalid", "type": "user"},
                    }
                ],
                "resource_groups": [{"id": "private-rg-id", "name": "private-rg", "location": "westeurope"}],
                "resources": [
                    {
                        "id": "private-resource-id",
                        "name": "private-resource-name",
                        "type": "Microsoft.App/containerApps",
                        "location": "westeurope",
                    }
                ],
            },
        }
        for name in (
            "apps",
            "cdns",
            "certificates",
            "custom_images",
            "kubernetes_clusters",
            "load_balancers",
            "registry_repositories",
            "reserved_ips",
        ):
            fixture["digitalocean"][name] = []

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fixture_path = temp_path / "fixture.json"
            output_path = temp_path / "capture.json"
            fixture_path.write_text(json.dumps(fixture), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(CAPTURE_SCRIPT),
                    "--fixture",
                    str(fixture_path),
                    "--output",
                    str(output_path),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            capture = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(capture["schema_version"], 1)
        self.assertEqual(capture["captured_at"], "2026-08-23T22:00:00Z")
        self.assertEqual(capture["digitalocean"]["counts"]["droplets"], 1)
        self.assertEqual(capture["digitalocean"]["counts"]["databases"], 2)
        self.assertEqual(capture["digitalocean"]["database_engines"], {"pg": 1, "valkey": 1})
        self.assertEqual(capture["azure"]["counts"]["subscriptions"], 1)
        self.assertEqual(capture["azure"]["resource_types"], {"Microsoft.App/containerApps": 1})
        self.assertRegex(capture["evidence_sha256"], r"^[0-9a-f]{64}$")

        serialized = json.dumps(capture, sort_keys=True)
        for forbidden in (
            "123456",
            "private-product-host",
            "203.0.113.4",
            "private-db-id",
            "private-db-name",
            "private-db.example.invalid",
            "private-user",
            "private-password",
            "private.example",
            "private-subscription-id",
            "private-tenant-id",
            "person@example.invalid",
            "private-rg",
            "private-resource-name",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_live_plan_requires_explicit_provider_contexts(self) -> None:
        # Break caught: live capture silently uses whichever cloud account happens
        # to be the current CLI default.
        result = subprocess.run(
            [sys.executable, str(CAPTURE_SCRIPT), "--command-plan"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--doctl-context", result.stderr)
        self.assertIn("--azure-subscription", result.stderr)

    def test_live_command_plan_contains_only_read_operations(self) -> None:
        # Break caught: adding a create, update, delete, deployment, or login
        # operation to the reusable live-capture path.
        result = subprocess.run(
            [
                sys.executable,
                str(CAPTURE_SCRIPT),
                "--command-plan",
                "--doctl-context",
                "fixture-context",
                "--azure-subscription",
                "fixture-subscription",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(set(plan), {"digitalocean", "azure"})
        self.assertTrue(
            {
                "apps",
                "cdns",
                "certificates",
                "custom_images",
                "kubernetes_clusters",
                "load_balancers",
                "registry_repositories",
                "reserved_ips",
            }.issubset(plan["digitalocean"])
        )
        self.assertIn("list-user", plan["digitalocean"]["custom_images"])
        self.assertNotIn("--type", plan["digitalocean"]["custom_images"])
        forbidden_verbs = {
            "append",
            "create",
            "delete",
            "deploy",
            "fork",
            "login",
            "migrate",
            "remove",
            "resize",
            "restart",
            "run",
            "set",
            "update",
        }
        for provider_commands in plan.values():
            self.assertGreater(len(provider_commands), 0)
            for command in provider_commands.values():
                self.assertIsInstance(command, list)
                self.assertTrue(command)
                self.assertFalse(forbidden_verbs.intersection(command), command)

    def test_live_collection_fails_closed_on_partial_reads_and_sanitizes(self) -> None:
        # Break caught: a live command is skipped, malformed output is accepted, or
        # raw provider identifiers survive the common sanitizer.
        module = self._load_capture_module()
        plan = module.build_command_plan("fixture-context", "fixture-subscription")
        responses = {
            ("digitalocean", "droplets"): [
                {
                    "id": "raw-droplet-id",
                    "name": "raw-droplet-name",
                    "status": "active",
                    "region": {"slug": "fra1"},
                    "size_slug": "s-2vcpu-2gb",
                }
            ],
            ("digitalocean", "databases"): [
                {
                    "id": "raw-database-id",
                    "name": "raw-database-name",
                    "engine": "pg",
                    "region": "fra1",
                    "status": "online",
                    "connection": {"password": "raw-password"},
                }
            ],
            ("azure", "accounts"): {
                "id": "raw-subscription-id",
                "tenantId": "raw-tenant-id",
                "state": "Enabled",
            },
            ("azure", "resource_groups"): [],
            ("azure", "resources"): [],
        }
        for name in module.DO_COLLECTIONS:
            responses.setdefault(("digitalocean", name), [])
        calls: list[tuple[str, str]] = []

        def fake_run(provider: str, name: str, command: list[str]) -> object:
            self.assertEqual(command, plan[provider][name])
            calls.append((provider, name))
            return responses[(provider, name)]

        collector = getattr(module, "collect_live", None)
        self.assertIsNotNone(collector)
        raw = collector(plan, fake_run, captured_at="2026-08-23T22:00:00Z")
        capture = module.sanitize_capture(raw)

        expected_calls = {(provider, name) for provider, commands in plan.items() for name in commands}
        self.assertEqual(set(calls), expected_calls)
        self.assertEqual(capture["digitalocean"]["counts"]["droplets"], 1)
        self.assertEqual(capture["azure"]["counts"]["subscriptions"], 1)
        serialized = json.dumps(capture, sort_keys=True)
        for forbidden in ("raw-droplet-id", "raw-database-id", "raw-password"):
            self.assertNotIn(forbidden, serialized)

    def test_provider_command_timeout_and_failures_are_bounded_and_private(self) -> None:
        # Break caught: a provider CLI can hang forever or echo a credential into
        # the capture error path.
        module = self._load_capture_module()
        runner = getattr(module, "_run_json_command", None)
        self.assertIsNotNone(runner)

        timeout = subprocess.TimeoutExpired(cmd=["provider"], timeout=120)
        with (
            mock.patch.object(module, "resolve_command", return_value=["provider"]),
            mock.patch.object(module.subprocess, "run", side_effect=timeout) as run,
        ):
            with self.assertRaisesRegex(ValueError, r"digitalocean\.droplets timed out"):
                runner("digitalocean", "droplets", ["provider"])
        self.assertEqual(run.call_args.kwargs["timeout"], module.PROVIDER_READ_TIMEOUT_SECONDS)

        failure = subprocess.CompletedProcess(
            ["provider"],
            7,
            stdout="",
            stderr="credential=private-value\nnetwork failed",
        )
        with (
            mock.patch.object(module, "resolve_command", return_value=["provider"]),
            mock.patch.object(module.subprocess, "run", return_value=failure),
        ):
            with self.assertRaisesRegex(ValueError, r"failed with exit 7") as raised:
                runner("digitalocean", "droplets", ["provider"])
        self.assertIn("stderr_bytes=", str(raised.exception))
        self.assertNotIn("private-value", str(raised.exception))
        self.assertNotIn("network failed", str(raised.exception))

    def test_windows_batch_cli_is_launched_through_comspec(self) -> None:
        # Break caught: live capture cannot start Azure CLI on Windows because
        # CreateProcess does not execute the az.cmd launcher directly.
        module = self._load_capture_module()
        resolver = getattr(module, "resolve_command", None)
        self.assertIsNotNone(resolver)
        resolved = resolver(
            ["az", "account", "show"],
            which=lambda _: r"C:\tools\az.cmd",
            windows=True,
            comspec="cmd.exe",
        )
        self.assertEqual(
            resolved,
            ["cmd.exe", "/d", "/s", "/c", r"C:\tools\az.cmd account show"],
        )
        with self.assertRaisesRegex(ValueError, "unsafe batch argument"):
            resolver(
                ["az", "account", "show", "--subscription", "value&whoami"],
                which=lambda _: r"C:\tools\az.cmd",
                windows=True,
                comspec="cmd.exe",
            )


if __name__ == "__main__":
    unittest.main()
