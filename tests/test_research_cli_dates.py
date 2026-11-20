import unittest
from datetime import datetime, timezone

from research_agent.cli import cap_to_last_completed_moscow_date


class CompletedDailyDateTests(unittest.TestCase):
    def test_excludes_current_moscow_date_even_when_utc_date_is_previous_day(self):
        # 22:30 UTC on Nov 19 is already 01:30 on Nov 20 in Moscow.
        now = datetime(2026, 11, 19, 22, 30, tzinfo=timezone.utc)
        self.assertEqual(
            cap_to_last_completed_moscow_date("2026-11-20", now),
            "2026-11-19",
        )

    def test_preserves_a_requested_historical_end_date(self):
        now = datetime(2026, 11, 20, 8, 0, tzinfo=timezone.utc)
        self.assertEqual(
            cap_to_last_completed_moscow_date("2026-11-18", now),
            "2026-11-18",
        )

    def test_caps_future_requested_end_date(self):
        now = datetime(2026, 11, 20, 8, 0, tzinfo=timezone.utc)
        self.assertEqual(
            cap_to_last_completed_moscow_date("2026-11-25", now),
            "2026-11-19",
        )

    def test_rejects_naive_now(self):
        with self.assertRaises(ValueError):
            cap_to_last_completed_moscow_date("2026-11-20", datetime(2026, 11, 20))


if __name__ == "__main__":
    unittest.main()
