import unittest

from research_agent.v2.features import FeatureInputError, extract_ohlcv_features
from research_agent.v2.discovery import generate_hypotheses


def make_bars(count=45):
    bars = []
    for i in range(count):
        close = 100.0 + i * 0.7 + (i % 4) * 0.15
        bars.append({
            "timestamp": f"2025-01-{(i // 24) + 1:02d}T{i % 24:02d}:00:00",
            "open": close - 0.2,
            "high": close + 0.6,
            "low": close - 0.7,
            "close": close,
            "volume": 1000.0 + i * 10.0,
        })
    return bars


class OHLCVFeatureTests(unittest.TestCase):
    def test_outputs_are_aligned_and_warmups_are_missing(self):
        bars = make_bars()
        features = extract_ohlcv_features(bars)
        self.assertTrue(all(len(values) == len(bars) for values in features.values()))
        self.assertIsNone(features["return_1"][0])
        self.assertIsNone(features["relative_volume"][19])
        self.assertIsNotNone(features["relative_volume"][20])
        self.assertIsNone(features["realized_volatility"][9])
        self.assertIsNotNone(features["realized_volatility"][10])

    def test_future_bars_cannot_change_past_features(self):
        bars = make_bars()
        baseline = extract_ohlcv_features(bars)
        changed = [dict(row) for row in bars]
        for row in changed[30:]:
            row["open"] *= 1.8
            row["high"] *= 1.8
            row["low"] *= 1.8
            row["close"] *= 1.8
            row["volume"] *= 5
        altered = extract_ohlcv_features(changed)
        for name in baseline:
            self.assertEqual(baseline[name][:30], altered[name][:30], name)

    def test_rejects_invalid_ohlc_and_negative_volume(self):
        bars = make_bars()
        bars[5]["high"] = bars[5]["low"] - 1
        with self.assertRaises(FeatureInputError):
            extract_ohlcv_features(bars)
        bars = make_bars()
        bars[5]["volume"] = -1
        with self.assertRaises(FeatureInputError):
            extract_ohlcv_features(bars)

    def test_rejects_duplicate_or_non_monotonic_timestamps(self):
        bars = make_bars()
        bars[5]["timestamp"] = bars[4]["timestamp"]
        with self.assertRaises(FeatureInputError):
            extract_ohlcv_features(bars)
        bars = make_bars()
        bars[5]["timestamp"], bars[6]["timestamp"] = bars[6]["timestamp"], bars[5]["timestamp"]
        with self.assertRaises(FeatureInputError):
            extract_ohlcv_features(bars)

    def test_rejects_non_finite_values(self):
        bars = make_bars()
        bars[4]["close"] = float("inf")
        with self.assertRaises(FeatureInputError):
            extract_ohlcv_features(bars)

    def test_feature_panel_feeds_the_hypothesis_generator(self):
        panel = extract_ohlcv_features(make_bars(80))
        result = generate_hypotheses(
            panel, formation_indices=list(range(40, 70)),
            min_observations=20, max_features=8, max_hypotheses=100,
        )
        self.assertEqual(result["status"], "GENERATED")
        self.assertTrue(result["eligible_features"])
        self.assertFalse(result["safety"]["forward_returns_used"])

    def test_custom_horizons_and_window_validation(self):
        features = extract_ohlcv_features(make_bars(), return_horizons=(2, 7), volume_window=5)
        self.assertIn("return_2", features)
        self.assertIn("return_7", features)
        self.assertIsNotNone(features["relative_volume"][5])
        with self.assertRaises(FeatureInputError):
            extract_ohlcv_features(make_bars(), volatility_window=1)


if __name__ == "__main__":
    unittest.main()
