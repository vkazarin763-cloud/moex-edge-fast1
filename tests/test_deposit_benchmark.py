import unittest

from experimental_portfolio.deposit_benchmark import (
    DEPOSIT_SNAPSHOT, compare_to_deposit, get_deposit_hurdle,
)


class DepositBenchmarkTests(unittest.TestCase):
    def test_snapshot_matches_official_november_2026_rates(self):
        self.assertEqual(DEPOSIT_SNAPSHOT["as_of"], "2026-11-27")
        self.assertAlmostEqual(get_deposit_hurdle("91_to_180_days")["annual_rate"], 0.1318)
        self.assertAlmostEqual(get_deposit_hurdle("181_days_to_1_year")["annual_rate"], 0.1285)
        self.assertAlmostEqual(DEPOSIT_SNAPSHOT["headline_rate"], 0.1333)

    def test_strategy_below_deposit_is_rejected(self):
        result = compare_to_deposit({"cagr": 0.0761, "max_drawdown": -0.0524})
        self.assertEqual(result["status"], "BELOW_HURDLE")
        self.assertLess(result["excess_over_hurdle"], 0)

    def test_strategy_above_hurdle_is_not_approved(self):
        result = compare_to_deposit({"cagr": 0.18, "max_drawdown": -0.2})
        self.assertEqual(result["status"], "ABOVE_HURDLE_NOT_APPROVED")
        self.assertIn("never live approval", result["warning"])

    def test_explicit_risk_premium_is_applied(self):
        result = compare_to_deposit({"cagr": 0.15}, required_excess_rate=0.03)
        self.assertAlmostEqual(result["total_hurdle_rate"], 0.1585)
        self.assertEqual(result["status"], "BELOW_HURDLE")

    def test_missing_cagr_is_not_comparable(self):
        self.assertEqual(compare_to_deposit({})["status"], "NOT_COMPARABLE")

    def test_invalid_term_and_premium_fail_closed(self):
        with self.assertRaises(ValueError):
            get_deposit_hurdle("overnight")
        with self.assertRaises(ValueError):
            compare_to_deposit({"cagr": 0.2}, required_excess_rate=-0.01)


if __name__ == "__main__":
    unittest.main()
