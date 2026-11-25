import unittest
from datetime import datetime, timezone

from research_agent.cli import cap_to_last_completed_moscow_date, research_exit_code


def complete_analyzed_results(count=44):
    return {
        f"TICKER{i:02d}": {"status": "ANALYZED"}
        for i in range(count)
    }


class ResearchExitCodeTests(unittest.TestCase):
    def test_pass_returns_zero(self):
        report = {
            "results": complete_analyzed_results(),
            "independent_validation": {"status": "INDEPENDENT_VALIDATION_PASS"},
        }
        self.assertEqual(research_exit_code(report, 44), 0)

    def test_fail_returns_two(self):
        report = {
            "results": complete_analyzed_results(),
            "independent_validation": {"status": "INDEPENDENT_VALIDATION_FAIL"},
        }
        self.assertEqual(research_exit_code(report, 44), 2)

    def test_incomplete_returns_three(self):
        report = {
            "results": complete_analyzed_results(),
            "independent_validation": {"status": "INDEPENDENT_VALIDATION_INCOMPLETE"},
        }
        self.assertEqual(research_exit_code(report, 44), 3)

    def test_missing_validation_fails_closed_without_recursion(self):
        self.assertEqual(
            research_exit_code({"results": complete_analyzed_results()}, 44), 3
        )

    def test_no_analyzed_tickers_returns_nonzero(self):
        # Empty results cannot establish full-universe coverage, so fail closed.
        self.assertEqual(
            research_exit_code(
                {"independent_validation": {"status": "INDEPENDENT_VALIDATION_PASS"}},
                0,
            ),
            4,
        )


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
