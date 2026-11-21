"""Tests for the isolated experimental exit-policy runner."""
import unittest
from datetime import datetime, timedelta

from research_agent.core import Candle, BacktestConfig
from research_agent.experiment_lab import (
    ExitHypothesis, run_experiment_lab,
)


def _candles(count=180):
    rows = []
    start = datetime(2024, 1, 1)
    for i in range(count):
        close = 100.0 + i * 0.15 + (i % 7) * 0.08
        rows.append(Candle(
            start + timedelta(days=i), close, close + 0.5,
            close - 0.5, close, 1000.0 + i,
        ))
    return rows


class ExperimentLabTests(unittest.TestCase):
    def test_holdout_bars_are_excluded_and_counted(self):
        rows = _candles(180)
        rows.extend(_candles(2))
        # Replace the appended timestamps with dates in the prospective period.
        rows[-2] = Candle(datetime(2026, 11, 20), 130, 131, 129, 130, 1000)
        rows[-1] = Candle(datetime(2026, 11, 21), 131, 132, 130, 131, 1000)
        hypothesis = ExitHypothesis(
            "test-config", "test only", BacktestConfig(0, 0, 0.03, 0.06, 20)
        )
        report = run_experiment_lab(
            {"SBER": rows}, hypotheses=(hypothesis,), folds=2,
            warmup_bars=55, min_total_trades=1, min_trades_per_fold=0,
        )
        trial = report["trials"][0]
        self.assertEqual(trial["excluded_holdout_bars"], 2)
        self.assertEqual(trial["development_bars"], 180)
        self.assertEqual(report["multiple_testing_family_size"], 5)

    def test_every_registered_hypothesis_is_retained(self):
        report = run_experiment_lab(
            {"SBER": _candles(80)},
            hypotheses=(
                ExitHypothesis("a", "first", BacktestConfig()),
                ExitHypothesis("b", "second", BacktestConfig(0.001, 0.0005, 0.02, 0.04, 60)),
            ),
            folds=2, warmup_bars=55, min_total_trades=1, min_trades_per_fold=0,
        )
        self.assertEqual(report["trials_total"], 2)
        self.assertEqual({t["hypothesis_id"] for t in report["trials"]}, {"a", "b"})
        self.assertEqual(report["hypothesis_count"], 2)

    def test_duplicate_hypothesis_ids_are_rejected(self):
        item = ExitHypothesis("same", "one", BacktestConfig())
        with self.assertRaises(ValueError):
            run_experiment_lab({"SBER": _candles(80)}, hypotheses=(item, item))

    def test_empty_hypothesis_family_is_rejected(self):
        with self.assertRaises(ValueError):
            run_experiment_lab({"SBER": _candles(80)}, hypotheses=())


if __name__ == "__main__":
    unittest.main()
