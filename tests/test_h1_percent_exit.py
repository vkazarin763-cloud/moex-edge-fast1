import unittest
from decimal import Decimal

from h1_percent_exit import calculate_exit_levels, evaluate_closed_h1_candle


class H1PercentExitTests(unittest.TestCase):
    def test_long_levels(self):
        stop, target = calculate_exit_levels("100", "LONG")
        self.assertEqual(stop, Decimal("97.000"))
        self.assertEqual(target, Decimal("105.000"))

    def test_short_levels(self):
        stop, target = calculate_exit_levels("100", "SHORT")
        self.assertEqual(stop, Decimal("103.000"))
        self.assertEqual(target, Decimal("95.000"))

    def test_long_stop(self):
        candle = {"open": 100, "high": 101, "low": 96, "close": 99}
        self.assertEqual(evaluate_closed_h1_candle(100, "LONG", candle), "STOP_LOSS")

    def test_long_target(self):
        candle = {"open": 100, "high": 106, "low": 99, "close": 104}
        self.assertEqual(evaluate_closed_h1_candle(100, "LONG", candle), "TAKE_PROFIT")

    def test_short_stop_and_target(self):
        stop_candle = {"open": 100, "high": 104, "low": 99, "close": 102}
        target_candle = {"open": 100, "high": 101, "low": 94, "close": 96}
        self.assertEqual(evaluate_closed_h1_candle(100, "SHORT", stop_candle), "STOP_LOSS")
        self.assertEqual(evaluate_closed_h1_candle(100, "SHORT", target_candle), "TAKE_PROFIT")

    def test_stop_has_priority_if_both_hit(self):
        candle = {"open": 100, "high": 106, "low": 96, "close": 101}
        self.assertEqual(evaluate_closed_h1_candle(100, "LONG", candle), "STOP_LOSS")

    def test_no_trigger(self):
        candle = {"open": 100, "high": 103, "low": 98, "close": 101}
        self.assertIsNone(evaluate_closed_h1_candle(100, "LONG", candle))

    def test_invalid_ohlc_rejected(self):
        candle = {"open": 100, "high": 99, "low": 98, "close": 100}
        with self.assertRaises(ValueError):
            evaluate_closed_h1_candle(100, "LONG", candle)


if __name__ == "__main__":
    unittest.main()
