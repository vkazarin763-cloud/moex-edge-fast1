import unittest
from datetime import datetime, timezone

from research_agent.core import Candle
from research_agent.finam_market_data import FinamBar
from research_agent.finam_crosscheck import compare_daily_series, _finam_daily_interval


class FinamMOEXCrosscheckTests(unittest.TestCase):
    def test_daily_request_boundaries_exclude_the_following_utc_date(self):
        # Start at UTC midnight to avoid pulling the prior UTC day's D1 bar.
        # The exclusive end is the final representable instant of the
        # requested final UTC date; live Finam returned a next-day 05:00Z bar
        # when the end was exactly next-day 00:00Z.
        from datetime import date, timedelta

        start_time, end_time = _finam_daily_interval(
            date(2026, 10, 20), date(2026, 11, 18)
        )
        self.assertEqual(start_time, datetime(2026, 10, 20, 0, tzinfo=timezone.utc))
        self.assertEqual(
            end_time,
            datetime(2026, 11, 18, 23, 59, 59, 999999, tzinfo=timezone.utc),
        )
        self.assertEqual(
            end_time + timedelta(microseconds=1),
            datetime(2026, 11, 19, 0, tzinfo=timezone.utc),
        )

    def setUp(self):
        self.moex = [
            Candle(datetime(2026, 11, 18), 100, 102, 99, 101, 1000),
            Candle(datetime(2026, 11, 19), 101, 104, 100, 103, 1200),
        ]
        self.finam = [
            FinamBar(datetime(2026, 11, 17, 21, tzinfo=timezone.utc),
                     100.1, 102.1, 99.1, 101.1, 1005, False),
            FinamBar(datetime(2026, 11, 18, 21, tzinfo=timezone.utc),
                     101, 104, 100, 103, 1200, True),
        ]

    def test_compares_daily_bars_by_moscow_calendar_date(self):
        result = compare_daily_series(self.moex, self.finam)
        self.assertEqual(result["status"], "DATE_COVERAGE_MATCHES")
        self.assertEqual(result["matched_days"], 2)
        self.assertEqual(result["comparisons"][0]["date"], "2026-11-18")
        self.assertAlmostEqual(
            result["comparisons"][0]["prices"]["close"]["difference_pct_of_moex"],
            (0.1 / 101) * 100,
        )
        self.assertTrue(result["comparisons"][1]["finam_is_data_snapshot"])
        self.assertIn("Raw source differences only", result["interpretation"])

    def test_reports_different_date_coverage_without_filling_gaps(self):
        result = compare_daily_series(self.moex, self.finam[:1])
        self.assertEqual(result["status"], "DATE_COVERAGE_DIFFERS")
        self.assertEqual(result["moex_only_dates"], ["2026-11-19"])
        self.assertEqual(result["finam_only_dates"], [])
        self.assertEqual(result["matched_days"], 1)

    def test_reports_no_overlap(self):
        result = compare_daily_series(
            self.moex[:1],
            [FinamBar(datetime(2026, 11, 20, tzinfo=timezone.utc),
                      1, 2, 1, 2, 10, False)],
        )
        self.assertEqual(result["status"], "NO_OVERLAPPING_DATES")
        self.assertEqual(result["comparisons"], [])

    def test_unknown_snapshot_metadata_stays_unknown(self):
        finam = [FinamBar(datetime(2026, 11, 17, 21, tzinfo=timezone.utc),
                          100, 102, 99, 101, 1000, None)]
        result = compare_daily_series(self.moex[:1], finam)
        self.assertIsNone(result['comparisons'][0]['finam_is_data_snapshot'])
    def test_rejects_duplicate_daily_dates_per_source(self):
        duplicate = self.moex + [
            Candle(datetime(2026, 11, 18, 12), 100, 102, 99, 101, 1000)
        ]
        with self.assertRaises(ValueError):
            compare_daily_series(duplicate, self.finam)


if __name__ == "__main__":
    unittest.main()
