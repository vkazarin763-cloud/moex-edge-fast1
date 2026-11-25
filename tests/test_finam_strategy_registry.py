"""Tests for the fail-closed Finam strategy registry adapter."""
import unittest

from research_agent.finam_strategy_registry import build_finam_strategy_registry


class FinamStrategyRegistryTests(unittest.TestCase):
    def _report(self, missing=None):
        universe = ["SBER", "GAZP", "LKOH"]
        audit = {
            ticker: {"status": "OK", "retained_completed_bars": 250}
            for ticker in universe
        }
        if missing:
            audit[missing] = {"status": "FETCH_OR_VALIDATION_ERROR"}
        return {
            "source": "Finam Trade API TIME_FRAME_D, native D1 bars",
            "holdout_start": "2026-11-20",
            "holdout_used_for_selection": False,
            "date_till": "2026-11-19",
            "generated_at_utc": "2026-11-25T00:00:00+00:00",
            "universe": universe,
            "data_audit": audit,
        }

    def test_full_finam_coverage_never_approves_unvalidated_strategies(self):
        registry = build_finam_strategy_registry(self._report())
        self.assertEqual(registry["source_provider"], "Finam Trade API")
        self.assertEqual(registry["source_timeframe"], "D1")
        self.assertEqual(registry["coverage"]["expected_symbols"], 3)
        self.assertEqual(registry["coverage"]["analyzed_symbols"], 3)
        self.assertTrue(registry["coverage"]["coverage_complete"])
        self.assertEqual(registry["scanner_contract"]["consume_only_status"], "PASS")
        self.assertEqual(registry["summary"]["PASS"], 0)
        self.assertEqual(registry["summary"]["INSUFFICIENT_DATA"], 30)
        self.assertTrue(all(
            item["status"] == "INSUFFICIENT_DATA"
            and item["eligible_for_shadow_scanner"] is False
            for item in registry["strategies"]
        ))

    def test_incomplete_finam_coverage_blocks_scanner_contract(self):
        registry = build_finam_strategy_registry(self._report(missing="GAZP"))
        self.assertFalse(registry["coverage"]["coverage_complete"])
        self.assertEqual(
            registry["scanner_contract"]["consume_only_status"],
            "BLOCKED_INCOMPLETE_COVERAGE",
        )
        self.assertEqual(registry["coverage"]["unavailable_tickers"], ["GAZP"])

    def test_rejects_non_finam_or_changed_holdout_report(self):
        report = self._report()
        report["source"] = "MOEX ISS"
        with self.assertRaisesRegex(ValueError, "only native Finam"):
            build_finam_strategy_registry(report)
        report = self._report()
        report["holdout_start"] = "2026-11-19"
        with self.assertRaisesRegex(ValueError, "holdout boundary"):
            build_finam_strategy_registry(report)


if __name__ == "__main__":
    unittest.main()
