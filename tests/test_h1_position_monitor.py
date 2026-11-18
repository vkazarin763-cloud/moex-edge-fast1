import unittest
from decimal import Decimal
from unittest.mock import patch

import h1_position_monitor as hm


class FakeLogger:
    def __init__(self):
        self.messages = []
    def warning(self, *args):
        self.messages.append(args)


class H1PositionMonitorTests(unittest.TestCase):
    def setUp(self):
        self.symbol = "T@MISX"
        self.account = {"positions": [{
            "symbol": self.symbol,
            "quantity": {"value": "10"},
            "average_price": {"value": "100"},
        }]}
        self.candle_safe = {
            "timestamp": "2026-11-18T10:00:00+00:00",
            "open": Decimal("100"), "high": Decimal("102"),
            "low": Decimal("99"), "close": Decimal("101"),
        }
        self.candle_stop = {
            "timestamp": "2026-11-18T11:00:00+00:00",
            "open": Decimal("100"), "high": Decimal("101"),
            "low": Decimal("96"), "close": Decimal("98"),
        }
        self.saved = []
        self.sent = []
        self.logger = FakeLogger()
        self.state = {}
        self.deps = {
            "api_get": lambda *a, **k: {},
            "decimal_value": self.decimal_value,
            "save_state": lambda state: self.saved.append(dict(state)),
            "find_order_by_client_id": lambda *a: "exit-order",
            "wait_for_terminal_order": lambda *a: {
                "status": "ORDER_STATUS_FILLED",
                "executed_quantity": {"value": "10"},
            },
            "get_account_info": lambda *a: ({"positions": []}, Decimal("0")),
            "get_position_quantity": lambda account, symbol: Decimal("0"),
            "place_market_order": self.place_order,
            "send_telegram_message": self.sent.append,
            "logger": self.logger,
        }
        self.orders = []

    @staticmethod
    def decimal_value(value, name):
        if isinstance(value, dict):
            value = value.get("value")
        result = Decimal(str(value))
        if not result.is_finite():
            raise ValueError(name)
        return result

    def place_order(self, token, symbol, quantity, side, client_order_id=None):
        self.orders.append((symbol, quantity, side, client_order_id,
                            self.state[hm.position_key(symbol)]["status"]))
        return {"order_id": "exit-order", "client_order_id": client_order_id}

    def test_initialize_persists_broker_average_entry(self):
        rec = hm.initialize_position_state(
            self.state, self.symbol, "T", "LONG", 10, "100",
            self.deps["save_state"], "2026-11-18T09:30:00+00:00"
        )
        self.assertEqual(rec["entry_price"], "100")
        self.assertEqual(rec["quantity"], 10)
        self.assertIsNone(rec["last_processed_candle"])
        self.assertEqual(rec["status"], "MONITORING")

    def test_legacy_position_is_enrolled_without_replaying_old_history(self):
        with patch.object(hm, "fetch_closed_h1_candles",
                          return_value=[self.candle_safe, self.candle_stop]):
            hm.monitor_open_positions(
                "jwt", self.account, self.state, True, self.deps
            )
        rec = self.state[hm.position_key(self.symbol)]
        self.assertEqual(rec["entry_price"], "100")
        self.assertEqual(rec["last_processed_candle"], self.candle_stop["timestamp"])
        self.assertTrue(rec["baseline_only"])
        self.assertEqual(self.orders, [])

    def test_new_closed_stop_candle_triggers_dry_run_without_order(self):
        hm.initialize_position_state(
            self.state, self.symbol, "T", "LONG", 10, "100",
            self.deps["save_state"], "2026-11-18T10:30:00+00:00"
        )
        rec = self.state[hm.position_key(self.symbol)]
        rec["last_processed_candle"] = self.candle_safe["timestamp"]
        with patch.object(hm, "fetch_closed_h1_candles",
                          return_value=[self.candle_safe, self.candle_stop]):
            hm.monitor_open_positions(
                "jwt", self.account, self.state, True, self.deps
            )
        self.assertEqual(rec["last_dry_run_exit"], "STOP_LOSS")
        self.assertEqual(rec["last_processed_candle"], self.candle_stop["timestamp"])
        self.assertEqual(self.orders, [])

    def test_live_exit_reservation_is_saved_before_market_order(self):
        hm.initialize_position_state(
            self.state, self.symbol, "T", "LONG", 10, "100",
            self.deps["save_state"], "2026-11-18T10:30:00+00:00"
        )
        rec = self.state[hm.position_key(self.symbol)]
        rec["last_processed_candle"] = self.candle_safe["timestamp"]
        with patch.object(hm, "fetch_closed_h1_candles",
                          return_value=[self.candle_safe, self.candle_stop]):
            hm.monitor_open_positions(
                "jwt", self.account, self.state, False, self.deps
            )
        self.assertEqual(len(self.orders), 1)
        self.assertEqual(self.orders[0][1:3], (10, "SIDE_SELL"))
        self.assertEqual(self.orders[0][4], "EXIT_SUBMISSION_ATTEMPTED")
        self.assertEqual(rec["status"], "CLOSED")
        self.assertEqual(rec["exit_reason"], "STOP_LOSS")

    def test_short_position_closes_with_buy_side(self):
        short_account = {"positions": [{
            "symbol": self.symbol,
            "quantity": {"value": "-3"},
            "average_price": {"value": "100"},
        }]}
        hm.initialize_position_state(
            self.state, self.symbol, "T", "SHORT", -3, "100",
            self.deps["save_state"], "2026-11-18T10:30:00+00:00"
        )
        rec = self.state[hm.position_key(self.symbol)]
        rec["last_processed_candle"] = self.candle_safe["timestamp"]
        tp = dict(self.candle_stop, low=Decimal("94"))
        with patch.object(hm, "fetch_closed_h1_candles",
                          return_value=[self.candle_safe, tp]):
            hm.monitor_open_positions(
                "jwt", short_account, self.state, False, self.deps
            )
        self.assertEqual(self.orders[0][2], "SIDE_BUY")
        self.assertEqual(rec["status"], "CLOSED")

    def test_missing_average_price_blocks_monitoring(self):
        bad = {"positions": [{
            "symbol": self.symbol, "quantity": {"value": "10"}
        }]}
        with self.assertRaises(hm.H1MonitorError):
            hm.monitor_open_positions("jwt", bad, self.state, True, self.deps)

    def test_direction_or_average_price_change_fails_closed(self):
        hm.initialize_position_state(
            self.state, self.symbol, "T", "LONG", 10, "100",
            self.deps["save_state"]
        )
        changed = {"positions": [{
            "symbol": self.symbol, "quantity": {"value": "-10"},
            "average_price": {"value": "100"},
        }]}
        with patch.object(hm, "fetch_closed_h1_candles",
                          return_value=[self.candle_safe]):
            with self.assertRaises(hm.H1MonitorError):
                hm.monitor_open_positions("jwt", changed, self.state, True, self.deps)

    def test_ambiguous_exit_is_reconciled_without_second_post(self):
        hm.initialize_position_state(
            self.state, self.symbol, "T", "LONG", 10, "100",
            self.deps["save_state"]
        )
        rec = self.state[hm.position_key(self.symbol)]
        rec.update(status="EXIT_SUBMISSION_ATTEMPTED",
                   exit_client_order_id="persisted-client-id")
        with patch.object(hm, "fetch_closed_h1_candles") as candles:
            hm.monitor_open_positions("jwt", self.account, self.state, False, self.deps)
        self.assertEqual(rec["status"], "CLOSED")
        candles.assert_not_called()
        self.assertEqual(self.orders, [])

    def test_missing_order_during_ambiguous_reconciliation_blocks(self):
        hm.initialize_position_state(
            self.state, self.symbol, "T", "LONG", 10, "100",
            self.deps["save_state"]
        )
        rec = self.state[hm.position_key(self.symbol)]
        rec.update(status="EXIT_SUBMISSION_ATTEMPTED",
                   exit_client_order_id="persisted-client-id")
        self.deps["find_order_by_client_id"] = lambda *a: None
        with self.assertRaises(hm.H1MonitorError):
            hm.monitor_open_positions("jwt", self.account, self.state, False, self.deps)
        self.assertEqual(self.orders, [])

    def test_position_increase_fails_closed(self):
        hm.initialize_position_state(
            self.state, self.symbol, "T", "LONG", 10, "100",
            self.deps["save_state"]
        )
        increased = {"positions": [{
            "symbol": self.symbol, "quantity": {"value": "12"},
            "average_price": {"value": "100"},
        }]}
        with patch.object(hm, "fetch_closed_h1_candles",
                          return_value=[self.candle_safe]):
            with self.assertRaises(hm.H1MonitorError):
                hm.monitor_open_positions("jwt", increased, self.state, True, self.deps)


if __name__ == "__main__":
    unittest.main()
