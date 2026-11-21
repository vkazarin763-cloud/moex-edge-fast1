import unittest
from datetime import date, datetime

from research_agent.core import Candle
from research_agent.moex_iss import HistoryRecord
from research_agent.session_mapping import (
    combine_morning_main_history_records,
    reconcile_session_candles,
)


class SessionCompatibleReconciliationTests(unittest.TestCase):
    def test_morning_and_main_history_reconstruct_daily_chart_candle(self):
        morning = [HistoryRecord(
            date(2025, 4, 10), 7579, 14.738, 14.738, 14.525, 14.728, 28103000
        )]
        main = [HistoryRecord(
            date(2025, 4, 10), 33456, 14.728, 15.201, 14.405, 14.457, 126030700
        )]
        combined = combine_morning_main_history_records(morning, main)
        self.assertEqual(len(combined), 1)
        row = combined[0]
        self.assertEqual(row.open, 14.738)
        self.assertEqual(row.high, 15.201)
        self.assertEqual(row.low, 14.405)
        self.assertEqual(row.close, 14.457)
        self.assertEqual(row.volume, 154133700)
        self.assertEqual(row.num_trades, 41035)

    def test_weekday_chart_candle_compares_to_morning_plus_main_not_total(self):
        day = date(2025, 4, 10)
        total = [HistoryRecord(day, 52406, 14.738, 15.201, 14.146, 14.518, 204849700)]
        morning = [HistoryRecord(day, 7579, 14.738, 14.738, 14.525, 14.728, 28103000)]
        main = [HistoryRecord(day, 33456, 14.728, 15.201, 14.405, 14.457, 126030700)]
        chart_candle = [Candle(
            datetime(2025, 4, 10), 14.738, 15.201, 14.405, 14.457, 154133700
        )]
        comparison = combine_morning_main_history_records(morning, main)
        audit = reconcile_session_candles(
            chart_candle, total, comparison_history_records=comparison
        )
        self.assertEqual(audit["trading_days_mismatched"], 0)
        self.assertEqual(audit["trading_days_reconciled"], 1)
        self.assertEqual(audit["comparison_basis"],
                         "MORNING_PLUS_MAIN_WEEKDAY_CANDLES_WEEKEND_FRAGMENTS_MAPPED_SEPARATELY")

    def test_total_history_remains_default_when_no_session_comparison_is_supplied(self):
        day = date(2025, 4, 10)
        total = [HistoryRecord(day, 52406, 14.738, 15.201, 14.146, 14.518, 204849700)]
        chart_candle = [Candle(
            datetime(2025, 4, 10), 14.738, 15.201, 14.405, 14.457, 154133700
        )]
        audit = reconcile_session_candles(chart_candle, total)
        self.assertEqual(audit["trading_days_mismatched"], 1)
        self.assertEqual(audit["comparison_basis"], "TOTAL_SESSION_HISTORY")


    def test_weekend_fragments_are_mapped_but_not_mixed_into_weekday_candle_comparison(self):
        from datetime import timedelta

        day = date(2025, 3, 3)  # Monday
        weekend = Candle(
            datetime(2025, 3, 1), 99.0, 100.0, 98.0, 99.5, 500
        )
        weekday = Candle(
            datetime(2025, 3, 3), 100.0, 102.0, 99.0, 101.0, 1500
        )
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


if __name__ == "__main__":
    unittest.main()
