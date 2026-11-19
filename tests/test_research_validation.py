import unittest
from datetime import datetime, timedelta

from research_agent.core import Candle, BacktestConfig
from research_agent.validation import walk_forward_report


class WalkForwardTests(unittest.TestCase):
    def test_chronological_folds_and_small_sample_rejected(self):
        rows = []
        start = datetime(2024, 1, 1)
        for i in range(320):
            price = 100 + i * 0.2
            rows.append(Candle(start + timedelta(hours=i), price, price + 0.5,
                               price - 0.5, price, 1000))
        report = walk_forward_report(
            rows, folds=3, warmup_bars=60, min_total_trades=1,
            min_trades_per_fold=0,
            config=BacktestConfig(0, 0, None, None, 2),
        )
        self.assertEqual(len(report["folds"]), 3)
        starts = [f["start"] for f in report["folds"]]
        self.assertEqual(starts, sorted(starts))
        for candidate in report["candidates"].values():
            self.assertIn(candidate["status"], {
                "PROMISING_FOR_INDEPENDENT_REVIEW",
                "REJECT_OR_INSUFFICIENT_EVIDENCE",
            })

    def test_invalid_fold_count_rejected(self):
        rows = [Candle(datetime(2024, 1, 1) + timedelta(hours=i),
                       100, 101, 99, 100, 1000) for i in range(100)]
        with self.assertRaises(ValueError):
            walk_forward_report(rows, folds=1, warmup_bars=55)


if __name__ == "__main__":
    unittest.main()
