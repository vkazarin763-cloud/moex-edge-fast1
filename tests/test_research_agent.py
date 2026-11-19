import unittest
from datetime import datetime, timedelta

from research_agent.core import (
    Candle, Signal, BacktestConfig, validate_candles, backtest, summarize,
)


def bars(prices):
    start = datetime(2025, 1, 1)
    result = []
    for i, price in enumerate(prices):
        result.append(Candle(start + timedelta(hours=i), price, price * 1.02,
                             price * 0.98, price, 1000))
    return result


class ValidationTests(unittest.TestCase):
    def test_valid_series(self):
        self.assertEqual(len(validate_candles(bars([100, 101, 102]))), 3)

    def test_duplicate_timestamp_rejected(self):
        data = bars([100, 101])
        data[1] = Candle(data[0].timestamp, 101, 103, 99, 101, 1000)
        with self.assertRaises(ValueError):
            validate_candles(data)

    def test_invalid_ohlc_rejected(self):
        data = bars([100, 101])
        data[1] = Candle(data[1].timestamp, 101, 100, 99, 101, 1000)
        with self.assertRaises(ValueError):
            validate_candles(data)


class BacktestTests(unittest.TestCase):
    def test_signal_enters_next_bar_open(self):
        data = bars([100, 100, 100, 100, 100, 100])
        # Entry at bar 2 open=100, target reached on bar 3.
        data[3] = Candle(data[3].timestamp, 100, 110, 99, 105, 1000)
        result = backtest(data, [Signal(1, 1, "test")],
                          BacktestConfig(0, 0, 0.05, 0.05, 5))
        self.assertEqual(result[0].entry_time, data[2].timestamp)
        self.assertEqual(result[0].exit_reason, "TARGET")
        self.assertAlmostEqual(result[0].net_return, 0.05)

    def test_stop_wins_when_both_hit_same_bar(self):
        data = bars([100, 100, 100, 100])
        data[2] = Candle(data[2].timestamp, 100, 110, 90, 100, 1000)
        result = backtest(data, [Signal(1, 1, "test")],
                          BacktestConfig(0, 0, 0.05, 0.05, 2))
        self.assertEqual(result[0].exit_reason, "STOP")

    def test_open_terminal_trade_not_counted_as_closed(self):
        data = bars([100, 100, 100, 100])
        result = backtest(data, [Signal(1, 1, "test")],
                          BacktestConfig(0, 0, None, None, None))
        stats = summarize(result)
        self.assertEqual(stats["closed_trades"], 0)
        self.assertEqual(stats["open_terminal_trades_excluded"], 1)
        self.assertIsNone(stats["average_net_return"])

    def test_two_sided_costs(self):
        data = bars([100, 100, 100, 110])
        result = backtest(data, [Signal(1, 1, "test")],
                          BacktestConfig(0.001, 0.0005, 0.05, 0.05, 3))
        self.assertAlmostEqual(result[0].net_return, 0.05 - 0.003)

    def test_overlapping_signals_are_skipped(self):
        data = bars([100] * 8)
        data[3] = Candle(data[3].timestamp, 100, 106, 99, 105, 1000)
        result = backtest(data, [Signal(1, 1, "a"), Signal(2, 1, "b")],
                          BacktestConfig(0, 0, 0.05, 0.05, 4))
        self.assertEqual(len(result), 1)


if __name__ == "__main__":
    unittest.main()
