import unittest
import math
import random
from statistics import mean
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


    def test_precomputed_block_sums_match_reference_resampling(self):
        values = [((i * 17) % 29 - 14) / 10000 for i in range(23)]
        block_length, resamples, seed, alpha = 4, 999, 123, 0.05
        actual = moving_block_bootstrap_mean_test(
            values, block_length=block_length, resamples=resamples,
            seed=seed, alpha=alpha,
        )
        observed = mean(values)
        centered = [value - observed for value in values]
        rng = random.Random(seed)
        null_means, alt_means = [], []
        blocks_needed = (len(values) + block_length - 1) // block_length
        for _ in range(resamples):
            null_sample, alt_sample = [], []
            for _block in range(blocks_needed):
                start = rng.randrange(len(values))
                take = min(block_length, len(values) - len(null_sample))
                for offset in range(take):
                    index = (start + offset) % len(values)
                    null_sample.append(centered[index])
                    alt_sample.append(values[index])
            null_means.append(mean(null_sample))
            alt_means.append(mean(alt_sample))
        expected_p = (sum(abs(value) >= abs(observed) for value in null_means) + 1) / (resamples + 1)
        alt_means.sort()

        def quantile(probability):
            position = (len(alt_means) - 1) * probability
            lower, upper = math.floor(position), math.ceil(position)
            if lower == upper:
                return alt_means[lower]
            weight = position - lower
            return alt_means[lower] * (1 - weight) + alt_means[upper] * weight

        self.assertEqual(actual["two_sided_p_value"], expected_p)
        self.assertAlmostEqual(actual["confidence_interval"]["lower"], quantile(alpha / 2))
        self.assertAlmostEqual(actual["confidence_interval"]["upper"], quantile(1 - alpha / 2))

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
