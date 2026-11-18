import unittest
from datetime import datetime, timezone

from moex_h1_data import CandleDataError, parse_closed_h1_rows


class MoexH1DataTests(unittest.TestCase):
    def setUp(self):
        self.columns = ["open", "close", "high", "low", "begin"]

    def test_parses_closed_candle_and_sorts_rows(self):
        rows = [
            ["101", "102", "103", "100", "2026-11-18 11:00:00"],
            ["100", "101", "102", "99", "2026-11-18 10:00:00"],
        ]
        now = datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc)  # 12:00 Moscow
        result = parse_closed_h1_rows(self.columns, rows, now=now)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["open"], 100)
        self.assertTrue(result[0]["timestamp"].endswith("+00:00"))

    def test_excludes_current_incomplete_and_future_candles(self):
        rows = [
            ["100", "101", "102", "99", "2026-11-18 11:00:00"],
            ["100", "101", "102", "99", "2026-11-18 12:00:00"],
        ]
        now = datetime(2026, 11, 18, 9, 30, tzinfo=timezone.utc)  # 12:30 Moscow
        self.assertEqual(parse_closed_h1_rows(self.columns, rows, now=now), [])

    def test_naive_iss_timestamps_are_moscow_time(self):
        rows = [["100", "101", "102", "99", "2026-11-18 10:00:00"]]
        now = datetime(2026, 11, 18, 8, 30, tzinfo=timezone.utc)
        result = parse_closed_h1_rows(self.columns, rows, now=now)
        self.assertEqual(result[0]["timestamp"], "2026-11-18T07:00:00+00:00")

    def test_duplicate_candles_are_removed(self):
        row = ["100", "101", "102", "99", "2026-11-18 10:00:00"]
        now = datetime(2026, 11, 18, 8, 30, tzinfo=timezone.utc)
        result = parse_closed_h1_rows(self.columns, [row, row], now=now)
        self.assertEqual(len(result), 1)

    def test_missing_columns_and_invalid_ohlc_fail_closed(self):
        with self.assertRaises(CandleDataError):
            parse_closed_h1_rows(["open", "high"], [], now=datetime.now(timezone.utc))
        bad = [["100", "101", "99", "98", "2026-11-18 10:00:00"]]
        with self.assertRaises(CandleDataError):
            parse_closed_h1_rows(self.columns, bad,
                                 now=datetime(2026, 11, 18, 8, 30, tzinfo=timezone.utc))

    def test_missing_or_invalid_values_fail_closed(self):
        rows = [["100", None, "102", "99", "2026-11-18 10:00:00"]]
        with self.assertRaises(CandleDataError):
            parse_closed_h1_rows(self.columns, rows,
                                 now=datetime(2026, 11, 18, 8, 30, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
