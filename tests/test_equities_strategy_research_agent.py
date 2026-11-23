import unittest
from research_agent.equities_strategy_research_agent import _extract, inspect_candidate

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

if __name__ == "__main__":
    unittest.main()
