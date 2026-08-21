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
                "shared-machine context",
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

    def test_make_and_ci_run_the_cross_platform_contract(self) -> None:
        command = 'python -m unittest discover -s tests/contracts -p "test_*.py"'
        makefile = self.read("Makefile")
        workflow = self.read(".github/workflows/ci.yml")
        self.assertIn("agent-contract:", makefile)
        self.assertIn(command, makefile)
        self.assertIn("agent-contract:", workflow)
        self.assertIn("name: Agent Contract", workflow)
        self.assertIn(command, workflow)


if __name__ == "__main__":
    unittest.main()
