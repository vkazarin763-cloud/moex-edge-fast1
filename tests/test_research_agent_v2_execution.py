import unittest

from research_agent.v2.execution import ExecutionInputError, evaluate_hypothesis


def bars(count=9):
    closes = [100, 101, 102, 103, 102, 101, 100, 99, 98][:count]
    result = []
    for i, close in enumerate(closes):
        result.append({
            "timestamp": f"2025-02-{i + 1:02d}T10:00:00",
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 1000,
        })
    return result


def rule(feature, op, threshold, direction=None):
    result = {"conditions": [{"feature": feature, "operator": op, "threshold": threshold}]}
    if direction:
        result["direction"] = direction
    return result


class ExecutionEvaluatorTests(unittest.TestCase):
    def test_signal_fills_next_open_and_exit_is_separate(self):
        panel = {"entry": [1, 0, 0, 0, 0, 0, 0, 0, 0],
                 "exit":  [0, 0, 1, 0, 0, 0, 0, 0, 0]}
        result = evaluate_hypothesis(
            bars(), panel, rule("entry", ">=", 1, "LONG"), rule("exit", ">=", 1),
            commission_rate=0, slippage_rate=0,
        )
        self.assertEqual(result["counts"]["closed_trades"], 1)
        trade = result["trades"][0]
        self.assertEqual(trade["signal_timestamp"], bars()[0]["timestamp"])
        self.assertEqual(trade["entry_timestamp"], bars()[1]["timestamp"])
        self.assertEqual(trade["exit_signal_timestamp"], bars()[2]["timestamp"])
        self.assertEqual(trade["exit_timestamp"], bars()[3]["timestamp"])
        self.assertEqual(trade["entry_price"], bars()[1]["open"])
        self.assertEqual(trade["exit_price"], bars()[3]["open"])

    def test_slippage_and_commission_reduce_net_return(self):
        panel = {"entry": [1, 0, 0, 0, 0, 0, 0, 0, 0],
                 "exit":  [0, 0, 1, 0, 0, 0, 0, 0, 0]}
        free = evaluate_hypothesis(
            bars(), panel, rule("entry", ">=", 1, "LONG"), rule("exit", ">=", 1),
            commission_rate=0, slippage_rate=0,
        )
        charged = evaluate_hypothesis(
            bars(), panel, rule("entry", ">=", 1, "LONG"), rule("exit", ">=", 1),
            commission_rate=0.001, slippage_rate=0.001,
        )
        self.assertLess(charged["trades"][0]["net_return"], free["trades"][0]["net_return"])

    def test_unclosed_position_is_separate_and_not_in_metrics(self):
        panel = {"entry": [1, 0, 0, 0, 0, 0, 0, 0, 0],
                 "exit":  [0] * 9}
        result = evaluate_hypothesis(
            bars(), panel, rule("entry", ">=", 1, "SHORT"), rule("exit", ">=", 1),
            commission_rate=0, slippage_rate=0,
        )
        self.assertEqual(result["counts"]["closed_trades"], 0)
        self.assertIsNotNone(result["open_position"])
        self.assertIsNone(result["metrics"]["mean_net_return"])

    def test_last_bar_signal_is_not_filled(self):
        panel = {"entry": [0] * 8 + [1], "exit": [0] * 9}
        result = evaluate_hypothesis(
            bars(), panel, rule("entry", ">=", 1, "LONG"), rule("exit", ">=", 1),
        )
        self.assertEqual(result["counts"]["entry_signals_filled"], 0)
        self.assertEqual(result["counts"]["unfilled_final_bar_signals"], 1)

    def test_rejects_bad_alignment_and_invalid_ohlc(self):
        panel = {"entry": [1] * 8, "exit": [0] * 9}
        with self.assertRaises(ExecutionInputError):
            evaluate_hypothesis(
                bars(), panel, rule("entry", ">=", 1, "LONG"), rule("exit", ">=", 1)
            )
        bad = bars()
        bad[3]["high"] = bad[3]["low"] - 1
        panel = {"entry": [1] * 9, "exit": [0] * 9}
        with self.assertRaises(ExecutionInputError):
            evaluate_hypothesis(
                bad, panel, rule("entry", ">=", 1, "LONG"), rule("exit", ">=", 1)
            )

    def test_requires_direction_and_known_features(self):
        panel = {"entry": [1] * 9, "exit": [0] * 9}
        with self.assertRaises(ExecutionInputError):
            evaluate_hypothesis(bars(), panel, rule("entry", ">=", 1), rule("exit", ">=", 1))
        with self.assertRaises(ExecutionInputError):
            evaluate_hypothesis(
                bars(), panel, rule("missing", ">=", 1, "LONG"), rule("exit", ">=", 1)
            )


if __name__ == "__main__":
    unittest.main()
