"""Dependency-free checks for the repository's vendor-neutral agent contract."""

import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.validate_agent_contract import (
    EXPECTED_SKILLS,
    REQUIRED_FILES,
    WINDOWS_REPARSE_POINT,
    _is_reparse_point,
    validate_contract,
    validate_skill_layout,
)

ROOT = Path(__file__).resolve().parents[2]


class AgentContractTests(unittest.TestCase):
    """Keep canonical procedures discoverable and adapters exact."""

    def read(self, relative_path: str) -> str:
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def assert_terms(self, text: str, terms: tuple[str, ...], context: str) -> None:
        lowered = text.lower()
        missing = [term for term in terms if term.lower() not in lowered]
        self.assertFalse(missing, f"{context} is missing contract terms: {missing}")

    def fixture(self, destination: Path) -> None:
        shutil.copytree(ROOT / ".agents" / "skills", destination / ".agents" / "skills")
        shutil.copytree(ROOT / ".claude" / "skills", destination / ".claude" / "skills")

    def contract_fixture(self, destination: Path) -> None:
        self.fixture(destination)
        for relative_path in REQUIRED_FILES:
            source = ROOT / relative_path
            target = destination / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    def add_frontmatter_line(self, root: Path, skill: str, line: str) -> None:
        for skill_root in (root / ".agents" / "skills", root / ".claude" / "skills"):
            path = skill_root / skill / "SKILL.md"
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace("\n---\n", f"\n{line}\n---\n", 1), encoding="utf-8")

    def assert_reason(self, issues: list[str], reason: str) -> None:
        self.assertTrue(
            any(issue.startswith(f"{reason}:") for issue in issues),
            f"expected {reason}, got: {issues}",
        )

    def test_live_contract_passes_validator(self) -> None:
        self.assertEqual([], validate_contract(ROOT))

    def test_expected_skill_inventory_is_exact(self) -> None:
        self.assertEqual({"adr-new", "end-session", "pr-lifecycle", "session-start"}, EXPECTED_SKILLS)

    def test_missing_adapter_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            shutil.rmtree(root / ".claude" / "skills" / "adr-new")
            self.assert_reason(validate_skill_layout(root), "SKILL_ADAPTER_MISSING")

    def test_extra_adapter_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            shutil.copytree(
                root / ".claude" / "skills" / "adr-new",
                root / ".claude" / "skills" / "undeclared",
            )
            self.assert_reason(validate_skill_layout(root), "SKILL_ADAPTER_UNDECLARED")

    def test_drifted_adapter_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            path = root / ".claude" / "skills" / "adr-new" / "SKILL.md"
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace("completely", "partially"), encoding="utf-8")
            self.assert_reason(validate_skill_layout(root), "SKILL_ADAPTER_BODY_NOT_THIN")

    def test_non_thin_adapter_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            path = root / ".claude" / "skills" / "adr-new" / "notes.md"
            path.write_text("duplicated policy\n", encoding="utf-8")
            self.assert_reason(validate_skill_layout(root), "SKILL_ADAPTER_BODY_NOT_THIN")

    def test_missing_canonical_skill_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            shutil.rmtree(root / ".agents" / "skills" / "end-session")
            self.assert_reason(validate_skill_layout(root), "SKILL_CANONICAL_MISSING")

    def test_extra_canonical_skill_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            shutil.copytree(
                root / ".agents" / "skills" / "adr-new",
                root / ".agents" / "skills" / "undeclared",
            )
            self.assert_reason(validate_skill_layout(root), "SKILL_CANONICAL_UNDECLARED")

    def test_unknown_or_duplicate_frontmatter_fails_closed(self) -> None:
        for line in ("allowed-tools: Bash", "name: adr-new"):
            with self.subTest(line=line), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.fixture(root)
                self.add_frontmatter_line(root, "adr-new", line)
                self.assert_reason(validate_skill_layout(root), "SKILL_FRONTMATTER_SCHEMA")

    def test_windows_reparse_attribute_is_rejected(self) -> None:
        metadata = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=WINDOWS_REPARSE_POINT)
        with patch.object(Path, "lstat", return_value=metadata):
            self.assertTrue(_is_reparse_point(Path("junction")))

    def test_reparse_point_in_skill_ancestor_fails_closed(self) -> None:
        with patch(
            "scripts.validate_agent_contract._is_reparse_point",
            side_effect=lambda path: path.name == ".agents",
        ):
            self.assert_reason(validate_skill_layout(ROOT), "SKILL_REPARSE_POINT")

    def test_non_thin_claude_adapter_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.contract_fixture(root)
            path = root / "CLAUDE.md"
            path.write_text(
                path.read_text(encoding="utf-8") + "\n## Commands\nRun a workflow.\n",
                encoding="utf-8",
            )
            self.assert_reason(validate_contract(root), "CLAUDE_ADAPTER_DRIFT")

    def test_canonical_files_exist_and_agents_has_precedence(self) -> None:
        required = (
            "AGENTS.md",
            "docs/agent/orchestration.md",
            ".claude/agents/orchestrator.md",
            "CLAUDE.md",
        )
        for relative_path in required:
            with self.subTest(path=relative_path):
                self.assertTrue((ROOT / relative_path).is_file(), relative_path)

        agents = self.read("AGENTS.md")
        self.assert_terms(
            agents,
            (
                "canonical",
                "vendor-neutral",
                "AGENTS.md",
                "conflicts",
                "higher-priority harness",
            ),
            "AGENTS.md precedence",
        )

    def test_adapters_link_to_canonical_contract(self) -> None:
        claude = self.read("CLAUDE.md")
        self.assertLessEqual(len(claude.splitlines()), 24)
        self.assert_terms(
            claude,
            ("AGENTS.md", "docs/agent/orchestration.md", ".agents/skills", ".claude/skills"),
            "CLAUDE.md adapter",
        )
        self.assertNotIn("Project Overview", claude)

        adapter = self.read(".claude/agents/orchestrator.md")
        self.assert_terms(
            adapter,
            ("../../AGENTS.md", "../../docs/agent/orchestration.md", "canonical", "startup adapter"),
            "Claude orchestrator adapter",
        )
        self.assertLessEqual(
            len(adapter.splitlines()),
            32,
            "Claude orchestrator adapter must remain thin; put policy in the portable contract",
        )
        self.assertNotIn("Project Overview", adapter)

    def test_branch_and_pr_linkage_is_explicit(self) -> None:
        agents = self.read("AGENTS.md")
        self.assert_terms(
            agents,
            (
                ".agents/skills",
                ".claude/skills",
                "codex/spm-3-orchestration-contract",
                "Fixes SPM-<number>",
                "Part of SPM-<number>",
            ),
            "AGENTS.md source and linkage contract",
        )

    def test_roles_authority_and_evidence_are_explicit(self) -> None:
        protocol = self.read("docs/agent/orchestration.md")
        self.assert_terms(
            protocol,
            (
                "root orchestrator",
                "orientation",
                "linear cycle",
                "authority",
                "external mutations",
                "shared-machine resources",
                "watchers",
                "integration",
                "heavy",
                "independent verification",
                "exactly one bounded",
                "delegation never widens",
                "reports are claims",
                "primary evidence",
            ),
            "role, authority, and evidence protocol",
        )

    def test_briefing_contract_is_complete(self) -> None:
        protocol = self.read("docs/agent/orchestration.md")
        self.assert_terms(
            protocol,
            (
                "goal and unit of work",
                "scope and permitted writes",
                "explicit prohibitions and reasons",
                "required reading",
                "validation",
                "plan-first and decision stops",
                "reporting and evidence",
                "not-yours list",
                "harness and isolation context",
                "delegation and filesystem-isolation",
                "required fallback",
                "measured",
                "inferred",
                "conjectural",
            ),
            "delegate briefing contract",
        )

    def test_isolation_stops_and_plan_first_boundaries_are_explicit(self) -> None:
        protocol = self.read("docs/agent/orchestration.md")
        self.assert_terms(
            protocol,
            (
                "read-only delegates may share",
                "only one writer",
                "isolated Git worktree",
                "one-writer fallback",
                "filesystem-sharing and isolation model",
                "STOP 1",
                "implementation-ready",
                "local-ready",
                "pull-request-ready",
                "STOP 2",
                "merged",
                "blocked",
                "Azure",
                "secrets",
                "authentication",
                "database schema",
                "data migration",
                "public MCP/API",
                "privacy",
                "PII",
                "destructive",
                "frontend framework",
            ),
            "isolation, stop, and plan-first protocol",
        )

    def test_linear_is_authoritative_and_cycles_require_approval(self) -> None:
        agents = self.read("AGENTS.md")
        self.assert_terms(
            agents,
            (
                "Linear, team SPM",
                "sole planning system",
                "do not create a second issue queue",
                "owner-approved replanning",
            ),
            "Linear planning contract",
        )

    def test_multi_ticket_sessions_are_capacity_based_and_issue_isolated(self) -> None:
        agents = self.read("AGENTS.md")
        protocol = self.read("docs/agent/orchestration.md")
        session_start = self.read(".agents/skills/session-start/SKILL.md")
        end_session = self.read(".agents/skills/end-session/SKILL.md")
        pr_lifecycle = self.read(".agents/skills/pr-lifecycle/SKILL.md")
        normalized_session_start = " ".join(session_start.split())

        self.assert_terms(
            agents,
            (
                "multi-ticket session",
                "two or more eligible",
                "no fixed maximum",
                "ticket-local blocker",
                "does not end the session",
            ),
            "multi-ticket standing directive",
        )
        self.assertIn(
            "Never switch a dirty checkout to another ticket.",
            agents,
            "the standing directive must fail closed when a writer lane is dirty",
        )
        self.assertIn(
            "batch-wide only when it prevents every safe eligible action",
            " ".join(agents.split()),
            "checkout isolation must not end safe independent read-only work",
        )
        self.assert_terms(
            protocol,
            (
                "transient batch",
                "current approved cycle",
                "dependency order",
                "sequential execution is the default",
                "isolated worktrees",
                "batch-wide stop",
            ),
            "multi-ticket orchestration protocol",
        )
        self.assertIn(
            "After each verified STOP 1 or ticket-local blocker",
            " ".join(protocol.split()),
            "eligibility must be refreshed after both completion and a blocker",
        )
        self.assert_terms(
            session_start,
            ("two or more", "eligible", "dependency", "batch"),
            "session-start batch selection",
        )
        self.assertIn(
            "Never create a second branch or PR for the same delivery slice implicitly.",
            normalized_session_start,
            "session-start must resume or explicitly reconcile an existing delivery lane",
        )
        self.assert_terms(
            session_start,
            ("exact branch/PR head", "primary issue linkage", "owner", "absence of another writer"),
            "existing delivery lane evidence",
        )
        self.assert_terms(
            end_session,
            ("each selected ticket", "STOP 2/merged", "blocked", "next eligible"),
            "end-session batch reconciliation",
        )
        self.assert_terms(
            pr_lifecycle,
            ("session batch", "separate branch", "one primary issue"),
            "per-ticket branch and PR isolation",
        )

    def test_standing_repository_delivery_authority_is_explicit_and_bounded(self) -> None:
        agents = self.read("AGENTS.md")
        normalized_agents = " ".join(agents.split())
        tool_policy = self.read("docs/agent/tool-policy.md")
        end_session = self.read(".agents/skills/end-session/SKILL.md")
        pr_lifecycle = self.read(".agents/skills/pr-lifecycle/SKILL.md")
        review_checklist = self.read("docs/agent/review-checklist.md")
        normalized_tool_policy = " ".join(tool_policy.split())
        normalized_end_session = " ".join(end_session.split())
        normalized_pr_lifecycle = " ".join(pr_lifecycle.split())
        normalized_review_checklist = " ".join(review_checklist.split())

        self.assert_terms(
            normalized_agents,
            (
                "standing authority",
                "local commits",
                "non-force-push",
                "create or update its pull request",
                "merge a qualifying pull request",
                "without asking for permission at each operation",
                "never passes to a delegate",
                "unauthorized production effect",
                "cycle replanning remain separately authorized",
                "Repository delivery and production delivery are distinct operations",
                "accepted documented deployment procedure",
                "monitor it to a terminal result",
                "deployed revision",
                "target environment",
                "health evidence",
                "rollback posture",
            ),
            "standing repository-delivery directive",
        )
        self.assert_terms(
            normalized_tool_policy,
            (
                "standing repository-delivery authority",
                "does not pass to delegates",
                "unauthorized deployment or production effect",
                "accepted documented deployment procedure",
                "revision, environment, health, and rollback evidence",
                "dispatch alone is not success",
                "Never force-push",
            ),
            "tool authority boundary",
        )
        self.assert_terms(
            normalized_pr_lifecycle,
            (
                "standing repository-delivery authority",
                "qualifying pull request",
                "manual-only",
                "does not dispatch production",
                "merge never authorizes a later workflow dispatch",
                "exact Linear mutations",
                "active harness authorized",
                "accepted documented deployment procedure",
                "deployed revision",
                "target environment",
                "health or smoke evidence",
                "rollback posture",
                "successful dispatch or an older healthy run is not a successful deployment",
            ),
            "pull-request lifecycle authority",
        )
        self.assert_terms(
            normalized_end_session,
            (
                "standing authority",
                "concrete publication gate",
                "This authority never passes to delegates",
                "Do not merge when it would trigger",
                "accepted documented deployment procedure",
                "monitor the exact run to a terminal result",
                "revision, environment, health, and rollback evidence",
            ),
            "end-session authority",
        )
        self.assert_terms(
            normalized_review_checklist,
            (
                "Standing repository-delivery authority",
                "accepted documented deployment procedure",
                "exact revision",
                "environment",
                "health evidence",
                "rollback posture",
                "separately authorized",
                "no gate was bypassed",
            ),
            "review authority evidence",
        )

    def test_make_and_ci_run_the_cross_platform_contract(self) -> None:
        command = 'python -m unittest discover -s tests/contracts -p "test_*.py"'
        makefile = self.read("Makefile")
        workflow = self.read(".github/workflows/ci.yml")
        self.assertIn("agent-contract:", makefile)
        self.assertIn(command, makefile)
        self.assertIn("uv-contract:", makefile)
        self.assertIn("uv-contract:", workflow)
        self.assertIn("name: UV Workflow and Lock Drift", workflow)
        self.assertIn("uv run --locked", makefile)
        self.assertIn("uv run --locked", workflow)
        self.assertIn(command, workflow)

    def test_pr_lifecycle_merge_default_is_validated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.contract_fixture(root)
            lifecycle = root / ".agents" / "skills" / "pr-lifecycle" / "SKILL.md"
            text = lifecycle.read_text(encoding="utf-8")
            lifecycle.write_text(
                text.replace(
                    "Invoke the GitHub merge operation with the `merge` method explicitly; "
                    "`merge` is this repository's\n"
                    "default pull-request strategy.",
                    "Invoke a permitted GitHub merge operation.",
                ),
                encoding="utf-8",
            )

            self.assert_reason(validate_contract(root), "PR_LIFECYCLE_MERGE_POLICY")


if __name__ == "__main__":
    unittest.main()
