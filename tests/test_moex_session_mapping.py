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
    def test_weekend_bars_map_to_next_positive_history_date_and_aggregate(self):
        history = [
            HistoryRecord(date(2025, 3, 3), 15),
            HistoryRecord(date(2025, 3, 4), 12),
        ]
        raw = [
            Candle(datetime(2025, 3, 1), 100, 105, 99, 103, 10),
            Candle(datetime(2025, 3, 2), 103, 108, 102, 107, 20),
            Candle(datetime(2025, 3, 3), 107, 110, 106, 109, 30),
            Candle(datetime(2025, 3, 4), 109, 112, 108, 111, 40),
        ]
        normalized, diagnostics = normalize_daily_candles(
            raw, history, max_session_date="2025-03-04"
        )
        self.assertEqual(
            [item.timestamp.date() for item in normalized],
            [date(2025, 3, 3), date(2025, 3, 4)],
        )
        monday = normalized[0]
        self.assertEqual(
            (monday.open, monday.high, monday.low, monday.close, monday.volume),
            (100, 110, 99, 109, 60),
        )
        self.assertEqual(diagnostics["weekend_candles_mapped"], 2)
        self.assertEqual(diagnostics["unresolved_weekend_candles"], [])
        self.assertTrue(diagnostics["session_date_mapping_verified"])

    def test_same_date_positive_history_keeps_transferred_weekend_workday(self):
        history = [
            HistoryRecord(date(2025, 3, 1), 4),
            HistoryRecord(date(2025, 3, 3), 15),
        ]
        raw = [
            Candle(datetime(2025, 3, 1), 100, 105, 99, 103, 10),
            Candle(datetime(2025, 3, 3), 103, 108, 102, 107, 20),
        ]
        normalized, diagnostics = normalize_daily_candles(raw, history)
        self.assertEqual(
            [item.timestamp.date() for item in normalized],
            [date(2025, 3, 1), date(2025, 3, 3)],
        )
        self.assertEqual(
            diagnostics["weekend_session_mappings"][0]["mapping_basis"],
            "same-date positive NUMTRADES",
        )

    def test_weekend_session_is_excluded_until_target_date_completes(self):
        history = [HistoryRecord(date(2025, 3, 3), 15)]
        raw = [
            Candle(datetime(2025, 3, 1), 100, 105, 99, 103, 10),
            Candle(datetime(2025, 3, 2), 103, 108, 102, 107, 20),
        ]
        normalized, diagnostics = normalize_daily_candles(
            raw, history, max_session_date="2025-03-02"
        )
        self.assertEqual(normalized, [])
        self.assertEqual(
            diagnostics["source_bars_excluded_beyond_completed_session_cutoff"],
            2,
        )

    def test_weekend_without_confirmable_target_is_excluded_and_reported(self):
        raw = [
            Candle(datetime(2025, 3, 1), 100, 105, 99, 103, 10),
            Candle(datetime(2025, 3, 2), 103, 108, 102, 107, 0),
        ]
        normalized, diagnostics = normalize_daily_candles(raw, [])
        self.assertEqual(normalized, [])
        self.assertEqual(len(diagnostics["unresolved_weekend_candles"]), 2)
        self.assertFalse(diagnostics["session_date_mapping_verified"])

    def test_duplicate_history_dates_are_rejected(self):
        duplicate = [
            HistoryRecord(date(2025, 3, 3), 15),
            HistoryRecord(date(2025, 3, 3), 16),
        ]
        with self.assertRaises(SessionMappingError):
            normalize_daily_candles([], duplicate)


if __name__ == "__main__":
    unittest.main()
