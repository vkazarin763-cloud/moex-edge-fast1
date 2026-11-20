import unittest
from datetime import date, datetime

from research_agent.core import Candle
from research_agent.moex_iss import HistoryRecord
from research_agent.session_mapping import (
    SessionMappingError,
    earliest_session_date,
    latest_completed_session_date,
    normalize_daily_candles,
)


class SessionDateBoundsTests(unittest.TestCase):
    def test_latest_and_earliest_dates_use_positive_tqbr_trades(self):
        records = {
            "AAA": [
                HistoryRecord(date(2025, 3, 3), 15),
                HistoryRecord(date(2025, 3, 4), 12),
            ],
            "BBB": [
                HistoryRecord(date(2025, 2, 28), 20),
                HistoryRecord(date(2025, 3, 5), 0),
            ],
        }
        self.assertEqual(
            latest_completed_session_date(records, "2025-03-04"),
            date(2025, 3, 4),
        )
        self.assertEqual(
            earliest_session_date(records, "2025-02-27", "2025-03-04"),
            date(2025, 2, 28),
        )

    def test_missing_positive_trade_history_fails_closed(self):
        with self.assertRaises(SessionMappingError):
            latest_completed_session_date(
                {"AAA": [HistoryRecord(date(2025, 3, 3), 0)]},
                "2025-03-04",
            )


class WeekendHistoryMappingTests(unittest.TestCase):
    def test_weekend_bars_are_preserved_separately_without_history(self):
        raw = [
            Candle(datetime(2025, 3, 1), 100, 105, 99, 103, 10),
            Candle(datetime(2025, 3, 2), 103, 108, 102, 107, 20),
            Candle(datetime(2025, 3, 3), 107, 110, 106, 109, 30),
        ]
        normalized, diagnostics = normalize_daily_candles(raw, [
            HistoryRecord(date(2025, 3, 3), 15),
        ], max_session_date="2025-03-03")
        self.assertEqual(
            [item.timestamp.date() for item in normalized],
            [date(2025, 3, 1), date(2025, 3, 2), date(2025, 3, 3)],
        )
        self.assertEqual(
            [(item.open, item.high, item.low, item.close, item.volume)
             for item in normalized[:2]],
            [(100, 105, 99, 103, 10), (103, 108, 102, 107, 20)],
        )
        self.assertEqual(diagnostics["weekend_candles_preserved"], 2)
        self.assertEqual(len(diagnostics["unresolved_weekend_candles"]), 2)
        self.assertEqual(diagnostics["sessions_combining_multiple_calendar_dates"], [])
        self.assertFalse(diagnostics["session_date_mapping_complete"])

    def test_same_date_positive_history_confirms_weekend_bar_without_merging(self):
        raw = [
            Candle(datetime(2025, 3, 1), 100, 105, 99, 103, 10),
            Candle(datetime(2025, 3, 3), 103, 108, 102, 107, 20),
        ]
        normalized, diagnostics = normalize_daily_candles(
            raw, [HistoryRecord(date(2025, 3, 1), 4),
                  HistoryRecord(date(2025, 3, 3), 15)]
        )
        self.assertEqual(
            [item.timestamp.date() for item in normalized],
            [date(2025, 3, 1), date(2025, 3, 3)],
        )
        self.assertTrue(diagnostics["weekend_session_mappings"][0][
            "verified_by_tqbr_history"
        ])
        self.assertTrue(diagnostics["session_date_mapping_complete"])

    def test_unfinished_weekend_after_cutoff_is_excluded_without_relabeling(self):
        raw = [
            Candle(datetime(2025, 3, 1), 100, 105, 99, 103, 10),
            Candle(datetime(2025, 3, 2), 103, 108, 102, 107, 20),
        ]
        normalized, diagnostics = normalize_daily_candles(
            raw, [], max_session_date="2025-02-28"
        )
        self.assertEqual(normalized, [])
        self.assertEqual(
            diagnostics["source_bars_excluded_beyond_completed_session_cutoff"], 2
        )

    def test_weekend_zero_volume_is_preserved_but_unverified(self):
        raw = [Candle(datetime(2025, 3, 1), 100, 105, 99, 103, 0)]
        normalized, diagnostics = normalize_daily_candles(raw, [])
        self.assertEqual(len(normalized), 1)
        self.assertFalse(diagnostics["session_date_mapping_complete"])
        self.assertEqual(diagnostics["unresolved_weekend_candles"][0]["volume"], 0)

    def test_duplicate_history_dates_are_rejected(self):
        duplicate = [
            HistoryRecord(date(2025, 3, 3), 15),
            HistoryRecord(date(2025, 3, 3), 16),
        ]
        with self.assertRaises(SessionMappingError):
            normalize_daily_candles([], duplicate)


if __name__ == "__main__":
    unittest.main()
