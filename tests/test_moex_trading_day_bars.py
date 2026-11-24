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

    def test_known_split_price_basis_ratios_are_flagged_without_adjustment(self):
        events = [
            ("GMKN", date(2024, 4, 3), 100.0),
            ("TRNFP", date(2024, 2, 20), 100.0),
            ("VTBR", date(2024, 7, 12), 1.0 / 5000.0),
            ("PLZL", date(2025, 3, 26), 10.0),
            ("T", date(2026, 4, 16), 10.0),
        ]
        for ticker, trade_date, factor in events:
            with self.subTest(ticker=ticker):
                raw = [Candle(
                    datetime.combine(trade_date, datetime.min.time()),
                    100, 110, 90, 105, 1000,
                )]
                history = [HistoryRecord(
                    trade_date, 20,
                    100 * factor, 110 * factor, 90 * factor, 105 * factor, 1000,
                )]
                result = reconcile_session_candles(raw, history, ticker=ticker)
                self.assertEqual(result["price_scale_mismatch_dates"], 1)
                self.assertEqual(result["known_price_basis_match_count"], 1)
                self.assertEqual(result["unexplained_price_scale_mismatch_count"], 0)
                self.assertEqual(
                    result["price_scale_mismatch_examples"][0]["classification"],
                    "MATCHES_KNOWN_PRE_EVENT_PRICE_BASIS",
                )
                self.assertEqual(
                    result["price_scale_mismatch_examples"][0]["history_to_raw_volume_factor"],
                    1.0,
                )
                # The audit is diagnostic only: source OHLC values are not rewritten.
                self.assertEqual(raw[0].close, 105)
                self.assertEqual(history[0].close, 105 * factor)


    def test_documented_split_ohlc_basis_does_not_hide_volume_mismatch(self):
        trade_date = date(2024, 4, 3)
        raw = [Candle(datetime.combine(trade_date, datetime.min.time()), 100, 110, 90, 105, 1000)]
        history = [HistoryRecord(trade_date, 20, 1, 1.1, 0.9, 1.05, 1100)]
        result = reconcile_session_candles(raw, history, ticker="GMKN")
        self.assertEqual(result["documented_corporate_action_mismatch_dates"], 0)
        self.assertEqual(result["unexplained_mismatch_dates"], 1)
        self.assertFalse(result["complete"])

    def test_documented_split_only_price_basis_is_not_an_unexplained_mismatch(self):
        trade_date = date(2024, 4, 3)
        raw = [Candle(datetime.combine(trade_date, datetime.min.time()), 100, 110, 90, 105, 1000)]
        history = [HistoryRecord(trade_date, 20, 1, 1.1, 0.9, 1.05, 1000)]
        result = reconcile_session_candles(raw, history, ticker="GMKN")
        self.assertEqual(result["trading_days_mismatched"], 1)
        self.assertEqual(result["documented_corporate_action_mismatch_dates"], 1)
        self.assertEqual(result["unexplained_mismatch_dates"], 0)
        self.assertTrue(result["complete"])
        self.assertEqual(result["status"], "RECONCILED_WITH_DOCUMENTED_CORPORATE_ACTIONS")

    def test_known_split_price_basis_accepts_reciprocal_direction(self):
        trade_date = date(2024, 4, 3)
        raw = [Candle(datetime.combine(trade_date, datetime.min.time()), 100, 110, 90, 105, 1000)]
        history = [HistoryRecord(trade_date, 20, 1, 1.1, 0.9, 1.05, 1000)]
        result = reconcile_session_candles(raw, history, ticker="GMKN")
        audit = result["price_scale_mismatch_examples"][0]
        self.assertEqual(audit["classification"], "MATCHES_KNOWN_PRE_EVENT_PRICE_BASIS")
        self.assertEqual(audit["matched_ratio_direction"], "RECIPROCAL_DOCUMENTED_FACTOR")

    def test_known_corporate_action_factor_after_effective_date_is_not_applied(self):
        trade_date = date(2024, 4, 5)
        raw = [Candle(datetime.combine(trade_date, datetime.min.time()), 100, 110, 90, 105, 1000)]
        history = [HistoryRecord(trade_date, 20, 10000, 11000, 9000, 10500, 1000)]
        result = reconcile_session_candles(raw, history, ticker="GMKN")
        self.assertEqual(result["known_price_basis_match_count"], 0)
        self.assertEqual(result["unexplained_price_scale_mismatch_count"], 1)

    def test_unreferenced_price_scale_ratio_remains_unexplained(self):
        trade_date = date(2025, 1, 2)
        raw = [Candle(datetime.combine(trade_date, datetime.min.time()), 100, 110, 90, 105, 1000)]
        history = [HistoryRecord(trade_date, 20, 1000, 1100, 900, 1050, 1000)]
        result = reconcile_session_candles(raw, history, ticker="UNKNOWN")
        self.assertEqual(result["price_scale_mismatch_dates"], 1)
        self.assertEqual(result["known_price_basis_match_count"], 0)
        self.assertEqual(result["unexplained_price_scale_mismatch_count"], 1)
        self.assertEqual(
            result["price_scale_mismatch_examples"][0]["classification"],
            "NO_KNOWN_CORPORATE_ACTION_REFERENCE",
        )

    def test_official_2026_weekday_additional_sessions_map_to_next_trade_date(self):
        sessions = [
            (date(2026, 2, 23), date(2026, 2, 24)),
            (date(2026, 5, 1), date(2026, 5, 4)),
            (date(2026, 6, 12), date(2026, 6, 15)),
            (date(2026, 11, 4), date(2026, 11, 5)),
        ]
        for session_date, trade_date in sessions:
            with self.subTest(session_date=session_date):
                raw = [
                    Candle(datetime.combine(session_date, datetime.min.time()), 100, 101, 99, 100, 10),
                    Candle(datetime.combine(trade_date, datetime.min.time()), 100, 102, 98, 101, 20),
                ]
                history = [
                    HistoryRecord(session_date, 0, None, None, None, None, 0),
                    HistoryRecord(trade_date, 30, 100, 102, 98, 101, 30),
                ]
                result = reconcile_session_candles(raw, history)
                self.assertTrue(result["complete"])
                self.assertEqual(result["trading_days_reconciled"], 1)
                self.assertEqual(result["unassigned_raw_candles"], 0)
                self.assertEqual(result["raw_weekday_additional_session_candles"], 1)
                self.assertEqual(result["raw_weekday_additional_session_candles_mapped"], 1)
                self.assertEqual(result["raw_weekday_additional_session_candles_unmapped"], 0)

    def test_unlisted_weekday_without_history_is_not_silently_mapped(self):
        raw = [Candle(datetime(2026, 3, 2), 100, 101, 99, 100, 10)]
        result = reconcile_session_candles(raw, [])
        self.assertFalse(result["complete"])
        self.assertEqual(result["raw_weekday_additional_session_candles"], 0)
        self.assertEqual(result["unassigned_raw_candles"], 1)

    def test_mapped_weekend_candle_count_counts_fragments_not_unique_dates(self):
        raw = [
            Candle(datetime(2025, 3, 1, 10), 100, 102, 99, 101, 10),
            Candle(datetime(2025, 3, 1, 12), 101, 103, 100, 102, 20),
            Candle(datetime(2025, 3, 3), 102, 104, 101, 103, 30),
        ]
        history = [
            HistoryRecord(date(2025, 3, 3), 30, 100, 104, 99, 103, 60)
        ]
        result = reconcile_session_candles(raw, history)
        self.assertTrue(result["complete"])
        self.assertEqual(result["raw_weekend_candles"], 2)
        self.assertEqual(result["raw_weekend_candles_mapped"], 2)
        self.assertEqual(result["raw_weekend_candles_unmapped"], 0)

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

    def test_reconciliation_reports_full_reason_and_field_counts_beyond_examples(self):
        raw = [
            Candle(datetime(2025, 2, 22), 100, 101, 99, 100, 10),
            Candle(datetime(2025, 3, 3), 100, 102, 98, 101, 20),
            Candle(datetime(2025, 3, 4), 101, 103, 100, 102, 30),
        ]
        history = [
            HistoryRecord(date(2025, 3, 3), 20, 100, 102, 98, 101, 20),
            HistoryRecord(date(2025, 3, 4), 20, 101, 104, 100, 102, 30),
        ]
        result = reconcile_session_candles(raw, history)
        self.assertEqual(result["raw_candles"], 3)
        self.assertEqual(result["mapped_raw_candles"], 2)
        self.assertEqual(result["unassigned_raw_candles"], 1)
        self.assertEqual(result["unassigned_reason_counts"], {
            "PRELAUNCH_WEEKEND_UNCONFIRMED": 1,
        })
        self.assertEqual(result["mismatch_reason_counts"], {
            "AGGREGATED_OHLCV_DIFFERS": 1,
        })
        self.assertEqual(result["mismatch_field_counts"]["high"], 1)
        self.assertEqual(result["mismatch_field_counts"]["open"], 0)
        self.assertEqual(sum(result["unassigned_reason_counts"].values()), 1)
        self.assertEqual(sum(result["mismatch_reason_counts"].values()), 1)

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
