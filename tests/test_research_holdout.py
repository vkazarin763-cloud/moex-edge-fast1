import unittest
from datetime import date, datetime, timedelta

from research_agent.core import BacktestConfig, Candle
from research_agent.validation import (
    _newey_west_mean_test,
    apply_holm_correction,
    prospective_holdout_report,
)


def trending_daily_bars(count=320):
    start = date(2024, 1, 1)
    rows = []
    for i in range(count):
        close = 100.0 + i
        rows.append(Candle(
            datetime.combine(start + timedelta(days=i), datetime.min.time()),
            close - 0.4, close + 0.2, close - 0.5, close, 10000.0,
        ))
    return rows


class ProspectiveHoldoutTests(unittest.TestCase):
    def test_no_future_observations_are_not_misrepresented_as_holdout(self):
        rows = trending_daily_bars(100)
        report = prospective_holdout_report(rows, "2026-11-20")
        self.assertEqual(report["status"], "WAITING_FOR_PROSPECTIVE_DATA")
        self.assertEqual(report["holdout_bars"], 0)

    def test_holdout_uses_only_signals_after_frozen_cutoff(self):
        rows = trending_daily_bars()
        cutoff = (date(2024, 1, 1) + timedelta(days=220)).isoformat()
        report = prospective_holdout_report(
            rows, cutoff, min_holdout_trades=5, bootstrap_samples=100,
            config=BacktestConfig(0, 0, None, None, 1),
        )
        self.assertEqual(report["status"], "PROSPECTIVE_DATA_AVAILABLE")
        donchian = report["strategies"]["Donchian20"]
        self.assertGreaterEqual(donchian["closed_trades"], 5)
        self.assertIsNotNone(donchian["block_bootstrap_mean_ci_95"])
        self.assertGreater(donchian["block_bootstrap_mean_ci_95"]["lower"], 0)
        self.assertEqual(donchian["status"], "AWAITING_MULTIPLE_TEST_CORRECTION")

    def test_default_holm_family_is_ticker_times_frozen_strategies_not_directions(self):
        results = {
            "AAA": {"prospective_holdout": {"strategies": {}}},
            "BBB": {"prospective_holdout": {"strategies": {}}},
        }
        summary = apply_holm_correction(results)
        self.assertEqual(summary["family_size"], 2 * 5)
        self.assertEqual(summary["minimum_family_size_for_holdout_design"], 2 * 5)
        self.assertEqual(summary["ticker_count"], 2)
        self.assertEqual(summary["frozen_strategy_count_per_ticker"], 5)
        self.assertFalse(summary["directions_separately_tested"])
        self.assertEqual(summary["family_scope"], "prospective_holdout_only")

    def test_hac_mean_test_returns_one_sided_probability(self):
        result = _newey_west_mean_test([0.01 + i * 0.0001 for i in range(40)])
        self.assertIsNotNone(result["pvalue"])
        self.assertGreater(result["z_statistic"], 0)
        self.assertGreaterEqual(result["lags"], 1)

    def test_holm_correction_includes_full_family_size(self):
        results = {
            "AAA": {
                "prospective_holdout": {
                    "strategies": {
                        "Donchian20": {
                            "raw_hac_pvalue": 0.001,
                            "closed_trades": 40,
                            "minimum_trades_required": 30,
                            "block_bootstrap_mean_ci_95": {"lower": 0.01, "upper": 0.03},
                            "status": "AWAITING_MULTIPLE_TEST_CORRECTION",
                        }
                    }
                }
            }
        }
        summary = apply_holm_correction(results, family_size=220)
        detail = results["AAA"]["prospective_holdout"]["strategies"]["Donchian20"]
        self.assertEqual(summary["family_size"], 220)
        self.assertEqual(summary["family_scope"], "prospective_holdout_only")
        self.assertEqual(summary["hypothesis_unit"], "ticker x frozen entry strategy")
        self.assertFalse(summary["directions_separately_tested"])
        self.assertTrue(summary["development_directional_registry_is_separate"])
        self.assertEqual(summary["minimum_family_size_for_holdout_design"], 5)
        self.assertAlmostEqual(detail["holm_adjusted_pvalue"], 0.22)
        self.assertEqual(detail["status"], "NOT_CONFIRMED_BY_CORRECTED_TEST")


if __name__ == "__main__":
    unittest.main()
