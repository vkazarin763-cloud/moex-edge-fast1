"""Offline tests for the three-year candlestick and support/resistance research."""
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from research_agent.candle_level_research import (
    detect_signals, _h1_daily_trend, _fetch_d1_model_rows,
)
from research_agent.core import Candle
from research_agent.finam_market_data import FinamBar
from research_agent.moex_iss import HistoryRecord


class CandleLevelResearchTests(unittest.TestCase):
    def _flat_rows(self, count):
        start = datetime(2024, 1, 1)
        return [
            Candle(start + timedelta(days=i), 100.0, 101.0, 99.0, 100.0, 1000.0)
            for i in range(count)
        ]

    def test_d1_loader_uses_history_trade_dates_not_raw_calendar_candles(self):
        records = [
            HistoryRecord(
                trade_date=date(2025, 3, 3), num_trades=100,
                open=100.0, high=105.0, low=99.0, close=104.0, volume=5000.0,
            ),
            HistoryRecord(
                trade_date=date(2025, 3, 4), num_trades=0,
                open=None, high=None, low=None, close=None, volume=None,
            ),
            HistoryRecord(
                trade_date=date(2025, 3, 5), num_trades=120,
                open=104.0, high=108.0, low=103.0, close=107.0, volume=6000.0,
            ),
        ]
        with patch(
            "research_agent.candle_level_research.fetch_history_records",
            return_value=records,
        ) as fetch:
            rows, audit = _fetch_d1_model_rows("SBER", "2023-11-20", "2026-11-19")
        fetch.assert_called_once_with(
            "SBER", "2023-11-20", "2026-11-19", board="TQBR"
        )
        self.assertEqual([row.timestamp.date() for row in rows], [
            date(2025, 3, 3), date(2025, 3, 5),
        ])
        self.assertEqual(audit["session_mapping"]["zero_trade_history_rows_excluded"], 1)
        self.assertEqual(audit["status"], "OK")

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
