import unittest
from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

import pandas as pd

import signal_bot


class SignalBotTests(unittest.TestCase):
    def test_clean_candles_removes_invalid_and_duplicate_rows(self):
        frame = pd.DataFrame([
            {"begin": "2026-11-16 10:00", "open": 10, "high": 12, "low": 9, "close": 11, "volume": 100},
            {"begin": "2026-11-16 10:00", "open": 10, "high": 12, "low": 9, "close": 11, "volume": 100},
            {"begin": "2026-11-16 11:00", "open": 10, "high": 8, "low": 9, "close": 11, "volume": 100},
        ])
        result = signal_bot.clean_candles(frame)
        self.assertEqual(len(result), 1)

    def test_empty_daily_response_is_returned_as_empty(self):
        now = datetime(2026, 11, 17, 15, 0, tzinfo=ZoneInfo("Europe/Moscow"))
        with mock.patch.object(signal_bot.edge, "fetch_candles", return_value=pd.DataFrame()):
            result = signal_bot.get_closed_d1("SBER", now)
        self.assertTrue(result.empty)

    def test_current_day_daily_candle_is_excluded(self):
        now = datetime(2026, 11, 17, 15, 0, tzinfo=ZoneInfo("Europe/Moscow"))
        frame = pd.DataFrame([
            {"begin": "2026-11-16", "open": 10, "high": 12, "low": 9, "close": 11, "volume": 100},
            {"begin": "2026-11-17", "open": 11, "high": 13, "low": 10, "close": 12, "volume": 100},
        ])
        with mock.patch.object(signal_bot.edge, "fetch_candles", return_value=frame):
            result = signal_bot.get_closed_d1("SBER", now)
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["begin"].date().isoformat(), "2026-11-16")

    def test_unfinished_h1_candle_is_excluded(self):
        now = datetime(2026, 11, 17, 15, 30, tzinfo=ZoneInfo("Europe/Moscow"))
        frame = pd.DataFrame([
            {"begin": "2026-11-17 14:00", "open": 10, "high": 12, "low": 9, "close": 11, "volume": 100},
            {"begin": "2026-11-17 15:00", "open": 11, "high": 13, "low": 10, "close": 12, "volume": 100},
        ])
        with mock.patch.object(signal_bot.edge, "fetch_candles", return_value=frame):
            result = signal_bot.get_closed_h1("SBER", now)
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["begin"].hour, 14)

    def test_ai_weight_breaks_equal_priority_tie(self):
        candidates = [
            (pd.Timestamp("2026-11-16"), 1, "Donchian55"),
            (pd.Timestamp("2026-11-16"), 1, "ATR"),
        ]
        with mock.patch.object(signal_bot.edge, "calc_indicators", return_value=pd.DataFrame()), \
             mock.patch.object(signal_bot.edge, "get_signals", return_value=candidates), \
             mock.patch.dict(signal_bot.edge.STRATEGY_PRIORITY, {"Donchian55": 7, "ATR": 7}):
            selected = signal_bot.select_signal(pd.DataFrame(), {"Donchian55": 2, "ATR": 9})
        self.assertEqual(selected[2], "ATR")


if __name__ == "__main__":
    unittest.main()
