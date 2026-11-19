import unittest
from datetime import datetime, timedelta

from research_agent.core import Candle
from research_agent.quality import candle_quality_report


def make_bars(days, volumes=None):
    start = datetime(2025, 1, 1)
    volumes = volumes or [100.0] * len(days)
    return [
        Candle(start + timedelta(days=day), 100.0, 102.0, 98.0, 101.0, volume)
        for day, volume in zip(days, volumes)
    ]


class CandleQualityReportTests(unittest.TestCase):
    def test_reports_date_gap_without_claiming_missing_sessions(self):
        report = candle_quality_report(make_bars([0, 1, 7]), "2025-01-01", "2025-01-08")
        self.assertEqual(report["calendar_gap_count"], 1)
        self.assertEqual(report["calendar_gap_candidates"][0]["classification"],
                         "UNVERIFIED_CALENDAR_GAP")
        self.assertFalse(report["exchange_calendar_verified"])
        self.assertIn("not classified as missing sessions", report["calendar_caveat"])

    def test_reports_short_history_and_zero_volume(self):
        report = candle_quality_report(make_bars([0, 1, 2], [100, 0, 100]))
        self.assertEqual(report["history_status"], "BELOW_WARMUP")
        self.assertEqual(report["zero_volume_bars"], 1)
        self.assertEqual(report["checks"]["ohlc_relationships"], "PASS")

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


if __name__ == "__main__":
    unittest.main()
