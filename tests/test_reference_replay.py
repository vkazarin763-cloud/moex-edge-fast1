"""Deterministic fixtures for the independent execution replay oracle."""
import unittest
from datetime import datetime, timedelta

from research_agent.core import BacktestConfig, Candle, Signal, backtest
from research_agent.reference_audit import compare_replay, reference_replay


def _bars(spec):
    start = datetime(2026, 1, 5, 10, 0)
    return [
        Candle(start + timedelta(days=i), *values, 1000.0)
        for i, values in enumerate(spec)
    ]


class IndependentReferenceReplayTests(unittest.TestCase):
    def _assert_matches(self, bars, signals, config):
        primary = backtest(bars, signals, config)
        reference = reference_replay(bars, signals, config)
        audit = compare_replay(primary, reference)
        self.assertEqual(audit["status"], "REFERENCE_REPLAY_MATCH", audit["mismatches"])
        return primary, reference

    def test_long_stop_gap_and_two_sided_costs(self):
        bars = _bars([
            (100, 101, 99, 100), (100, 101, 99, 100),
            (94, 96, 93, 95), (95, 96, 94, 95),
        ])
        config = BacktestConfig(0.001, 0.0005, 0.03, 0.06, 5)
        primary, reference = self._assert_matches(bars, [Signal(0, 1, "fixture")], config)
        self.assertEqual(reference[0]["exit_reason"], "STOP_GAP")
        self.assertEqual(reference[0]["exit_time"], bars[2].timestamp)
        self.assertAlmostEqual(primary[0].net_return, reference[0]["net_return"])

    def test_long_target_gap_fills_at_target_not_better_open(self):
        bars = _bars([
            (100, 101, 99, 100), (100, 101, 99, 100),
            (108, 111, 107, 110), (110, 111, 109, 110),
        ])
        _, reference = self._assert_matches(
            bars, [Signal(0, 1, "fixture")],
            BacktestConfig(0.0, 0.0, 0.03, 0.06, 5),
        )
        self.assertEqual(reference[0]["exit_reason"], "TARGET_GAP")
        self.assertAlmostEqual(reference[0]["exit_price"], 106.0)

    def test_same_bar_stop_precedes_target_for_long_and_short(self):
        for side in (1, -1):
            bars = _bars([
                (100, 101, 99, 100), (100, 101, 99, 100),
                (100, 108, 92, 100), (100, 101, 99, 100),
            ])
            _, reference = self._assert_matches(
                bars, [Signal(0, side, "fixture")],
                BacktestConfig(0.0, 0.0, 0.03, 0.06, 5),
            )
            self.assertEqual(reference[0]["exit_reason"], "STOP")

    def test_short_target_gap(self):
        bars = _bars([
            (100, 101, 99, 100), (100, 101, 99, 100),
            (93, 95, 90, 92), (92, 94, 91, 93),
        ])
        _, reference = self._assert_matches(
            bars, [Signal(0, -1, "fixture")],
            BacktestConfig(0.0, 0.0, 0.03, 0.06, 5),
        )
        self.assertEqual(reference[0]["exit_reason"], "TARGET_GAP")
        self.assertAlmostEqual(reference[0]["exit_price"], 94.0)

    def test_time_exit_and_terminal_open_trade(self):
        bars = _bars([
            (100, 101, 99, 100), (100, 101, 99, 100),
            (101, 102, 99, 101), (102, 103, 100, 102),
            (103, 104, 101, 103),
        ])
        _, timed = self._assert_matches(
            bars, [Signal(0, 1, "time")],
            BacktestConfig(0.0, 0.0, None, None, 2),
        )
        self.assertEqual(timed[0]["exit_reason"], "TIME")
        self.assertEqual(timed[0]["exit_time"], bars[2].timestamp)

        _, opened = self._assert_matches(
            bars[:3], [Signal(0, 1, "open")],
            BacktestConfig(0.0, 0.0, None, None, 5),
        )
        self.assertEqual(opened[0]["status"], "OPEN")
        self.assertIsNone(opened[0]["net_return"])
        self.assertEqual(opened[0]["exit_reason"], "END_OF_DATA")

    def test_mismatch_is_not_silently_accepted(self):
        bars = _bars([
            (100, 101, 99, 100), (100, 101, 99, 100),
            (94, 96, 93, 95),
        ])
        primary = backtest(bars, [Signal(0, 1, "fixture")],
                           BacktestConfig(0.0, 0.0, 0.03, None, 5))
        altered = reference_replay(bars, [Signal(0, 1, "fixture")],
                                   BacktestConfig(0.0, 0.0, 0.03, None, 5))
        altered[0]["exit_reason"] = "WRONG_FILL"
        audit = compare_replay(primary, altered)
        self.assertEqual(audit["status"], "REFERENCE_REPLAY_MISMATCH")
        self.assertGreater(audit["mismatch_count"], 0)

    def test_invalid_non_integer_horizon_is_rejected(self):
        bars = _bars([
            (100, 101, 99, 100), (100, 101, 99, 100),
        ])
        with self.assertRaises(ValueError):
            reference_replay(bars, [Signal(0, 1, "fixture")],
                             BacktestConfig(0.0, 0.0, None, None, 1.5))


if __name__ == "__main__":
    unittest.main()
