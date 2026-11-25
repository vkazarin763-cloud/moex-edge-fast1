"""Release safety regression checks for isolated research workflows."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ResearchWorkflowSafetyTests(unittest.TestCase):
    def test_research_workflow_is_read_only_and_has_no_broker_execution(self):
        workflow = (ROOT / ".github" / "workflows" / "research-agent-run.yml").read_text()
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn("manual-finam-two-strategy-research.yml", workflow)
        self.assertNotIn("research_agent.cli", workflow)
        self.assertIn("secrets: inherit", workflow)
        self.assertIn("push:", workflow)
        self.assertIn('"research_agent/**"', workflow)
        self.assertIn("schedule:", workflow)
        self.assertNotIn("FINAM_API_SECRET", workflow)
        self.assertNotIn("FINAM_ACCOUNT_ID", workflow)
        self.assertNotIn("finam_executor.py", workflow)
        self.assertNotIn("moex_edge_fast_33.py", workflow)


    def test_legacy_cross_provider_workflows_are_retired(self):
        paths = (
            "research-agent-finam-crosscheck.yml",
            "research-agent-finam-h1-crosscheck.yml",
            "research-agent-timeframe-reconciliation.yml",
        )
        for name in paths:
            workflow = (ROOT / ".github" / "workflows" / name).read_text()
            self.assertIn("workflow_dispatch:", workflow)
            self.assertIn("legacy workflow is retired", workflow)
            self.assertNotIn("FINAM_API_TOKEN", workflow)
            self.assertNotIn("MOEX ISS", workflow)

    def test_scheduled_scanner_executor_workflow_is_explicitly_dry_run(self):
        workflow = (ROOT / ".github" / "workflows" / "moex-edge-fast.yml").read_text()
        self.assertIn("FINAM_DRY_RUN: 'true'", workflow)
        self.assertIn("FINAM_LIVE_TRADING_ENABLED: 'false'", workflow)
        self.assertIn("DRY RUN ONLY — LIVE TRADING DISABLED", workflow)

    def test_manual_finam_executor_workflow_is_explicitly_dry_run(self):
        workflow = (ROOT / ".github" / "workflows" / "finam-executor.yml").read_text()
        self.assertIn("FINAM_DRY_RUN: 'true'", workflow)
        self.assertIn("DRY_RUN forced", workflow)


if __name__ == "__main__":
    unittest.main()
