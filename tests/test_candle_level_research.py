"""Offline tests for the three-year candlestick and support/resistance research."""
import unittest
from datetime import datetime, timedelta, timezone

from research_agent.candle_level_research import detect_signals, _h1_daily_trend
from research_agent.core import Candle
from research_agent.finam_market_data import FinamBar


class CandleLevelResearchTests(unittest.TestCase):
    def _flat_rows(self, count):
        start = datetime(2024, 1, 1)
        return [
            Candle(start + timedelta(days=i), 100.0, 101.0, 99.0, 100.0, 1000.0)
            for i in range(count)
        ]

    def test_bullish_engulfing_is_detected_after_close(self):
        rows = self._flat_rows(10)
        rows[4] = Candle(rows[4].timestamp, 101.0, 102.0, 97.0, 98.0, 1000.0)
        rows[5] = Candle(rows[5].timestamp, 97.0, 103.0, 96.0, 102.0, 1500.0)
        signals, _ = detect_signals(rows)
        self.assertIn((5, 1), [(s.index, s.direction) for s in signals["Engulfing"]])
        self.assertTrue(all(s.index < len(rows) - 1 for group in signals.values() for s in group))

    def test_level_breakout_uses_only_confirmed_pivots(self):
        rows = self._flat_rows(12)
        rows[1] = Candle(rows[1].timestamp, 103, 105, 102, 104, 1000)
        rows[2] = Candle(rows[2].timestamp, 104, 105, 103, 104, 1000)
        rows[3] = Candle(rows[3].timestamp, 104, 106, 103, 105, 1000)
        rows[4] = Candle(rows[4].timestamp, 107, 110, 106, 108, 1000)
        rows[5] = Candle(rows[5].timestamp, 106, 107, 104, 105, 1000)
        rows[6] = Candle(rows[6].timestamp, 105, 108, 104, 106, 1000)
        rows[7] = Candle(rows[7].timestamp, 106, 109, 105, 108, 1000)
        rows[8] = Candle(rows[8].timestamp, 109, 113, 108, 112, 2000)
        signals, audit = detect_signals(rows)
        breakout_indices = [s.index for s in signals["LevelBreakout"] if s.direction == 1]
        self.assertIn(8, breakout_indices)
        self.assertGreaterEqual(audit["confirmed_resistance_pivots"], 1)

    def test_h1_trend_excludes_frozen_holdout(self):
        start = datetime(2026, 10, 22, 6, tzinfo=timezone.utc)
        bars = []
        for i in range(60):
            price = 100.0 + i
            bars.append(FinamBar(
                timestamp=start + timedelta(hours=i),
                open=price, high=price + 1, low=price - 1,
                close=price, volume=1000.0, is_data_snapshot=False,
            ))
        bars.append(FinamBar(
            timestamp=datetime(2026, 11, 20, 10, tzinfo=timezone.utc),
            open=1000, high=1001, low=999, close=1000,
            volume=1000, is_data_snapshot=False,
        ))
        trend = _h1_daily_trend(bars)
        self.assertTrue(trend)
        self.assertTrue(all(day.isoformat() < "2026-11-20" for day in trend))
        self.assertEqual(trend[max(trend)], 1)


if __name__ == "__main__":
    unittest.main()
