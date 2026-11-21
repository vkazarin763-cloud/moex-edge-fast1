import unittest
from datetime import date, datetime

from research_agent.core import Candle
from research_agent.moex_iss import HistoryRecord
from research_agent.session_mapping import (
    SessionMappingError,
    earliest_session_date,
    latest_completed_session_date,
    normalize_daily_candles,
    combine_morning_main_history_records,
    reconcile_session_candles,
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



class SessionCompatibleReconciliationTests(unittest.TestCase):
    def test_morning_and_main_history_reconstruct_daily_chart_candle(self):
        morning = [HistoryRecord(
            date(2025, 4, 10), 7579, 14.738, 14.738, 14.525, 14.728, 28103000
        )]
        main = [HistoryRecord(
            date(2025, 4, 10), 33456, 14.728, 15.201, 14.405, 14.457, 126030700
        )]
        row = combine_morning_main_history_records(morning, main)[0]
        self.assertEqual(
            (row.open, row.high, row.low, row.close, row.volume, row.num_trades),
            (14.738, 15.201, 14.405, 14.457, 154133700, 41035),
        )

    def test_weekday_chart_candle_compares_to_morning_plus_main_not_total(self):
        day = date(2025, 4, 10)
        total = [HistoryRecord(day, 52406, 14.738, 15.201, 14.146, 14.518, 204849700)]
        morning = [HistoryRecord(day, 7579, 14.738, 14.738, 14.525, 14.728, 28103000)]
        main = [HistoryRecord(day, 33456, 14.728, 15.201, 14.405, 14.457, 126030700)]
        chart = [Candle(datetime(2025, 4, 10), 14.738, 15.201, 14.405, 14.457, 154133700)]
        comparison = combine_morning_main_history_records(morning, main)
        audit = reconcile_session_candles(
            chart, total, comparison_history_records=comparison
        )
        self.assertEqual(audit["trading_days_mismatched"], 0)
        self.assertEqual(audit["trading_days_reconciled"], 1)
        self.assertEqual(audit["morning_plus_main_comparison_dates"], 1)

    def test_total_scope_is_selected_when_ohlc_matches_total_history(self):
        day = date(2025, 10, 27)
        total = [HistoryRecord(day, 31134, 12.74, 12.787, 12.3, 12.323, 122514100)]
        morning = [HistoryRecord(day, 7972, 12.74, 12.787, 12.414, 12.466, 33615100)]
        main = [HistoryRecord(day, 19747, 12.466, 12.56, 12.321, 12.43, 75810400)]
        chart = [Candle(datetime(2025, 10, 27), 12.74, 12.787, 12.3, 12.323, 109020598)]
        comparison = combine_morning_main_history_records(morning, main)
        audit = reconcile_session_candles(chart, total, comparison_history_records=comparison)
        self.assertEqual(audit["total_session_comparison_dates"], 1)
        self.assertEqual(audit["morning_plus_main_comparison_dates"], 0)
        self.assertEqual(audit["trading_days_mismatched"], 1)
        self.assertEqual(audit["mismatch_field_counts"]["volume"], 1)
        self.assertEqual(audit["mismatch_field_counts"]["close"], 0)

    def test_weekend_fragment_is_mapped_but_not_mixed_into_weekday_comparison(self):
        day = date(2025, 3, 3)
        weekend = Candle(datetime(2025, 3, 1), 99.0, 100.0, 98.0, 99.5, 500)
        weekday = Candle(datetime(2025, 3, 3), 100.0, 102.0, 99.0, 101.0, 1500)
        total = [HistoryRecord(day, 100, 99.0, 102.0, 98.0, 101.0, 2000)]
        morning = [HistoryRecord(day, 20, 100.0, 100.5, 99.5, 100.4, 400)]
        main = [HistoryRecord(day, 80, 100.4, 102.0, 99.0, 101.0, 1100)]
        comparison = combine_morning_main_history_records(morning, main)
        audit = reconcile_session_candles(
            [weekend, weekday], total, comparison_history_records=comparison
        )
        self.assertEqual(audit["trading_days_mismatched"], 0)
        self.assertEqual(audit["trading_days_reconciled"], 1)
        self.assertEqual(audit["mapped_weekend_fragments_excluded_from_comparison"], 1)

    def test_total_history_remains_default_without_session_comparison(self):
        day = date(2025, 4, 10)
        total = [HistoryRecord(day, 52406, 14.738, 15.201, 14.146, 14.518, 204849700)]
        chart = [Candle(datetime(2025, 4, 10), 14.738, 15.201, 14.405, 14.457, 154133700)]
        audit = reconcile_session_candles(chart, total)
        self.assertEqual(audit["trading_days_mismatched"], 1)
        self.assertEqual(audit["comparison_basis"], "TOTAL_SESSION_HISTORY")


if __name__ == "__main__":
    unittest.main()
