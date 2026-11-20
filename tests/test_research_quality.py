import unittest
from datetime import date, datetime, timedelta

from research_agent.core import Candle
from research_agent.moex_iss import HistoryRecord
from research_agent.quality import candle_quality_report, audit_tqbr_history


def make_bars(days, volumes=None):
    start = datetime(2025, 1, 1)
    volumes = volumes or [100.0] * len(days)
    return [
        Candle(start + timedelta(days=day), 100.0, 102.0, 98.0, 101.0, volume)
        for day, volume in zip(days, volumes)
    ]


class CandleQualityReportTests(unittest.TestCase):
    def test_records_history_backed_mapping_without_claiming_official_calendar(self):
        report = candle_quality_report(
            make_bars([0, 1]), session_date_mapping_complete=True,
        )
        self.assertTrue(report["session_date_mapping_complete"])
        self.assertFalse(report["exchange_calendar_verified"])
        self.assertIn("not a direct official-calendar lookup", report["calendar_caveat"])

    def test_reports_date_gap_without_claiming_missing_sessions(self):
        report = candle_quality_report(make_bars([0, 1, 7]), "2025-01-01", "2025-01-08")
        self.assertEqual(report["calendar_gap_count"], 1)
        self.assertEqual(report["calendar_gap_candidates"][0]["classification"],
                         "UNVERIFIED_CALENDAR_GAP")
        self.assertFalse(report["exchange_calendar_verified"])

    def test_reports_short_history_and_zero_volume(self):
        report = candle_quality_report(make_bars([0, 1, 2], [100, 0, 100]))
        self.assertEqual(report["history_status"], "BELOW_WARMUP")
        self.assertEqual(report["zero_volume_bars"], 1)
        self.assertEqual(report["checks"]["ohlc_relationships"], "PASS")

    def test_verified_weekend_trade_is_not_flagged_as_calendar_anomaly(self):
        saturday = make_bars([3])
        records = [HistoryRecord(date(2025, 1, 4), 17)]
        report = candle_quality_report(
            saturday, warmup_bars=0, preferred_min_bars=0,
            history_records=records,
            session_date_mapping_complete=True,
        )
        self.assertEqual(report["weekend_bars"], 1)
        self.assertEqual(report["weekend_session_diagnostics"]["verified_trade_bars"], 1)
        self.assertEqual(report["weekend_session_diagnostics"]["unverified_bars"], 0)
        self.assertEqual(report["status"], "VALID")

    def test_unverified_weekend_trade_remains_a_quality_caveat(self):
        saturday = make_bars([3])
        report = candle_quality_report(
            saturday, warmup_bars=0, preferred_min_bars=0,
            history_records=[HistoryRecord(date(2025, 1, 4), 0)],
        )
        self.assertEqual(report["weekend_session_diagnostics"]["candles_on_zero_trade_dates"], 1)
        self.assertEqual(report["weekend_session_diagnostics"]["unverified_bars"], 1)
        self.assertEqual(report["status"], "VALID_WITH_CAVEATS")

    def test_weekend_without_history_remains_unverified(self):
        report = candle_quality_report(
            make_bars([3]), warmup_bars=0, preferred_min_bars=0,
        )
        self.assertEqual(report["weekend_session_diagnostics"]["dates_without_history_rows"], 1)
        self.assertEqual(report["weekend_session_diagnostics"]["unverified_bars"], 1)
        self.assertEqual(report["status"], "VALID_WITH_CAVEATS")

    def test_reports_requested_range_coverage(self):
        report = candle_quality_report(make_bars([2, 3]), "2025-01-01", "2025-01-06")
        self.assertEqual(report["start_delay_calendar_days"], 2)
        self.assertEqual(report["end_lag_calendar_days"], 2)
        self.assertEqual(report["range_boundary_status"], "BOUNDARY_REQUIRES_REVIEW")

    def test_flags_candles_before_and_after_requested_range(self):
        report = candle_quality_report(make_bars([-1, 0, 5, 6]),
                                        "2025-01-01", "2025-01-06")
        self.assertEqual(report["range_boundary_status"], "OUTSIDE_REQUESTED_RANGE")
        self.assertTrue(report["starts_before_requested_range"])
        self.assertTrue(report["ends_after_requested_range"])
        self.assertEqual(report["out_of_range_bars"], 2)
        self.assertEqual(report["status"], "VALID_WITH_CAVEATS")

    def test_rejects_reversed_requested_range(self):
        with self.assertRaises(ValueError):
            candle_quality_report(make_bars([0, 1]), "2025-01-02", "2025-01-01")

    def test_rejects_invalid_history_thresholds(self):
        with self.assertRaises(ValueError):
            candle_quality_report(make_bars([0, 1]), warmup_bars=10, preferred_min_bars=5)


class TQBRHistoryAuditTests(unittest.TestCase):
    def test_separates_missing_trade_candle_from_zero_trade_session(self):
        candles = make_bars([0, 4])
        records = [
            HistoryRecord(date(2025, 1, 1), 12),
            HistoryRecord(date(2025, 1, 2), 0),
            HistoryRecord(date(2025, 1, 3), 7),
            HistoryRecord(date(2025, 1, 5), 5),
        ]
        report = audit_tqbr_history(candles, records, "2025-01-01", "2025-01-05")
        self.assertEqual(report["status"], "MISSING_CANDLE_ON_RECORDED_TRADE_DATE")
        self.assertEqual(report["missing_candles_on_trade_dates"],
                         [{"date": "2025-01-03", "num_trades": 7}])
        self.assertEqual(report["zero_trade_sessions_without_candles"], ["2025-01-02"])
        self.assertFalse(report["exchange_calendar_verified"])

    def test_missing_history_row_is_unclassified_not_called_a_holiday(self):
        report = audit_tqbr_history(
            make_bars([0, 2]), [HistoryRecord(date(2025, 1, 1), 2)],
            "2025-01-01", "2025-01-03",
        )
        self.assertEqual(report["candles_without_history_record"], ["2025-01-03"])
        self.assertEqual(report["status"], "CROSSCHECK_INCONCLUSIVE")
        self.assertIn("No row is not proof", report["coverage_scope"])

    def test_zero_trade_row_with_candle_is_reported_as_anomaly(self):
        report = audit_tqbr_history(
            make_bars([0]), [HistoryRecord(date(2025, 1, 1), 0)],
            "2025-01-01", "2025-01-01",
        )
        self.assertEqual(report["candles_present_on_zero_trade_dates"], ["2025-01-01"])
        self.assertEqual(report["status"], "CROSSCHECK_INCONCLUSIVE")

    def test_unknown_trade_count_makes_crosscheck_inconclusive(self):
        report = audit_tqbr_history(
            make_bars([0]), [HistoryRecord(date(2025, 1, 1), None)],
            "2025-01-01", "2025-01-01",
        )
        self.assertEqual(report["status"], "CROSSCHECK_INCONCLUSIVE")
        self.assertEqual(report["history_rows_unknown_trade_count"], ["2025-01-01"])

    def test_empty_history_is_not_reported_as_verified(self):
        report = audit_tqbr_history(
            make_bars([0]), [], "2025-01-01", "2025-01-02",
        )
        self.assertEqual(report["status"], "NO_HISTORY_RECORDS")
        self.assertFalse(report["exchange_calendar_verified"])

    def test_candle_outside_audit_range_is_rejected(self):
        with self.assertRaises(ValueError):
            audit_tqbr_history(
                make_bars([0, 2]), [HistoryRecord(date(2025, 1, 1), 1)],
                "2025-01-01", "2025-01-02",
            )

    def test_duplicate_or_out_of_range_history_rows_rejected(self):
        candle = make_bars([0])
        duplicate = [HistoryRecord(date(2025, 1, 1), 1)] * 2
        with self.assertRaises(ValueError):
            audit_tqbr_history(candle, duplicate, "2025-01-01", "2025-01-02")
        with self.assertRaises(ValueError):
            audit_tqbr_history(
                candle, [HistoryRecord(date(2025, 1, 3), 1)],
                "2025-01-01", "2025-01-02",
            )


if __name__ == "__main__":
    unittest.main()
