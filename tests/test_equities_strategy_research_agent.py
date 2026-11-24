import json
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

    def test_llm_is_optional_without_secret(self):
        with patch.dict(os.environ, {}, clear=True):
            result = _llm_analyze({"title":"demo"}, "Daily equity strategy")
        self.assertEqual(result["status"], "NOT_CONFIGURED")
        self.assertIsNone(result["analysis"])

    def test_llm_response_is_parsed(self):
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                inner = json.dumps({"entry_rules":["close above 20-day high"],"exit_rules":[],"missing_information":["stop rule"]})
                outer = {"model":"provider/test-model","choices":[{"message":{"content":inner}}],"usage":{"total_tokens":123}}
                return json.dumps(outer).encode("utf-8")
        with patch.dict(os.environ, {"OPENROUTER_API_KEY":"test-key"}):
            with patch("research_agent.equities_strategy_research_agent.urllib.request.urlopen", return_value=Response()):
                result = _llm_analyze({"title":"demo"}, "source text")
        self.assertEqual(result["status"], "LLM_ANALYSIS_COMPLETED")
        self.assertEqual(result["model"], "provider/test-model")
        self.assertEqual(result["analysis"]["entry_rules"], ["close above 20-day high"])
        self.assertEqual(result["usage"]["total_tokens"], 123)

    def test_github_source_is_pinned_and_license_is_recorded(self):
        responses = [
            {"default_branch":"main", "license":{"spdx_id":"MIT","name":"MIT License"}},
            {"sha":"abc123"},
            {"tree":[{"type":"blob","path":"README.md"},{"type":"blob","path":"strategy.py"}]},
        ]
        with patch("research_agent.equities_strategy_research_agent.fetch_json", side_effect=responses):
            with patch("research_agent.equities_strategy_research_agent._request_text", side_effect=["README text", "strategy code"]):
                text, paths, provenance = _read_github_source("https://github.com/demo/strategy")
        self.assertIn("strategy code", text)
        self.assertEqual(provenance["source_version"], "abc123")
        self.assertEqual(provenance["source_version_status"], "PINNED_COMMIT")
        self.assertEqual(provenance["source_license_spdx"], "MIT")
        self.assertEqual(len(provenance["source_file_sha256"]), 2)

if __name__ == "__main__":
    unittest.main()
