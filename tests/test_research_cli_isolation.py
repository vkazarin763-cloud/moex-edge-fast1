"""CLI-level regression tests for the frozen development/holdout boundary."""
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch

from research_agent import cli
from research_agent.core import Candle
from research_agent.moex_iss import HistoryRecord


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
        for offset in range(3)
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
            observed["holdout"] = [
                row for row in rows
                if row.timestamp.date() >= date.fromisoformat(cutoff)
            ]
            observed["cutoff"] = cutoff
            return {"status": "PROSPECTIVE_DATA_AVAILABLE"}

        def capture_portfolio(rows, **kwargs):
            observed["portfolio"] = list(rows["TEST"])
            observed["portfolio_kwargs"] = kwargs
            return {"status": "DEVELOPMENT_WALK_FORWARD_PORTFOLIO"}

        history_records = [
            HistoryRecord(date(2023, 11, 20), 10, 90.0, 91.0, 89.0, 90.5, 1000.0),
            HistoryRecord(date(2026, 11, 18), 10, 100.0, 101.0, 99.0, 100.5, 1000.0),
            HistoryRecord(date(2026, 11, 19), 10, 101.0, 102.0, 100.0, 101.5, 1000.0),
            HistoryRecord(date(2026, 11, 20), 10, 102.0, 103.0, 101.0, 102.5, 1000.0),
        ]
        with (
            patch.object(cli, "cap_to_last_completed_moscow_date", return_value="2026-11-20"),
            patch.object(cli, "fetch_history_records", return_value=history_records) as history_fetch,
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
        self.assertEqual(
            [row.timestamp.date() for row in observed["holdout"]],
            [date(2026, 11, 20)],
        )
        self.assertEqual(observed["portfolio"], observed["development"])
        self.assertEqual(report["development_portfolio"]["status"], "DEVELOPMENT_WALK_FORWARD_PORTFOLIO")
        self.assertEqual(report["results"]["TEST"]["status"], "ANALYZED")
        fetch.assert_called_once()
        history_fetch.assert_called_once_with(
            "TEST", "2023-11-19", "2026-11-20", board="TQBR"
        )
        self.assertLessEqual(
            date.fromisoformat(fetch.call_args.args[1]),
            cutoff - timedelta(days=3 * 365 + 2),
        )

    def test_raw_candle_fetch_failure_does_not_block_history_research(self):
        history_records = [
            HistoryRecord(date(2023, 11, 20), 10, 90.0, 91.0, 89.0, 90.5, 1000.0),
            HistoryRecord(date(2026, 11, 18), 10, 100.0, 101.0, 99.0, 100.5, 1000.0),
            HistoryRecord(date(2026, 11, 19), 10, 101.0, 102.0, 100.0, 101.5, 1000.0),
            HistoryRecord(date(2026, 11, 20), 10, 102.0, 103.0, 101.0, 102.5, 1000.0),
        ]
        with (
            patch.object(cli, "cap_to_last_completed_moscow_date", return_value="2026-11-20"),
            patch.object(cli, "fetch_history_records", return_value=history_records),
            patch.object(cli, "fetch_candles", return_value=[]),
        ):
            report = cli.run_universe("2026-11-18", "2026-11-21", ["EMPTY"])
        result = report["results"]["EMPTY"]
        self.assertEqual(result["status"], "ANALYZED")
        self.assertEqual(result["raw_session_candles"], 0)
        self.assertEqual(result["session_date_mapping"]["status"], "NO_RAW_CANDLES")
        self.assertIsNone(result["raw_candle_quality"])
        self.assertTrue(result["data_quality"]["session_date_mapping_complete"])


if __name__ == "__main__":
    unittest.main()
