import unittest
from datetime import date, datetime

from research_agent.core import Candle
from research_agent.moex_iss import HistoryRecord
from research_agent.session_mapping import (
    SessionMappingError,
    build_trading_day_candles,
    reconcile_session_candles,
)


class TradingDayBarTests(unittest.TestCase):
    def setUp(self):
        # MOEX ISS daily candles for SBER, 1–3 March 2025.
        self.raw = [
            Candle(datetime(2025, 3, 1), 309.84, 310.94, 309.47, 310.11, 1138430),
            Candle(datetime(2025, 3, 2), 309.50, 309.63, 306.80, 307.44, 1885110),
            Candle(datetime(2025, 3, 3), 306.45, 307.92, 300.20, 305.50, 66467290),
        ]
        # Official TQBR history row combines Saturday, Sunday and Monday.
        self.history = [
            HistoryRecord(
                date(2025, 3, 3), 160752,
                309.84, 310.94, 300.20, 305.50, 69490830,
            )
        ]

    def test_history_builds_one_trading_day_bar_with_weekend_sessions_included(self):
        candles, diagnostics = build_trading_day_candles(
            self.history, "2025-03-01", "2025-03-03"
        )
        self.assertEqual(len(candles), 1)
        self.assertEqual(candles[0], Candle(
            datetime(2025, 3, 3), 309.84, 310.94, 300.20, 305.50, 69490830
        ))
        self.assertEqual(diagnostics["research_input_bars"], 1)

    def test_weekend_fragments_reconcile_to_next_tqbr_trading_day(self):
        result = reconcile_session_candles(self.raw, self.history)
        self.assertTrue(result["complete"])
        self.assertEqual(result["raw_weekend_candles"], 2)
        self.assertEqual(result["raw_weekend_candles_mapped"], 2)
        self.assertEqual(result["trading_days_reconciled"], 1)
        self.assertEqual(result["trading_days_mismatched"], 0)

    def test_working_weekend_date_with_same_date_history_stays_on_its_date(self):
        raw = [Candle(datetime(2024, 4, 27), 100, 103, 99, 102, 500)]
        history = [HistoryRecord(date(2024, 4, 27), 12, 100, 103, 99, 102, 500)]
        candles, _ = build_trading_day_candles(history)
        result = reconcile_session_candles(raw, history)
        self.assertEqual(candles[0].timestamp.date(), date(2024, 4, 27))
        self.assertTrue(result["complete"])

    def test_zero_trade_history_rows_are_not_model_bars(self):
        history = [
            HistoryRecord(date(2025, 3, 3), 0, None, None, None, None, 0),
            HistoryRecord(date(2025, 3, 4), 10, 100, 102, 99, 101, 1000),
        ]
        candles, diagnostics = build_trading_day_candles(history)
        self.assertEqual(len(candles), 1)
        self.assertEqual(candles[0].timestamp.date(), date(2025, 3, 4))
        self.assertEqual(diagnostics["zero_trade_history_rows_excluded"], 1)

    def test_positive_trade_history_without_ohlcv_fails_closed(self):
        with self.assertRaises(SessionMappingError):
            build_trading_day_candles([
                HistoryRecord(date(2025, 3, 3), 10)
            ])

    def test_prelaunch_weekend_fragment_requires_same_date_history(self):
        raw = [Candle(datetime(2024, 4, 27), 100, 101, 99, 100, 10)]
        history = [HistoryRecord(date(2024, 4, 29), 20, 100, 102, 98, 101, 1000)]
        result = reconcile_session_candles(raw, history)
        self.assertFalse(result["complete"])
        self.assertEqual(result["raw_weekend_candles_unmapped"], 1)
        self.assertIn("pre-launch", result["unassigned_examples"][0]["reason"])

    def test_unmapped_weekend_fragment_is_reported_not_silently_shifted(self):
        raw = [Candle(datetime(2025, 3, 1), 100, 101, 99, 100, 10)]
        result = reconcile_session_candles(raw, [])
        self.assertFalse(result["complete"])
        self.assertEqual(result["raw_weekend_candles_unmapped"], 1)
        self.assertEqual(result["unassigned_raw_candles"], 1)

    def test_missing_raw_fragments_for_positive_history_date_are_reported(self):
        raw = [Candle(datetime(2025, 3, 3), 100, 102, 99, 101, 1000)]
        history = [
            HistoryRecord(date(2025, 3, 3), 10, 100, 102, 99, 101, 1000),
            HistoryRecord(date(2025, 3, 4), 20, 101, 103, 100, 102, 1500),
        ]
        result = reconcile_session_candles(raw, history)
        self.assertFalse(result["complete"])
        self.assertEqual(result["positive_trade_history_dates"], 2)
        self.assertEqual(result["history_dates_with_raw_fragments"], 1)
        self.assertEqual(result["history_trade_dates_without_raw_fragments"], 1)
        self.assertEqual(result["history_trade_dates_without_raw_fragments_examples"], ["2025-03-04"])
        self.assertEqual(result["raw_history_date_coverage_ratio"], 0.5)
        self.assertEqual(result["raw_history_coverage_status"], "PARTIAL_DATE_COVERAGE")

    def test_no_raw_candles_reports_zero_raw_history_coverage(self):
        history = [
            HistoryRecord(date(2025, 3, 3), 10, 100, 102, 99, 101, 1000),
        ]
        result = reconcile_session_candles([], history)
        self.assertEqual(result["raw_history_coverage_status"], "NO_RAW_CANDLES")
        self.assertEqual(result["history_trade_dates_without_raw_fragments"], 1)
        self.assertEqual(result["raw_history_date_coverage_ratio"], 0.0)


if __name__ == "__main__":
    unittest.main()
