import unittest
from datetime import date, datetime, timedelta

from research_agent.core import BacktestConfig, Candle
from research_agent.validation import (
    _binomial_upper_tail,
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

    def test_exact_sign_test_tail(self):
        self.assertAlmostEqual(_binomial_upper_tail(2, 2), 0.25)
        self.assertAlmostEqual(_binomial_upper_tail(2, 1), 0.75)
        self.assertAlmostEqual(_binomial_upper_tail(4, 4), 0.0625)

    def test_holm_correction_includes_full_family_size(self):
        results = {
            "AAA": {
                "prospective_holdout": {
                    "strategies": {
                        "Donchian20": {
                            "raw_sign_test_pvalue": 0.001,
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
        self.assertAlmostEqual(detail["holm_adjusted_pvalue"], 0.22)
        self.assertEqual(detail["status"], "NOT_CONFIRMED_BY_CORRECTED_TEST")


if __name__ == "__main__":
    unittest.main()
