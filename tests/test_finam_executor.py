import unittest
from decimal import Decimal
from unittest.mock import patch

import requests
import finam_executor as fe

# Stable dummy account id for URL construction in mocked tests; no API calls occur.
fe.ACCOUNT_ID = "unit-test-account"


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class FinamExecutorTests(unittest.TestCase):

    def test_dry_run_parser_defaults_safe_and_rejects_invalid_values(self):
        self.assertTrue(fe.parse_dry_run("true"))
        self.assertFalse(fe.parse_dry_run("false"))
        with self.assertRaises(RuntimeError):
            fe.parse_dry_run("typo")

    def test_trade_parameters_require_long_permission(self):
        payload = {
            "is_tradable": True,
            "longable": {"value": "AVAILABLE"},
            "shortable": {"value": "NOT_AVAILABLE"},
            "trade_lot_size": "10"
        }
        with patch.object(fe, "api_get", return_value=payload):
            self.assertEqual(fe.get_trade_parameters("jwt", "SBER", "LONG"), 10)

    def test_trade_parameters_reject_unavailable_short_permission(self):
        payload = {
            "is_tradable": True,
            "longable": {"value": "AVAILABLE"},
            "shortable": {"value": "HTB"},
            "trade_lot_size": "10"
        }
        with patch.object(fe, "api_get", return_value=payload):
            with self.assertRaises(ValueError):
                fe.get_trade_parameters("jwt", "SBER", "SHORT")

    def test_quantity_is_one_trading_lot_in_test_mode(self):
        with patch.object(fe, "TEST_MODE_MIN_VOLUME", True):
            self.assertEqual(fe.calculate_order_quantity("SBER", 999, 10), 10)

    def test_fixed_tick_size_rounds_protective_prices_directionally(self):
        asset = {"decimals": 2, "min_step": "5"}
        with patch.object(fe, "api_get", return_value=asset):
            down = fe.round_price_to_tick(
                "jwt", "SBER", Decimal("100.123"), fe.ROUND_FLOOR
            )
            up = fe.round_price_to_tick(
                "jwt", "SBER", Decimal("100.123"), fe.ROUND_CEILING
            )
        self.assertEqual(down, Decimal("100.10"))
        self.assertEqual(up, Decimal("100.15"))

    def test_price_dependent_tick_size_uses_correct_band(self):
        asset = {
            "decimals": 2,
            "min_step": "0",
            "price_step": {
                "step": {"value": "0.01"},
                "threshold_price": {"value": "100"},
                "step_from_threshold": {"value": "0.10"}
            }
        }
        with patch.object(fe, "api_get", return_value=asset):
            rounded = fe.round_price_to_tick(
                "jwt", "SBER", Decimal("100.04"), fe.ROUND_CEILING
            )
        self.assertEqual(rounded, Decimal("100.10"))

    def test_market_order_payload_has_no_account_id_and_has_client_id(self):
        with patch.object(fe, "DRY_RUN", False), \
             patch.object(fe, "api_post", return_value=FakeResponse(
                 200, {"order_id": "ord-1"}
             )) as post:
            result = fe.place_market_order("jwt", "SBER@MISX", 10, "SIDE_BUY")

        payload = post.call_args.args[2]
        self.assertNotIn("account_id", payload)
        self.assertLessEqual(len(payload["client_order_id"]), 20)
        self.assertEqual(result["order_id"], "ord-1")

    def test_server_error_reconciles_without_resubmitting(self):
        with patch.object(fe, "DRY_RUN", False), \
             patch.object(fe, "api_post", return_value=FakeResponse(502, text="gateway")) as post, \
             patch.object(fe, "find_order_by_client_id", return_value="ord-reconciled"):
            result = fe.place_market_order("jwt", "SBER@MISX", 10, "SIDE_BUY")
        self.assertEqual(result["order_id"], "ord-reconciled")
        self.assertEqual(post.call_count, 1)

    def test_timeout_is_unknown_and_never_retried(self):
        with patch.object(fe, "DRY_RUN", False), \
             patch.object(fe, "api_post", side_effect=requests.Timeout("lost")) as post, \
             patch.object(fe, "find_order_by_client_id", return_value=None):
            with self.assertRaises(fe.OrderSubmissionUnknown):
                fe.place_market_order("jwt", "SBER@MISX", 10, "SIDE_BUY")
        self.assertEqual(post.call_count, 1)

    def test_partial_fill_is_not_terminal(self):
        partial = {"status": "ORDER_STATUS_PARTIALLY_FILLED",
                   "executed_quantity": {"value": "5"},
                   "remaining_quantity": {"value": "5"}}
        filled = {"status": "ORDER_STATUS_FILLED",
                  "executed_quantity": {"value": "10"},
                  "remaining_quantity": {"value": "0"}}
        with patch.object(fe, "get_order_state", side_effect=[partial, filled]) as get_state, \
             patch.object(fe, "cancel_order_remainder") as cancel, \
             patch.object(fe.time, "sleep"):
            state = fe.wait_for_terminal_order("jwt", "ord-1", timeout_seconds=5)
        self.assertEqual(state["status"], "ORDER_STATUS_FILLED")
        self.assertEqual(get_state.call_count, 2)
        cancel.assert_not_called()

    def test_cancel_timeout_rechecks_terminal_order_state(self):
        partial = {"status": "ORDER_STATUS_PARTIALLY_FILLED",
                   "executed_quantity": {"value": "5"},
                   "remaining_quantity": {"value": "5"}}
        canceled = {"status": "ORDER_STATUS_CANCELED",
                    "executed_quantity": {"value": "5"},
                    "remaining_quantity": {"value": "0"}}
        with patch.object(fe, "get_order_state", side_effect=[partial, canceled]), \
             patch.object(fe, "cancel_order_remainder",
                          side_effect=requests.Timeout("cancel response lost")), \
             patch.object(fe.time, "sleep"), \
             patch.object(fe.time, "monotonic", side_effect=[0, 0, 1]):
            state = fe.wait_for_terminal_order("jwt", "ord-race", timeout_seconds=0.01)
        self.assertEqual(state["status"], "ORDER_STATUS_CANCELED")

    def test_reconcile_client_order_id_nested_in_order(self):
        payload = {"orders": [
            {"order_id": "other", "order": {"client_order_id": "different"}},
            {"order_id": "wanted", "order": {"client_order_id": "client-123"}}
        ]}
        with patch.object(fe, "api_get", return_value=payload):
            self.assertEqual(
                fe.find_order_by_client_id("jwt", "client-123"), "wanted"
            )

    def test_weighted_average_fill_price(self):
        trades = {"trades": [
            {"order_id": "ord-2", "size": {"value": "4"},
             "price": {"value": "100"}},
            {"order_id": "ord-2", "size": {"value": "6"},
             "price": {"value": "110"}},
            {"order_id": "other", "size": {"value": "100"},
             "price": {"value": "1"}}
        ]}
        with patch.object(fe, "api_get", return_value=trades):
            qty, avg = fe.get_weighted_average_fill(
                "jwt", "ord-2", fe.datetime.utcnow(), Decimal("10")
            )
        self.assertEqual(qty, Decimal("10"))
        self.assertEqual(avg, Decimal("106"))

    def test_sltp_payload_uses_executed_quantity_and_no_account_id(self):
        accepted = {
            "order_id": "sltp-1",
            "status": "ORDER_STATUS_NEW",
            "sltp_order": {
                "quantity_sl": {"value": "7"},
                "quantity_tp": {"value": "7"},
                "sl_price": {"value": "97.0"},
                "tp_price": {"value": "105.0"}
            }
        }
        with patch.object(fe, "DRY_RUN", False), \
             patch.object(fe, "api_post", return_value=FakeResponse(200, accepted)) as post:
            ok = fe.place_sltp_order(
                "jwt", "SBER@MISX", 7, "LONG", 97.0, 105.0
            )
        payload = post.call_args.args[2]
        self.assertTrue(ok)
        self.assertNotIn("account_id", payload)
        self.assertEqual(payload["quantity_sl"]["value"], "7")
        self.assertEqual(payload["quantity_tp"]["value"], "7")
        self.assertEqual(payload["side"], "SIDE_SELL")

    def test_sltp_http_200_without_order_confirmation_is_not_success(self):
        with patch.object(fe, "DRY_RUN", False), \
             patch.object(fe, "api_post", return_value=FakeResponse(200, {})):
            with self.assertRaises(fe.OrderProtectionError):
                fe.place_sltp_order(
                    "jwt", "SBER@MISX", 7, "LONG", 97.0, 105.0
                )

    def test_sltp_http_200_with_rejected_status_is_not_success(self):
        rejected = {
            "order_id": "sltp-rejected",
            "status": "ORDER_STATUS_REJECTED",
            "sltp_order": {
                "quantity_sl": {"value": "7"},
                "quantity_tp": {"value": "7"},
                "sl_price": {"value": "97.0"},
                "tp_price": {"value": "105.0"}
            }
        }
        with patch.object(fe, "DRY_RUN", False), \
             patch.object(fe, "api_post", return_value=FakeResponse(200, rejected)):
            with self.assertRaises(fe.OrderProtectionError):
                fe.place_sltp_order(
                    "jwt", "SBER@MISX", 7, "LONG", 97.0, 105.0
                )


if __name__ == "__main__":
    unittest.main()
