import unittest
from pathlib import Path


class SignalLedgerWorkflowSafetyTests(unittest.TestCase):
    def test_persistence_workflow_is_workflow_run_only(self):
        path = Path(__file__).parents[1] / ".github" / "workflows" / "research-agent-signal-ledger.yml"
        content = path.read_text(encoding="utf-8")
        self.assertIn("workflow_run:", content)
        self.assertIn('"MOEX EDGE MTF Signals (Read Only)"', content)
        self.assertNotIn("workflow_dispatch:", content)
        self.assertNotIn("pull_request:", content)

    def test_persistence_is_serialized_and_uses_dedicated_branch(self):
        path = Path(__file__).parents[1] / ".github" / "workflows" / "research-agent-signal-ledger.yml"
        content = path.read_text(encoding="utf-8")
        self.assertIn("cancel-in-progress: false", content)
        self.assertIn("moex-edge-signal-ledger", content)
        self.assertIn("contents: write", content)
        self.assertIn("github.event.workflow_run.head_branch == 'main'", content)
        self.assertIn("github.event.workflow_run.event == 'workflow_run'", content)


if __name__ == "__main__":
    unittest.main()
