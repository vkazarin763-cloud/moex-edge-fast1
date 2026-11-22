import unittest
from research_agent.v2.bootstrap import BootstrapInputError, moving_block_bootstrap_mean_test


class MovingBlockBootstrapTests(unittest.TestCase):
    def test_deterministic_and_reports_dependence_assumptions(self):
        values = [0.002 + ((i % 7) - 3) * 0.0001 for i in range(80)]
        a = moving_block_bootstrap_mean_test(values, block_length=5, resamples=999, seed=42)
        b = moving_block_bootstrap_mean_test(values, block_length=5, resamples=999, seed=42)
        self.assertEqual(a["two_sided_p_value"], b["two_sided_p_value"])
        self.assertEqual(a["observed_mean"], b["observed_mean"])
        self.assertTrue(a["safety"]["serial_dependence_preserved_within_blocks"])
        self.assertFalse(a["safety"]["overlapping_trade_dependence_fully_resolved"])
        self.assertEqual(a["safety"]["strategy_approval"], "NOT_APPROVED")

    def test_null_like_series_not_claimed_significant(self):
        values = [((i * 37) % 101 - 50) / 10000 for i in range(120)]
        result = moving_block_bootstrap_mean_test(values, block_length=6, resamples=1999, seed=7)
        self.assertGreaterEqual(result["two_sided_p_value"], 0.01)

    def test_positive_shift_is_detected_in_stable_series(self):
        values = [0.01 + ((i % 5) - 2) * 0.0001 for i in range(100)]
        result = moving_block_bootstrap_mean_test(values, block_length=4, resamples=999, seed=9)
        self.assertTrue(result["reject_null"])
        self.assertGreater(result["confidence_interval"]["lower"], 0)

    def test_rejects_bad_inputs(self):
        invalid = [
            ([], 2), ([0.1] * 19, 2), ([0.1] * 20, 11),
            ([0.1] * 20, 0), ([float("nan")] + [0.1] * 19, 2),
            ([float("inf")] + [0.1] * 19, 2), ([True] + [0.1] * 19, 2),
        ]
        for values, block in invalid:
            with self.subTest(values=values[:1], block=block):
                with self.assertRaises(BootstrapInputError):
                    moving_block_bootstrap_mean_test(values, block_length=block)
        with self.assertRaises(BootstrapInputError):
            moving_block_bootstrap_mean_test([0.1] * 20, block_length=2, resamples=100)

if __name__ == "__main__":
    unittest.main()
