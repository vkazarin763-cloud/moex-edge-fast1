import unittest

import pandas as pd

from research_agent.technical_analysis_ready import (
    _confirmed_pivots,
    _normalise_and_validate,
    _regression_channel,
)


def sample_candles(count=100):
    rows = []
    for i in range(count):
        base = 100.0 + i * 0.1
        rows.append({
            "timestamp": f"2025-01-{1 + i // 24:02d}T{i % 24:02d}:00:00",
            "open": base,
            "high": base + 1.0 + (i % 5) * 0.1,
            "low": base - 1.0 - (i % 3) * 0.1,
            "close": base + 0.2,
            "volume": 1000 + i,
        })
    return pd.DataFrame(rows)


class TechnicalAnalysisReadyTests(unittest.TestCase):
    def test_validates_and_normalises_ohlcv(self):
        frame = _normalise_and_validate(sample_candles())
        self.assertEqual(len(frame), 100)
        self.assertEqual(list(frame.columns), ["timestamp", "open", "high", "low", "close", "volume"])

    def test_rejects_duplicate_timestamps(self):
        frame = sample_candles()
        frame.loc[1, "timestamp"] = frame.loc[0, "timestamp"]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            _normalise_and_validate(frame)

    def test_rejects_invalid_ohlc(self):
        frame = sample_candles()
        frame.loc[0, "high"] = frame.loc[0, "low"] - 1
        with self.assertRaisesRegex(ValueError, "invalid OHLC"):
            _normalise_and_validate(frame)

    def test_pivot_is_not_available_until_right_side_confirmation(self):
        frame = pd.DataFrame([
            {"timestamp": pd.Timestamp(f"2025-01-{i+1:02d}"), "high": h, "low": l}
            for i, (h, l) in enumerate([(2, 1), (3, 0), (8, -1), (4, 0), (3, 1), (2, 2)])
        ])
        pivots = _confirmed_pivots(frame, left=2, right=2)
        high_pivot = next(item for item in pivots if item["kind"] == "resistance")
        self.assertEqual(high_pivot["pivot_index"], 2)
        self.assertEqual(high_pivot["confirmed_index"], 4)
        self.assertEqual(high_pivot["confirmed_at"], frame.iloc[4]["timestamp"].isoformat())

    def test_regression_channel_uses_trailing_window(self):
        frame = _normalise_and_validate(sample_candles())
        result = _regression_channel(frame, window=40)
        self.assertEqual(result["window_bars"], 40)
        self.assertEqual(result["window_end"], frame.iloc[-1]["timestamp"].isoformat())
        self.assertGreater(result["upper_at_last_close"], result["lower_at_last_close"])

    def test_channel_returns_none_when_history_is_short(self):
        frame = _normalise_and_validate(sample_candles(20))
        self.assertIsNone(_regression_channel(frame, window=60))


if __name__ == "__main__":
    unittest.main()
