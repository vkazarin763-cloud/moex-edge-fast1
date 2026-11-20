import unittest
from datetime import datetime, timezone

from research_agent.core import Candle
from research_agent.finam_market_data import FinamBar
from research_agent.timeframe_reconciliation import (
    reconcile_daily_to_hourly,
    reconcile_moex_and_finam,
)


class TimeframeReconciliationTests(unittest.TestCase):
    def test_moex_daily_includes_0600_open_and_volume_bucket(self):
        day = datetime(2026, 11, 18)
        daily = [Candle(day, 99, 105, 98, 104, 1250)]
        hourly = [
            Candle(datetime(2026, 11, 18, 6), 99, 99, 99, 99, 250),
            Candle(datetime(2026, 11, 18, 7), 100, 105, 98, 104, 1000),
        ]
        result = reconcile_daily_to_hourly(
            daily, hourly, source="MOEX ISS", opening_bucket_hour=6
        )
        self.assertEqual(result["status"], "RECONCILED")
        self.assertEqual(result["matched_days"], 1)
        self.assertTrue(all(
            check["matches"]
            for check in result["comparisons"][0]["checks"].values()
        ))
        self.assertTrue(result["comparisons"][0]["opening_bucket_present"])

    def test_finam_daily_uses_main_session_and_excludes_0600_bucket(self):
        daily = [FinamBar(
            datetime(2026, 11, 18, 4, tzinfo=timezone.utc),
            100, 105, 98, 104, 1000, False,
        )]
        hourly = [
            FinamBar(datetime(2026, 11, 18, 3, tzinfo=timezone.utc),
                     99, 99, 99, 99, 250, False),
            FinamBar(datetime(2026, 11, 18, 4, tzinfo=timezone.utc),
                     100, 105, 98, 104, 1000, False),
        ]
        result = reconcile_daily_to_hourly(
            daily, hourly, source="Finam", finam=True, excluded_hours={6}
        )
        self.assertEqual(result["status"], "RECONCILED")
        self.assertEqual(result["comparisons"][0]["h1_bars_total"], 2)
        self.assertEqual(result["comparisons"][0]["h1_bars_eligible"], 1)
        self.assertTrue(all(
            check["matches"]
            for check in result["comparisons"][0]["checks"].values()
        ))

    def test_snapshot_true_is_excluded_unknown_is_retained_and_flagged(self):
        daily = [FinamBar(
            datetime(2026, 11, 18, 4, tzinfo=timezone.utc),
            100, 105, 98, 104, 1000, False,
        )]
        hourly = [
            FinamBar(datetime(2026, 11, 18, 4, tzinfo=timezone.utc),
                     100, 105, 98, 104, 1000, None),
            FinamBar(datetime(2026, 11, 18, 5, tzinfo=timezone.utc),
                     104, 110, 103, 109, 500, True),
        ]
        result = reconcile_daily_to_hourly(
            daily, hourly, source="Finam", finam=True
        )
        self.assertEqual(result["finam_snapshot_true_bars_excluded"], 1)
        self.assertEqual(result["finam_snapshot_unknown_bars_retained"], 1)
        self.assertEqual(result["comparisons"][0]["h1_bars_total"], 1)

    def test_missing_h1_is_not_reported_as_match(self):
        daily = [Candle(datetime(2026, 11, 18), 10, 12, 9, 11, 100)]
        result = reconcile_daily_to_hourly(
            daily, [], source="MOEX ISS", opening_bucket_hour=6
        )
        self.assertEqual(result["status"], "NO_H1_BARS")
        self.assertEqual(result["daily_days_without_h1"], ["2026-11-18"])
        self.assertEqual(result["comparisons"][0]["status"], "NO_ELIGIBLE_H1_BARS")

    def test_high_low_disagreement_is_reported_not_silently_fixed(self):
        daily = [Candle(datetime(2026, 11, 18), 100, 120, 98, 104, 1000)]
        hourly = [Candle(datetime(2026, 11, 18, 7), 100, 110, 99, 104, 1000)]
        result = reconcile_daily_to_hourly(
            daily, hourly, source="MOEX ISS", opening_bucket_hour=6
        )
        self.assertEqual(result["status"], "PARTIAL_OR_DIFFERING")
        self.assertEqual(result["comparisons"][0]["checks"]["high"]["matches"], False)
        self.assertEqual(result["comparisons"][0]["checks"]["low"]["matches"], False)

    def test_duplicate_hourly_timestamp_is_rejected(self):
        row = Candle(datetime(2026, 11, 18, 7), 100, 105, 98, 104, 1000)
        with self.assertRaises(ValueError):
            reconcile_daily_to_hourly(
                [], [row, row], source="MOEX ISS", opening_bucket_hour=6
            )

    def test_combined_report_keeps_sources_independent(self):
        moex_daily = [Candle(datetime(2026, 11, 18), 99, 105, 98, 104, 1250)]
        moex_h1 = [
            Candle(datetime(2026, 11, 18, 6), 99, 99, 99, 99, 250),
            Candle(datetime(2026, 11, 18, 7), 100, 105, 98, 104, 1000),
        ]
        finam_daily = [FinamBar(
            datetime(2026, 11, 18, 4, tzinfo=timezone.utc),
            100, 105, 98, 104, 1000, False,
        )]
        finam_h1 = [FinamBar(
            datetime(2026, 11, 18, 4, tzinfo=timezone.utc),
            100, 105, 98, 104, 1000, False,
        )]
        result = reconcile_moex_and_finam(
            moex_daily=moex_daily, moex_hourly=moex_h1,
            finam_daily=finam_daily, finam_hourly=finam_h1,
        )
        self.assertEqual(result["moex"]["status"], "RECONCILED")
        self.assertEqual(result["finam"]["status"], "RECONCILED")
        self.assertIn("not modified or merged", result["safety"])


if __name__ == "__main__":
    unittest.main()
