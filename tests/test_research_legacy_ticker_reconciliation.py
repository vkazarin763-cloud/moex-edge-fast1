"""Regression tests for historical MOEX ticker aliases used only in raw reconciliation."""
import unittest
from datetime import date, datetime
from unittest.mock import patch

from research_agent import cli
from research_agent.core import Candle
from research_agent.moex_iss import HistoryRecord


def make_pair(day, offset):
    opened = 100.0 + offset
    high = opened + 2.0
    low = opened - 1.0
    close = opened + 1.0
    volume = 1000.0 + offset
    candle = Candle(
        datetime.combine(date.fromisoformat(day), datetime.min.time()),
        opened, high, low, close, volume,
    )
    history = HistoryRecord(
        date.fromisoformat(day), 10, opened, high, low, close, volume,
    )
    return candle, history


class LegacyTickerReconciliationTests(unittest.TestCase):
    def test_tcsg_alias_reconciles_old_t_candles_without_changing_model_input(self):
        legacy_pairs = [
            make_pair("2023-11-20", 0),
            make_pair("2024-11-27", 1),
        ]
        current_pairs = [
            make_pair("2024-11-28", 2),
            make_pair("2026-11-18", 3),
            make_pair("2026-11-19", 4),
            make_pair("2026-11-20", 5),
        ]
        legacy_history = [pair[1] for pair in legacy_pairs]
        current_history = [pair[1] for pair in current_pairs]
        raw_candles = [pair[0] for pair in legacy_pairs + current_pairs]
        fetch_calls = []

        def fetch_history(ticker, date_from, date_till, board):
            fetch_calls.append((ticker, date_from, date_till, board))
            return legacy_history if ticker == "TCSG" else current_history

        with (
            patch.object(cli, "cap_to_last_completed_moscow_date", return_value="2026-11-20"),
            patch.object(cli, "fetch_history_records", side_effect=fetch_history),
            patch.object(cli, "fetch_candles", return_value=raw_candles),
            patch.object(cli, "earliest_session_date", return_value=date(2023, 11, 20)),
            patch.object(cli, "walk_forward_report", return_value={"status": "TEST"}),
            patch.object(cli, "adversarial_cost_check", return_value={"status": "TEST"}),
            patch.object(cli, "prospective_holdout_report", return_value={"status": "TEST"}),
            patch.object(cli, "run_experiment_lab", return_value={"lab_version": "test", "trials": []}),
            patch.object(cli, "apply_holm_correction", return_value={"status": "TEST"}),
            patch.object(cli, "walk_forward_portfolio_report", return_value={"status": "TEST"}),
            patch.object(cli, "validate_research_report", return_value={"status": "INDEPENDENT_VALIDATION_INCOMPLETE"}),
        ):
            report = cli.run_universe("2023-11-20", "2026-11-21", ["T"])

        result = report["results"]["T"]
        self.assertEqual(
            fetch_calls,
            [
                ("T", "2023-11-19", "2026-11-20", "TQBR"),
                ("TCSG", "2023-11-19", "2024-11-27", "TQBR"),
            ],
        )
        # T's 2026 split means pre-event candles are excluded from model input.
        # The remaining post-event development sample is too short for research.
        self.assertEqual(result["status"], "INSUFFICIENT_POST_ACTION_HISTORY")
        self.assertEqual(result["research_input_bars"], 3)
        self.assertEqual(result["development_bars"], 2)
        self.assertEqual(
            result["corporate_action_history_basis"]["effective_date"], "2026-04-17"
        )
        self.assertEqual(
            result["corporate_action_history_basis"]["pre_event_bars_excluded"], 1
        )

        # The legacy ticker is used only to reconcile pre-rename raw candles.
        self.assertEqual(result["session_date_mapping"]["unassigned_raw_candles"], 0)
        self.assertEqual(result["session_date_mapping"]["trading_days_reconciled"], 6)
        self.assertEqual(
            result["tqbr_history_crosscheck"]["status"],
            "NO_MISSING_CANDLE_DETECTED_ON_RECORDED_TRADE_DATES",
        )
        self.assertEqual(
            result["raw_reconciliation_history_alias"]["ticker"], "TCSG"
        )
        self.assertFalse(
            result["raw_reconciliation_history_alias"]["used_for_model_input"]
        )


if __name__ == "__main__":
    unittest.main()
