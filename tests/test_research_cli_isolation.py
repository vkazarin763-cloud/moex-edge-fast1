"""CLI-level regression tests for the frozen development/holdout boundary."""
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch

from research_agent import cli
from research_agent.core import Candle


def make_candles():
    start = date(2026, 11, 18)
    return [
        Candle(
            datetime.combine(start + timedelta(days=offset), datetime.min.time()),
            100.0 + offset,
            101.0 + offset,
            99.0 + offset,
            100.5 + offset,
            1000.0,
        )
        for offset in range(4)
    ]


class CliHoldoutIsolationTests(unittest.TestCase):
    def test_development_and_prospective_stages_receive_disjoint_signal_windows(self):
        candles = make_candles()
        observed = {}

        def capture_development(rows):
            observed["development"] = list(rows)
            return {"candidates": {}}

        def capture_cost_stress(rows):
            observed["stress"] = list(rows)
            return {"candidates": {}}

        def capture_holdout(rows, cutoff):
            observed["holdout"] = list(rows)
            observed["cutoff"] = cutoff
            return {"status": "PROSPECTIVE_DATA_AVAILABLE"}

        def capture_portfolio(rows, **kwargs):
            observed["portfolio"] = list(rows["TEST"])
            observed["portfolio_kwargs"] = kwargs
            return {"status": "DEVELOPMENT_WALK_FORWARD_PORTFOLIO"}

        with (
            patch.object(cli, "fetch_candles", return_value=candles) as fetch,
            patch.object(cli, "candle_quality_report", return_value={"status": "TEST"}),
            patch.object(cli, "walk_forward_report", side_effect=capture_development),
            patch.object(cli, "adversarial_cost_check", side_effect=capture_cost_stress),
            patch.object(cli, "prospective_holdout_report", side_effect=capture_holdout),
            patch.object(cli, "walk_forward_portfolio_report", side_effect=capture_portfolio),
        ):
            report = cli.run_universe("2026-11-18", "2026-11-21", ["TEST"])

        cutoff = date.fromisoformat(cli.HOLDOUT_START_DATE)
        self.assertEqual(observed["cutoff"], cli.HOLDOUT_START_DATE)
        self.assertTrue(observed["development"])
        self.assertTrue(observed["stress"])
        self.assertTrue(observed["holdout"])
        self.assertTrue(all(row.timestamp.date() < cutoff for row in observed["development"]))
        self.assertTrue(all(row.timestamp.date() < cutoff for row in observed["stress"]))
        self.assertEqual(observed["holdout"], candles)
        self.assertEqual(observed["portfolio"], candles[:2])
        self.assertEqual(report["development_portfolio"]["status"], "DEVELOPMENT_WALK_FORWARD_PORTFOLIO")
        self.assertEqual(report["results"]["TEST"]["status"], "ANALYZED")
        fetch.assert_called_once()
        self.assertLessEqual(
            date.fromisoformat(fetch.call_args.args[1]),
            cutoff - timedelta(days=3 * 365 + 2),
        )

    def test_empty_fetch_is_reported_as_symbol_error_not_crash(self):
        with patch.object(cli, "fetch_candles", return_value=[]):
            report = cli.run_universe("2026-11-18", "2026-11-21", ["EMPTY"])
        self.assertEqual(report["results"]["EMPTY"]["status"], "DATA_OR_ANALYSIS_ERROR")


if __name__ == "__main__":
    unittest.main()
