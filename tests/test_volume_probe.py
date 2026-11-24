import unittest
from datetime import datetime

from research_agent.core import Candle
from research_agent.volume_probe import probe_case, run_probe


CASE = {
    "ticker": "AFKS",
    "trade_date": "2025-10-27",
    "raw_volume": 1000,
    "total_session_history_volume": 1100,
    "morning_plus_main_history_volume": 900,
}


class VolumeProbeTests(unittest.TestCase):
    def test_minute_aggregate_matches_daily_ohlcv_and_raw_baseline(self):
        daily = [Candle(datetime(2025, 10, 27), 100, 105, 98, 102, 1000)]
        minute = [
            Candle(datetime(2025, 10, 27, 10, 0), 100, 103, 99, 102, 400),
            Candle(datetime(2025, 10, 27, 10, 1), 102, 105, 98, 102, 600),
        ]

        def fetcher(ticker, start, end, interval, board):
            return daily if interval == 24 else minute

        result = probe_case(CASE, fetcher=fetcher)
        self.assertEqual(result["status"], "CROSS_TIMEFRAME_MATCH")
        self.assertTrue(result["ohlc_matches_daily"])
        self.assertTrue(result["volume_matches_daily"])
        self.assertTrue(result["volume_matches_frozen_raw_baseline"])
        self.assertFalse(result["volume_matches_total_session_history"])
        self.assertEqual(result["minute_candle_count"], 2)

    def test_minute_aggregate_mismatch_is_reported_not_suppressed(self):
        daily = [Candle(datetime(2025, 10, 27), 100, 105, 98, 102, 1000)]
        minute = [
            Candle(datetime(2025, 10, 27, 10, 0), 100, 103, 99, 102, 450),
            Candle(datetime(2025, 10, 27, 10, 1), 102, 105, 98, 102, 600),
        ]

        def fetcher(ticker, start, end, interval, board):
            return daily if interval == 24 else minute

        result = probe_case(CASE, fetcher=fetcher)
        self.assertEqual(result["status"], "CROSS_TIMEFRAME_MISMATCH")
        self.assertFalse(result["volume_matches_daily"])
        self.assertEqual(result["volume_difference_minute_minus_daily"], 50)

    def test_no_minute_candles_is_explicit(self):
        daily = [Candle(datetime(2025, 10, 27), 100, 105, 98, 102, 1000)]

        def fetcher(ticker, start, end, interval, board):
            return daily if interval == 24 else []

        result = probe_case(CASE, fetcher=fetcher)
        self.assertEqual(result["status"], "NO_MINUTE_CANDLES")

    def test_wrong_daily_candle_count_is_rejected(self):
        def fetcher(ticker, start, end, interval, board):
            return []

        result = probe_case(CASE, fetcher=fetcher)
        self.assertEqual(result["status"], "FETCH_OR_VALIDATION_ERROR")
        self.assertIn("Expected exactly one daily candle", result["error"])

    def test_probe_is_read_only_and_keeps_all_cases(self):
        result = run_probe([CASE], fetcher=lambda *a, **k: [])
        self.assertTrue(result["read_only"])
        self.assertEqual(result["case_count"], 1)
        self.assertEqual(result["status_counts"], {"FETCH_OR_VALIDATION_ERROR": 1})
        self.assertIn("No /iss/history", result["source_limitations"][1])


if __name__ == "__main__":
    unittest.main()
