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


    def test_manual_finam_market_data_workflow_is_read_only_and_dispatch_only(self):
        workflow = (ROOT / ".github" / "workflows" / "research-agent-finam-crosscheck.yml").read_text()
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("schedule:", workflow)
        self.assertIn("permissions:" + chr(10) + "  contents: read", workflow)
        self.assertIn("FINAM_API_TOKEN: ${{ secrets.FINAM_API_TOKEN }}", workflow)
        self.assertIn("python -m research_agent.finam_crosscheck", workflow)
        self.assertNotIn("finam_executor.py", workflow)
        self.assertNotIn("/orders", workflow)
        self.assertNotIn('echo "$FINAM_API_TOKEN"', workflow)
        self.assertIn("ZoneInfo('Europe/Moscow')", workflow)
        self.assertIn("moscow_today - timedelta(days=1)", workflow)


    def test_manual_d1_h1_reconciliation_workflow_is_read_only(self):
        workflow = (ROOT / ".github" / "workflows" / "research-agent-timeframe-reconciliation.yml").read_text()
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("schedule:", workflow)
        self.assertIn("permissions:" + chr(10) + "  contents: read", workflow)
        self.assertIn("FINAM_API_TOKEN: ${{ secrets.FINAM_API_TOKEN }}", workflow)
        self.assertIn("python -m research_agent.finam_timeframe_crosscheck", workflow)
        self.assertNotIn("finam_executor.py", workflow)
        self.assertNotIn("/orders", workflow)
        self.assertNotIn('echo "$FINAM_API_TOKEN"', workflow)

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
