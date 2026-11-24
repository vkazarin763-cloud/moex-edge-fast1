import os
import unittest
from unittest.mock import patch
from research_agent.equities_strategy_research_agent import (
    _extract, _llm_analyze, _read_github_source, inspect_candidate
)

class EquitiesResearchAgentTests(unittest.TestCase):
    def test_extracts_rule_evidence_without_claiming_validation(self):
        text = """Daily strategy.
Entry: buy when close crosses above the 20-day Donchian high.
Exit: sell when close falls below the 10-day low.
Use RSI and ATR indicators.
Execute at next open with commission and slippage."""
        result = _extract(text)
        for field in ("entry", "exit", "timeframe", "indicators", "execution"):
            self.assertTrue(result[field], field)

    def test_candidate_remains_not_eligible_when_source_unreadable(self):
        result = inspect_candidate({"url":"https://example.com/source","source_type":"unknown","title":"test"})
        self.assertEqual(result["promotion_status"], "NOT_ELIGIBLE")
        self.assertEqual(result["profitability_claim"], "NOT_ASSESSED")
        self.assertEqual(result["llm_analysis"]["status"], "SKIPPED_NO_SOURCE_TEXT")

    def test_llm_is_optional_and_does_not_call_provider_without_secret(self):
        with patch.dict(os.environ, {}, clear=True):
            result = _llm_analyze({"title":"demo"}, "Daily equity strategy")
        self.assertEqual(result["status"], "NOT_CONFIGURED")
        self.assertIsNone(result["analysis"])

    def test_github_source_is_pinned_to_commit_and_records_license(self):
        responses = [
            {"default_branch":"main", "license":{"spdx_id":"MIT","name":"MIT License"}},
            {"sha":"abc123"},
            {"tree":[{"type":"blob","path":"README.md"},{"type":"blob","path":"strategy.py"}]},
        ]
        with patch("research_agent.equities_strategy_research_agent.fetch_json", side_effect=responses), \\
             patch("research_agent.equities_strategy_research_agent._request_text", side_effect=["README text", "strategy code"]):
            text, paths, provenance = _read_github_source("https://github.com/demo/strategy")
        self.assertIn("strategy code", text)
        self.assertEqual(provenance["source_version"], "abc123")
        self.assertEqual(provenance["source_version_status"], "PINNED_COMMIT")
        self.assertEqual(provenance["source_license_spdx"], "MIT")
        self.assertEqual(len(provenance["source_file_sha256"]), 2)

if __name__ == "__main__":
    unittest.main()
