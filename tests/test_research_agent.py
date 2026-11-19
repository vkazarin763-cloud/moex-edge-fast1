import unittest
from datetime import datetime, timedelta, timezone

from research_agent.core import (
    Candle, Signal, BacktestConfig, validate_candles, backtest, summarize, generate_signals, _wilder_rsi,
)


def bars(prices):
    start = datetime(2025, 1, 1)
    result = []
    for i, price in enumerate(prices):
        result.append(Candle(start + timedelta(hours=i), price, price * 1.02,
                             price * 0.98, price, 1000))
    return result


class ValidationTests(unittest.TestCase):
    def test_flat_series_rsi_is_neutral(self):
        self.assertEqual(_wilder_rsi([100.0] * 20)[14], 50.0)

    def test_fixed_candidate_generator_uses_known_strategy_set(self):
        data = []
        start = datetime(2025, 1, 1)
        for i in range(180):
            price = 100 + i * 0.04 + (5 if (i // 12) % 2 else -5)
            data.append(Candle(start + timedelta(hours=i), price, price + 1,
                               price - 1, price, 1000))
        signals = generate_signals(data)
        allowed = {"Donchian20", "EMA20x50", "RSI14Trend50",
                   "MACD12x26", "Keltner20x2ATR"}
        self.assertTrue(all(signal.strategy in allowed for signal in signals))
        self.assertTrue(all(0 <= signal.index < len(data) - 1 for signal in signals))

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

    def test_mixed_naive_and_aware_timestamps_rejected(self):
        data = bars([100, 101])
        data[1] = Candle(data[1].timestamp.replace(tzinfo=timezone.utc),
                         data[1].open, data[1].high, data[1].low,
                         data[1].close, data[1].volume)
        with self.assertRaisesRegex(ValueError, "Mixed timezone"):
            validate_candles(data)


class BacktestTests(unittest.TestCase):
    def test_signal_enters_next_bar_open(self):
        data = bars([100, 100, 100, 100, 100, 100])
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

    def test_long_stop_gap_fills_at_open_not_stop(self):
        data = bars([100, 100, 100, 100])
        data[3] = Candle(data[3].timestamp, 90, 92, 89, 91, 1000)
        result = backtest(data, [Signal(1, 1, "test")],
                          BacktestConfig(0, 0, 0.05, 0.10, 3))
        self.assertEqual(result[0].exit_reason, "STOP_GAP")
        self.assertEqual(result[0].exit_price, 90)

    def test_short_stop_gap_fills_at_open_not_stop(self):
        data = bars([100, 100, 100, 100])
        data[3] = Candle(data[3].timestamp, 110, 112, 108, 111, 1000)
        result = backtest(data, [Signal(1, -1, "test")],
                          BacktestConfig(0, 0, 0.05, 0.10, 3))
        self.assertEqual(result[0].exit_reason, "STOP_GAP")
        self.assertEqual(result[0].exit_price, 110)

    def test_target_gap_fills_at_target_limit(self):
        data = bars([100, 100, 100, 100])
        data[3] = Candle(data[3].timestamp, 110, 112, 108, 111, 1000)
        result = backtest(data, [Signal(1, 1, "test")],
                          BacktestConfig(0, 0, 0.05, 0.05, 3))
        self.assertEqual(result[0].exit_reason, "TARGET_GAP")
        self.assertAlmostEqual(result[0].exit_price, 105)

    def test_max_bars_exit_uses_close_of_last_allowed_bar(self):
        data = bars([100, 100, 100, 103, 104, 105])
        result = backtest(data, [Signal(1, 1, "test")],
                          BacktestConfig(0, 0, None, None, 2))
        self.assertEqual(result[0].exit_reason, "TIME")
        self.assertEqual(result[0].exit_time, data[3].timestamp)
        self.assertEqual(result[0].exit_price, data[3].close)

    def test_max_bars_exit_on_final_dataset_bar_is_closed(self):
        data = bars([100, 100, 100, 103])
        result = backtest(data, [Signal(1, 1, "test")],
                          BacktestConfig(0, 0, None, None, 2))
        self.assertEqual(result[0].status, "CLOSED")
        self.assertEqual(result[0].exit_reason, "TIME")
        self.assertEqual(result[0].exit_time, data[-1].timestamp)
        self.assertEqual(result[0].exit_price, data[-1].close)

    def test_open_terminal_trade_not_counted_as_closed(self):
        data = bars([100, 100, 100, 100])
        result = backtest(data, [Signal(1, 1, "test")],
                          BacktestConfig(0, 0, None, None, None))
        stats = summarize(result)
        self.assertEqual(stats["closed_trades"], 0)
        self.assertEqual(stats["open_terminal_trades_excluded"], 1)
        self.assertIsNone(stats["average_net_return"])

    def test_summary_is_json_safe_when_there_are_no_losses(self):
        data = bars([100, 100, 100, 110])
        result = backtest(data, [Signal(1, 1, "test")],
                          BacktestConfig(0, 0, 0.05, 0.05, 3))
        stats = summarize(result)
        self.assertIsNone(stats["profit_factor"])
        self.assertTrue(stats["profit_factor_infinite"])

    def test_two_sided_costs(self):
        data = bars([100, 100, 100, 110])
        result = backtest(data, [Signal(1, 1, "test")],
                          BacktestConfig(0.001, 0.0005, 0.05, 0.05, 3))
        entry_fill = 100 * (1 + 0.0005)
        target_price = entry_fill * (1 + 0.05)
        exit_fill = target_price * (1 - 0.0005)
        expected = (exit_fill - entry_fill) / entry_fill - 0.001 * (entry_fill + exit_fill) / entry_fill
        self.assertAlmostEqual(result[0].net_return, expected)
        self.assertAlmostEqual(result[0].entry_price, entry_fill)
        self.assertAlmostEqual(result[0].exit_price, exit_fill)

    def test_overlapping_signals_are_skipped(self):
        data = bars([100] * 8)
        data[3] = Candle(data[3].timestamp, 100, 106, 99, 105, 1000)
        result = backtest(data, [Signal(1, 1, "same"), Signal(2, 1, "same")],
                          BacktestConfig(0, 0, 0.05, 0.05, 4))
        self.assertEqual(len(result), 1)


if __name__ == "__main__":
    unittest.main()
