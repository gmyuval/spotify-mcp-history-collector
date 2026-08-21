"""Dependency-free checks for the repository's vendor-neutral agent contract."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class AgentContractTests(unittest.TestCase):
    """Keep adapters thin and the portable operating contract discoverable."""

    def read(self, relative_path: str) -> str:
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def assert_terms(self, text: str, terms: tuple[str, ...], context: str) -> None:
        lowered = text.lower()
        missing = [term for term in terms if term.lower() not in lowered]
        self.assertFalse(missing, f"{context} is missing contract terms: {missing}")

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
            ("canonical", "vendor-neutral", "AGENTS.md", "conflicts", "higher-priority harness"),
            "AGENTS.md precedence",
        )

    def test_adapters_link_to_canonical_contract(self) -> None:
        claude = self.read("CLAUDE.md")
        claude_header = "\n".join(claude.splitlines()[:24])
        self.assert_terms(
            claude_header,
            ("AGENTS.md", "docs/agent/orchestration.md", "canonical", "non-authoritative", "stale"),
            "CLAUDE.md transitional header",
        )

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

    def test_make_and_ci_run_the_contract(self) -> None:
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
