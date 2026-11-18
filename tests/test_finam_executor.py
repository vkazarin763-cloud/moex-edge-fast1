import unittest
import base64
import json
from decimal import Decimal
from unittest.mock import patch

import requests
import tempfile
import os
import finam_executor as fe
import finam_readonly_audit as fra

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

    def test_live_mode_requires_separate_explicit_gate(self):
        fe.enforce_live_trading_gate(True, "false")
        with self.assertRaises(RuntimeError):
            fe.enforce_live_trading_gate(False, "false")
        with self.assertRaises(RuntimeError):
            fe.enforce_live_trading_gate(False, "")
        fe.enforce_live_trading_gate(False, "true")

    def test_live_order_limit_is_one_per_invocation(self):
        self.assertTrue(fe.can_submit_live_order(0))
        self.assertFalse(fe.can_submit_live_order(1))
        self.assertFalse(fe.can_submit_live_order(2))
        self.assertEqual(fe.MAX_NEW_ORDERS_PER_RUN, 1)

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

    def test_signal_fingerprint_is_stable_and_distinguishes_strategy_date(self):
        row = {
            "ticker": "sber", "direction": "long", "strategy": "breakout",
            "date": "2026-11-17", "entry_price": "100.00"
        }
        self.assertEqual(fe.signal_fingerprint(row), fe.signal_fingerprint(dict(row)))
        changed = dict(row, date="2026-11-18")
        self.assertNotEqual(fe.signal_fingerprint(row), fe.signal_fingerprint(changed))

    def test_signal_fingerprint_requires_strategy_and_date(self):
        with self.assertRaises(ValueError):
            fe.signal_fingerprint({
                "ticker": "SBER", "direction": "LONG", "entry_price": 100
            })

    def test_reserve_signal_prevents_duplicate(self):
        state = {}
        with patch.object(fe, "DRY_RUN", False), \
             patch.object(fe, "save_signal_state") as save:
            self.assertTrue(fe.reserve_signal(state, "abc", "SBER", "LONG"))
            self.assertFalse(fe.reserve_signal(state, "abc", "SBER", "LONG"))
        self.assertEqual(state["abc"]["status"], "SUBMISSION_ATTEMPTED")
        save.assert_called_once()

    def test_update_signal_state_persists_terminal_status(self):
        state = {"abc": {"ticker": "SBER"}}
        with patch.object(fe, "DRY_RUN", False), \
             patch.object(fe, "save_signal_state") as save:
            fe.update_signal_state(state, "abc", "EXECUTED_AND_PROTECTED",
                                   order_id="123")
        self.assertEqual(state["abc"]["status"], "EXECUTED_AND_PROTECTED")
        self.assertEqual(state["abc"]["order_id"], "123")
        save.assert_called_once()

    def test_signal_journal_branch_override_takes_precedence(self):
        with patch.dict(os.environ, {
            "FINAM_STATE_BRANCH": "feature/test-branch",
            "GITHUB_REF_NAME": "8/merge"
        }):
            branch = os.getenv("FINAM_STATE_BRANCH") or os.getenv("GITHUB_REF_NAME", "main")
        self.assertEqual(branch, "feature/test-branch")

    def test_live_signal_state_fails_closed_without_github_token(self):
        with patch.object(fe, "DRY_RUN", False), \
             patch.dict(os.environ, {"GITHUB_TOKEN": "", "GITHUB_REPOSITORY": ""}):
            with self.assertRaises(RuntimeError):
                fe.load_signal_state()

    def test_zero_quantity_position_records_do_not_block_new_signals(self):
        account = {"positions": [
            {"symbol": "SBER@MISX", "quantity": {"value": "0"}},
            {"symbol": "GAZP@MISX", "quantity": {"value": "10"}},
            {"symbol": "LKOH@MISX", "quantity": {"value": "-2.5"}}
        ]}
        self.assertEqual(
            fe.get_open_position_symbols(account), {"GAZP", "LKOH"}
        )

    def test_empty_positions_return_empty_symbol_set(self):
        self.assertEqual(fe.get_open_position_symbols({"positions": []}), set())

    def test_position_without_quantity_fails_closed(self):
        account = {"positions": [{"symbol": "SBER@MISX"}]}
        with self.assertRaises(fe.OrderProtectionError):
            fe.get_open_position_symbols(account)

    def test_malformed_positions_response_fails_closed(self):
        with self.assertRaises(RuntimeError):
            fe.get_open_position_symbols({"positions": None})

    def test_position_limit_blocks_eleventh_new_position(self):
        open_symbols = {f"T{i}" for i in range(10)}
        self.assertEqual(fe.MAX_OPEN_POSITIONS, 10)
        self.assertTrue(fe.position_limit_reached(open_symbols, "SBER"))

    def test_position_limit_allows_new_position_below_cap(self):
        open_symbols = {f"T{i}" for i in range(9)}
        self.assertFalse(fe.position_limit_reached(open_symbols, "SBER"))

    def test_active_orders_reserve_position_slots(self):
        payload = {"orders": [
            {
                "status": "ORDER_STATUS_NEW",
                "order": {"symbol": "SBER@MISX"}
            },
            {
                "status": "ORDER_STATUS_PARTIALLY_FILLED",
                "order": {"symbol": "GAZP@MISX"}
            },
            {
                "status": "ORDER_STATUS_FILLED",
                "order": {"symbol": "LKOH@MISX"}
            },
            {
                "status": "ORDER_STATUS_NEW",
                "sltp_order": {"symbol": "SBER@MISX"}
            }
        ]}
        with patch.object(fe, "api_get", return_value=payload):
            self.assertEqual(
                fe.get_active_order_symbols("jwt"), {"SBER", "GAZP"}
            )

    def test_unknown_order_status_reserves_slot(self):
        payload = {"orders": [
            {"status": "ORDER_STATUS_UNSPECIFIED",
             "order": {"symbol": "NVTK@MISX"}}
        ]}
        with patch.object(fe, "api_get", return_value=payload):
            self.assertEqual(fe.get_active_order_symbols("jwt"), {"NVTK"})

    def test_find_sltp_order_by_client_id_nested(self):
        payload = {"orders": [
            {"order_id": "sltp-wanted",
             "sltp_order": {"client_order_id": "sltp-client-123"}}
        ]}
        with patch.object(fe, "api_get", return_value=payload):
            self.assertEqual(
                fe.find_order_by_client_id("jwt", "sltp-client-123"),
                "sltp-wanted"
            )

    def test_active_order_without_symbol_fails_closed(self):
        payload = {"orders": [
            {"status": "ORDER_STATUS_NEW", "order": {"client_order_id": "x"}}
        ]}
        with patch.object(fe, "api_get", return_value=payload):
            with self.assertRaises(RuntimeError):
                fe.get_active_order_symbols("jwt")

    def test_invalid_active_orders_response_fails_closed(self):
        with patch.object(fe, "api_get", return_value={"orders": None}):
            with self.assertRaises(RuntimeError):
                fe.get_active_order_symbols("jwt")

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

    def test_missing_tick_metadata_raises_protection_error(self):
        with patch.object(fe, "api_get", return_value={
            "decimals": 2, "min_step": "0"
        }):
            with self.assertRaises(fe.OrderProtectionError):
                fe.round_price_to_tick(
                    "jwt", "SBER", Decimal("100.04"), fe.ROUND_CEILING
                )

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

    def test_weighted_average_retries_until_trade_history_is_visible(self):
        empty = {"trades": []}
        complete = {"trades": [
            {"order_id": "ord-lag", "size": {"value": "3"},
             "price": {"value": "100"}},
            {"order_id": "ord-lag", "size": {"value": "2"},
             "price": {"value": "110"}}
        ]}
        with patch.object(fe, "api_get", side_effect=[empty, complete]) as get_trades, \
             patch.object(fe.time, "sleep"):
            qty, avg = fe.get_weighted_average_fill(
                "jwt", "ord-lag", fe.datetime.utcnow(), Decimal("5")
            )
        self.assertEqual(get_trades.call_count, 2)
        self.assertEqual(qty, Decimal("5"))
        self.assertEqual(avg, Decimal("104"))

    def test_weighted_average_fails_closed_if_history_never_matches(self):
        partial = {"trades": [
            {"order_id": "ord-partial", "size": {"value": "3"},
             "price": {"value": "100"}}
        ]}
        with patch.object(fe, "TRADE_RECONCILE_ATTEMPTS", 2), \
             patch.object(fe, "api_get", return_value=partial), \
             patch.object(fe.time, "sleep"):
            with self.assertRaises(fe.OrderProtectionError):
                fe.get_weighted_average_fill(
                    "jwt", "ord-partial", fe.datetime.utcnow(), Decimal("5")
                )

    def test_sltp_payload_uses_executed_quantity_and_no_account_id(self):
        accepted = {
            "order_id": "sltp-1",
            "status": "ORDER_STATUS_NEW",
            "sltp_order": {
                "symbol": "SBER@MISX",
                "side": "SIDE_BUY",
                "quantity_sl": {"value": "7"},
                "quantity_tp": {"value": "7"},
                "sl_price": {"value": "97.0"},
                "tp_price": {"value": "105.0"}
            }
        }
        readback = {
            "order_id": "sltp-1",
            "status": "ORDER_STATUS_NEW",
            "sltp_order": accepted["sltp_order"]
        }
        with patch.object(fe, "DRY_RUN", False), \
             patch.object(fe, "api_post", return_value=FakeResponse(200, accepted)) as post, \
             patch.object(fe, "get_order_state", return_value=readback) as get_state:
            ok = fe.place_sltp_order(
                "jwt", "SBER@MISX", 7, "LONG", 97.0, 105.0
            )
        get_state.assert_called_once_with("jwt", "sltp-1")
        payload = post.call_args.args[2]
        self.assertTrue(ok)
        self.assertNotIn("account_id", payload)
        self.assertLessEqual(len(payload["client_order_id"]), 20)
        self.assertEqual(payload["sl_qty_measure"], "SLTP_QTY_MEASURE_VALUE")
        self.assertEqual(payload["tp_qty_measure"], "SLTP_QTY_MEASURE_VALUE")
        self.assertEqual(payload["quantity_sl"]["value"], "7")
        self.assertEqual(payload["quantity_tp"]["value"], "7")
        self.assertEqual(payload["side"], "SIDE_BUY")

    def test_sltp_timeout_reconciles_by_client_id_without_resubmitting(self):
        readback = {
            "order_id": "sltp-timeout",
            "status": "ORDER_STATUS_NEW",
            "sltp_order": {
                "symbol": "SBER@MISX",
                "side": "SIDE_BUY",
                "quantity_sl": {"value": "7"},
                "quantity_tp": {"value": "7"},
                "sl_price": {"value": "97.0"},
                "tp_price": {"value": "105.0"}
            }
        }
        with patch.object(fe, "DRY_RUN", False), \
             patch.object(fe, "api_post",
                          side_effect=requests.Timeout("lost response")) as post, \
             patch.object(fe, "find_order_by_client_id",
                          return_value="sltp-timeout") as find_order, \
             patch.object(fe, "get_order_state", return_value=readback):
            ok = fe.place_sltp_order(
                "jwt", "SBER@MISX", 7, "LONG", 97.0, 105.0
            )
        payload = post.call_args.args[2]
        self.assertTrue(ok)
        self.assertEqual(post.call_count, 1)
        find_order.assert_called_once_with("jwt", payload["client_order_id"])

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

    def test_sltp_rejected_on_readback_is_not_success(self):
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
        rejected_readback = {
            "order_id": "sltp-1",
            "status": "ORDER_STATUS_REJECTED",
            "sltp_order": accepted["sltp_order"]
        }
        with patch.object(fe, "DRY_RUN", False), \
             patch.object(fe, "api_post", return_value=FakeResponse(200, accepted)), \
             patch.object(fe, "get_order_state", return_value=rejected_readback):
            with self.assertRaises(fe.OrderProtectionError):
                fe.place_sltp_order(
                    "jwt", "SBER@MISX", 7, "LONG", 97.0, 105.0
                )

    def test_sltp_requires_readback_with_echoed_parameters(self):
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
        incomplete_readback = {
            "order_id": "sltp-1",
            "status": "ORDER_STATUS_NEW"
        }
        with patch.object(fe, "DRY_RUN", False), \
             patch.object(fe, "api_post", return_value=FakeResponse(200, accepted)), \
             patch.object(fe, "get_order_state", return_value=incomplete_readback):
            with self.assertRaises(fe.OrderProtectionError):
                fe.place_sltp_order(
                    "jwt", "SBER@MISX", 7, "LONG", 97.0, 105.0
                )

    def test_sltp_long_uses_protected_position_side_buy(self):
        readback = {
            "order_id": "sltp-long",
            "status": "ORDER_STATUS_NEW",
            "sltp_order": {
                "symbol": "SBER@MISX",
                "side": "SIDE_BUY",
                "quantity_sl": {"value": "7"},
                "quantity_tp": {"value": "7"},
                "sl_price": {"value": "97.0"},
                "tp_price": {"value": "105.0"}
            }
        }
        with patch.object(fe, "DRY_RUN", False), \
             patch.object(fe, "api_post", return_value=FakeResponse(200, readback)) as post, \
             patch.object(fe, "get_order_state", return_value=readback):
            self.assertTrue(
                fe.place_sltp_order("jwt", "SBER@MISX", 7, "LONG", 97.0, 105.0)
            )
        self.assertEqual(post.call_args.args[2]["side"], "SIDE_BUY")

    def test_sltp_short_uses_protected_position_side_sell(self):
        readback = {
            "order_id": "sltp-short",
            "status": "ORDER_STATUS_NEW",
            "sltp_order": {
                "symbol": "SBER@MISX",
                "side": "SIDE_SELL",
                "quantity_sl": {"value": "7"},
                "quantity_tp": {"value": "7"},
                "sl_price": {"value": "103.0"},
                "tp_price": {"value": "95.0"}
            }
        }
        with patch.object(fe, "DRY_RUN", False), \
             patch.object(fe, "api_post", return_value=FakeResponse(200, readback)) as post, \
             patch.object(fe, "get_order_state", return_value=readback):
            self.assertTrue(
                fe.place_sltp_order("jwt", "SBER@MISX", 7, "SHORT", 103.0, 95.0)
            )
        self.assertEqual(post.call_args.args[2]["side"], "SIDE_SELL")

    def test_sltp_wrong_readback_side_is_rejected(self):
        accepted = {
            "order_id": "sltp-1",
            "status": "ORDER_STATUS_NEW",
            "sltp_order": {
                "symbol": "SBER@MISX",
                "side": "SIDE_BUY",
                "quantity_sl": {"value": "7"},
                "quantity_tp": {"value": "7"},
                "sl_price": {"value": "97.0"},
                "tp_price": {"value": "105.0"}
            }
        }
        wrong_side = {
            "order_id": "sltp-1",
            "status": "ORDER_STATUS_NEW",
            "sltp_order": dict(accepted["sltp_order"], side="SIDE_SELL")
        }
        with patch.object(fe, "DRY_RUN", False), \
             patch.object(fe, "api_post", return_value=FakeResponse(200, accepted)), \
             patch.object(fe, "get_order_state", return_value=wrong_side):
            with self.assertRaises(fe.OrderProtectionError):
                fe.place_sltp_order(
                    "jwt", "SBER@MISX", 7, "LONG", 97.0, 105.0
                )


    def test_live_signal_state_reads_github_contents(self):
        encoded = base64.b64encode(b'{"abc": {"status": "SUBMISSION_ATTEMPTED"}}').decode("ascii")
        response = FakeResponse(200, {"content": encoded, "sha": "blob-sha"})
        env = {
            "GITHUB_TOKEN": "masked-test-token",
            "GITHUB_REPOSITORY": "owner/repo",
            "FINAM_STATE_BRANCH": "main"
        }
        with patch.object(fe, "DRY_RUN", False), \
             patch.dict(os.environ, env), \
             patch.object(fe.requests, "get", return_value=response) as get:
            state = fe.load_signal_state()
        self.assertEqual(state["abc"]["status"], "SUBMISSION_ATTEMPTED")
        self.assertEqual(get.call_args.kwargs["params"], {"ref": "main"})

    def test_live_signal_state_writes_contents_with_current_sha(self):
        current = FakeResponse(200, {"sha": "current-blob-sha"})
        saved = FakeResponse(200, {"content": {"sha": "new-blob-sha"}})
        env = {
            "GITHUB_TOKEN": "masked-test-token",
            "GITHUB_REPOSITORY": "owner/repo",
            "FINAM_STATE_BRANCH": "main"
        }
        state = {"abc": {"status": "SUBMISSION_ATTEMPTED"}}
        with patch.object(fe, "DRY_RUN", False), \
             patch.dict(os.environ, env), \
             patch.object(fe.requests, "get", return_value=current), \
             patch.object(fe.requests, "put", return_value=saved) as put:
            fe.save_signal_state(state)
        payload = put.call_args.kwargs["json"]
        self.assertEqual(payload["sha"], "current-blob-sha")
        self.assertEqual(payload["branch"], "main")
        written = json.loads(base64.b64decode(payload["content"]).decode("utf-8"))
        self.assertEqual(written, state)



class FinamReadOnlyAuditTests(unittest.TestCase):
    def test_t_position_absent_means_zero_only_with_valid_positions_array(self):
        self.assertEqual(
            fra.parse_position_quantity({"positions": []}, "T@MISX"),
            Decimal("0")
        )

    def test_t_position_quantity_is_read_from_broker_payload(self):
        account = {
            "positions": [
                {"symbol": "SBER@MISX", "quantity": {"value": "2"}},
                {"symbol": "T@MISX", "quantity": {"value": "1"}}
            ]
        }
        self.assertEqual(
            fra.parse_position_quantity(account, "T@MISX"),
            Decimal("1")
        )

    def test_malformed_positions_fail_closed(self):
        with self.assertRaises(fra.AuditError):
            fra.parse_position_quantity({}, "T@MISX")
        with self.assertRaises(fra.AuditError):
            fra.parse_position_quantity({"positions": [{"quantity": "1"}]}, "T@MISX")

    def test_no_active_t_orders(self):
        self.assertEqual(
            fra.count_active_orders_for_symbol(
                {"orders": [{"symbol": "SBER@MISX"}]}, "T@MISX"
            ),
            0
        )

    def test_active_t_order_is_counted(self):
        self.assertEqual(
            fra.count_active_orders_for_symbol(
                {"orders": [
                    {"symbol": "T@MISX", "status": "ORDER_STATUS_NEW"},
                    {"symbol": "SBER@MISX", "status": "ORDER_STATUS_NEW"}
                ]},
                "T@MISX"
            ),
            1
        )

    def test_nested_order_symbol_is_counted(self):
        self.assertEqual(
            fra.count_active_orders_for_symbol(
                {"orders": [
                    {"status": "ORDER_STATUS_NEW",
                     "order": {"symbol": "T@MISX"}},
                    {"status": "ORDER_STATUS_NEW",
                     "order": {"symbol": "SBER@MISX"}}
                ]},
                "T@MISX"
            ),
            1
        )

    def test_nested_sltp_order_symbol_is_counted(self):
        self.assertEqual(
            fra.count_active_orders_for_symbol(
                {"orders": [
                    {"status": "ORDER_STATUS_NEW",
                     "sltp_order": {"symbol": "T@MISX"}},
                    {"status": "ORDER_STATUS_NEW",
                     "sltp_order": {"symbol": "SBER@MISX"}}
                ]},
                "T@MISX"
            ),
            1
        )

    def test_malformed_nested_order_payload_fails_closed(self):
        with self.assertRaises(fra.AuditError):
            fra.count_active_orders_for_symbol(
                {"orders": [{"order": "not-an-object"}]}, "T@MISX"
            )

    def test_malformed_orders_fail_closed(self):
        with self.assertRaises(fra.AuditError):
            fra.count_active_orders_for_symbol({}, "T@MISX")
        with self.assertRaises(fra.AuditError):
            fra.count_active_orders_for_symbol(
                {"orders": [{"status": "ORDER_STATUS_NEW"}]}, "T@MISX"
            )

    def test_filled_t_orders_are_not_counted_as_active(self):
        self.assertEqual(
            len(fra.matching_active_orders_for_symbol(
                {"orders": [
                    {"status": "ORDER_STATUS_FILLED", "order": {"symbol": "T@MISX"}},
                    {"status": "ORDER_STATUS_NEW", "order": {"symbol": "T@MISX"}}
                ]},
                "T@MISX"
            )),
            1
        )


if __name__ == "__main__":
    unittest.main()
