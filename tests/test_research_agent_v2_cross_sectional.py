import unittest

from research_agent.v2.cross_sectional import (
    CrossSectionalFeatureError,
    extract_cross_sectional_features,
)


def make_bars(symbol_index, *, count=22, future_multiplier=1.0):
    rows = []
    for index in range(count):
        close = 100.0 * (1.01 ** index) if symbol_index == 0 else 100.0
        if index >= 21:
            close *= future_multiplier
        rows.append({
            "timestamp": f"2025-01-{index + 1:02d}T00:00:00",
            "close": close,
        })
    return rows


class CrossSectionalFeatureTests(unittest.TestCase):
    def test_relative_strength_and_market_regime_features(self):
        symbols = {
            f"S{index:02d}": make_bars(index)
            for index in range(24)
        }
        result = extract_cross_sectional_features(symbols)
        target = result["S00"]
        self.assertGreater(target["xs_relative_return_20"][20], 0.0)
        self.assertAlmostEqual(target["market_median_return_20"][20], 0.0)
        self.assertAlmostEqual(target["market_breadth_positive_20"][20], 1 / 24)
        self.assertGreater(target["market_dispersion_20"][20], 0.0)
        self.assertEqual(len(target["xs_relative_return_5"]), 22)

    def test_future_rows_cannot_change_earlier_features(self):
        original = {
            f"S{index:02d}": make_bars(index, count=24)
            for index in range(24)
        }
        changed = {
            f"S{index:02d}": make_bars(
                index, count=24, future_multiplier=5.0 if index == 0 else 0.2
            )
            for index in range(24)
        }
        first = extract_cross_sectional_features(original)
        second = extract_cross_sectional_features(changed)
        for symbol in original:
            for feature in first[symbol]:
                self.assertEqual(
                    first[symbol][feature][:21],
                    second[symbol][feature][:21],
                )

    def test_insufficient_same_date_coverage_fails_closed(self):
        symbols = {
            f"S{index:02d}": make_bars(index) if index < 10 else make_bars(index, count=10)
            for index in range(24)
        }
        result = extract_cross_sectional_features(symbols)
        # Only ten symbols have a valid 20-bar return on the 22nd date;
        # the 50% universe coverage requirement is not met.
        self.assertIsNone(result["S00"]["market_median_return_20"][21])
        self.assertIsNone(result["S00"]["xs_relative_return_20"][21])

    def test_rejects_non_monotonic_timestamps(self):
        symbols = {"AAA": make_bars(0), "BBB": make_bars(1)}
        symbols["AAA"][1]["timestamp"] = symbols["AAA"][0]["timestamp"]
        with self.assertRaises(CrossSectionalFeatureError):
            extract_cross_sectional_features(symbols)


if __name__ == "__main__":
    unittest.main()
