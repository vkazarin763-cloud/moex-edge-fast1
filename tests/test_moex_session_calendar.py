import unittest
from datetime import date, datetime
from urllib.parse import parse_qs, urlparse

from research_agent.core import Candle
from research_agent.session_calendar import (
    SessionCalendarError,
    StockCalendarRecord,
    fetch_stock_calendar,
    latest_completed_session_date,
    normalize_daily_candles,
)


class StockCalendarFetchTests(unittest.TestCase):
    def test_fetches_and_parses_all_days_calendar(self):
        def getter(url, timeout=20, retries=3):
            query = parse_qs(urlparse(url).query)
            self.assertEqual(query["show_all_days"], ["1"])
            self.assertEqual(query["iss.only"], ["off_days"])
            return {
                "off_days": {
                    "columns": ["tradedate", "is_traded", "trade_session_date", "reason"],
                    "data": [
                        ["2025-03-01", 1, "2025-03-03", "W"],
                        ["2025-03-02", 1, "2025-03-03", "W"],
                        ["2025-03-03", 1, None, "N"],
                    ],
                }
            }

        result = fetch_stock_calendar(
            "2025-03-01", "2025-03-03", getter=getter
        )
        self.assertEqual(len(result), 3)
        self.assertEqual(
            result[date(2025, 3, 1)].trade_session_date,
            date(2025, 3, 3),
        )
        self.assertEqual(result[date(2025, 3, 3)].reason, "N")


class WeekendSessionAggregationTests(unittest.TestCase):
    def setUp(self):
        self.calendar = {
            date(2025, 2, 28): StockCalendarRecord(
                date(2025, 2, 28), 1, None, "N"
            ),
            date(2025, 3, 1): StockCalendarRecord(
                date(2025, 3, 1), 1, date(2025, 3, 3), "W"
            ),
            date(2025, 3, 2): StockCalendarRecord(
                date(2025, 3, 2), 1, date(2025, 3, 3), "W"
            ),
            date(2025, 3, 3): StockCalendarRecord(
                date(2025, 3, 3), 1, None, "N"
            ),
            date(2025, 3, 4): StockCalendarRecord(
                date(2025, 3, 4), 1, None, "N"
            ),
            date(2025, 3, 7): StockCalendarRecord(
                date(2025, 3, 7), 1, None, "N"
            ),
        }
        self.raw = [
            Candle(datetime(2025, 3, 1), 100, 105, 99, 103, 10),
            Candle(datetime(2025, 3, 2), 103, 108, 102, 107, 20),
            Candle(datetime(2025, 3, 3), 107, 110, 106, 109, 30),
            Candle(datetime(2025, 3, 4), 109, 112, 108, 111, 40),
        ]

    def test_weekend_bars_are_combined_with_their_official_session_date(self):
        normalized, diagnostics = normalize_daily_candles(
            self.raw, self.calendar, max_session_date="2025-03-04"
        )
        self.assertEqual(
            [bar.timestamp.date() for bar in normalized],
            [date(2025, 3, 3), date(2025, 3, 4)],
        )
        monday = normalized[0]
        self.assertEqual(
            (monday.open, monday.high, monday.low, monday.close, monday.volume),
            (100, 110, 99, 109, 60),
        )
        self.assertEqual(diagnostics["weekend_session_candles_mapped"], 2)
        self.assertEqual(diagnostics["normalized_session_candles"], 2)
        self.assertTrue(diagnostics["exchange_calendar_verified"])

    def test_weekend_bars_are_excluded_until_their_session_date_completes(self):
        normalized, diagnostics = normalize_daily_candles(
            self.raw[:2], self.calendar, max_session_date="2025-03-02"
        )
        self.assertEqual(normalized, [])
        self.assertEqual(
            diagnostics["source_bars_excluded_beyond_completed_session_cutoff"],
            2,
        )

    def test_latest_completed_session_skips_weekend_session_mapped_forward(self):
        self.assertEqual(
            latest_completed_session_date(self.calendar, "2025-03-02"),
            date(2025, 2, 28),
        )
        self.assertEqual(
            latest_completed_session_date(self.calendar, "2025-03-03"),
            date(2025, 3, 3),
        )

    def test_missing_calendar_row_is_not_silently_accepted(self):
        with self.assertRaises(SessionCalendarError):
            normalize_daily_candles(
                [Candle(datetime(2025, 3, 8), 1, 2, 1, 2, 10)],
                self.calendar,
            )

    def test_candle_on_non_trading_date_is_rejected(self):
        calendar = {
            date(2025, 3, 8): StockCalendarRecord(
                date(2025, 3, 8), 0, None, "H"
            )
        }
        with self.assertRaises(SessionCalendarError):
            normalize_daily_candles(
                [Candle(datetime(2025, 3, 8), 1, 2, 1, 2, 10)],
                calendar,
            )


if __name__ == "__main__":
    unittest.main()
