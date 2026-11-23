import unittest

from research_agent.moex_equities_donchian_replay import (
    adjust_candle,
    _simulate_symbol,
    _trade_metrics,
    _validate_rows,
)


class DonchianReplayTests(unittest.TestCase):
    def test_split_adjustment_changes_only_pre_action_bars(self):
        before = {
            "timestamp": "2024-02-20T00:00:00",
            "open": 100.0, "high": 110.0, "low": 90.0, "close": 100.0,
            "volume": 1000.0,
        }
        adjusted = adjust_candle("TRNFP", before)
        self.assertEqual(adjusted["open"], 1.0)
        self.assertEqual(adjusted["high"], 1.1)
        self.assertEqual(adjusted["low"], 0.9)
        self.assertEqual(adjusted["volume"], 100000.0)
        self.assertEqual(before["open"], 100.0)

        after = dict(before, timestamp="2024-02-21T00:00:00")
        self.assertEqual(adjust_candle("TRNFP", after)["open"], 100.0)

    def test_vtbr_consolidation_uses_inverse_split_factor(self):
        candle = {
            "timestamp": "2024-07-08T00:00:00",
            "open": 0.02, "high": 0.021, "low": 0.019, "close": 0.02,
            "volume": 5000.0,
        }
        adjusted = adjust_candle("VTBR", candle)
        self.assertEqual(adjusted["open"], 100.0)
        self.assertEqual(adjusted["volume"], 1.0)

    def test_donchian_orders_fill_at_next_open_not_signal_close(self):
        rows = []
        for i in range(20):
            rows.append({
                "timestamp": f"2024-01-{i + 1:02d}T00:00:00",
                "open": 9.0, "high": 10.0, "low": 8.0, "close": 9.0,
            })
        rows.extend([
            {"timestamp": "2024-01-21T00:00:00", "open": 9.0, "high": 11.0, "low": 8.0, "close": 11.0},
            {"timestamp": "2024-01-22T00:00:00", "open": 12.0, "high": 12.0, "low": 7.0, "close": 7.5},
            {"timestamp": "2024-01-23T00:00:00", "open": 11.0, "high": 11.0, "low": 10.0, "close": 10.5},
        ])
        trades, open_position = _simulate_symbol("TEST", rows)
        self.assertEqual(len(trades), 1)
        self.assertIsNone(open_position)
        self.assertEqual(trades[0]["entry"], 12.0)
        self.assertEqual(trades[0]["exit"], 11.0)
        self.assertEqual(trades[0]["entry_date"], "2024-01-22")
        self.assertEqual(trades[0]["exit_date"], "2024-01-23")

    def test_source_order_validation_detects_non_monotonic_rows(self):
        rows = [
            {"timestamp": "2024-01-02T00:00:00", "open": 10, "high": 11, "low": 9, "close": 10},
            {"timestamp": "2024-01-01T00:00:00", "open": 10, "high": 11, "low": 9, "close": 10},
        ]
        result = _validate_rows("TEST", rows)
        self.assertEqual(result["non_monotonic"], 1)

    def test_cost_scenario_is_applied_on_both_sides(self):
        trade = {"entry": 100.0, "exit": 110.0, "holding_bars": 5}
        result = _trade_metrics([trade], 8.0)
        expected = (110.0 * 0.9992) / (100.0 * 1.0008) - 1.0
        self.assertAlmostEqual(result["average_net_trade_return"], expected)
        self.assertEqual(result["closed_trades"], 1)


if __name__ == "__main__":
    unittest.main()
