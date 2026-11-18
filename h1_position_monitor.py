"""Finam H1 position monitoring; no exchange-native stop orders are created."""
from datetime import datetime
from decimal import Decimal
import uuid

from finam_h1_data import fetch_closed_h1_candles
from h1_percent_exit import evaluate_closed_h1_candle


class H1MonitorError(RuntimeError):
    pass


def position_key(symbol):
    return "position::" + symbol


def initialize_position_state(state, symbol, ticker, direction, signed_quantity,
                              entry_price, save_state, entry_time=None):
    if direction not in ("LONG", "SHORT") or signed_quantity == 0:
        raise H1MonitorError("Invalid position direction/quantity")
    price = Decimal(str(entry_price))
    if not price.is_finite() or price <= 0:
        raise H1MonitorError("Invalid broker-confirmed average entry price")
    state[position_key(symbol)] = {
        "symbol": symbol,
        "ticker": ticker,
        "direction": direction,
        "quantity": abs(int(signed_quantity)),
        "entry_price": str(price),
        "entry_time": entry_time or datetime.now().astimezone().isoformat(),
        "last_processed_candle": None,
        "status": "MONITORING",
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }
    save_state(state)
    return state[position_key(symbol)]


def _position_rows(account_data, decimal_value):
    rows = account_data.get("positions")
    if not isinstance(rows, list):
        raise H1MonitorError("Finam account response has no positions list")
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or not row.get("symbol"):
            raise H1MonitorError("Malformed Finam position record")
        symbol = str(row["symbol"])
        if symbol in seen:
            raise H1MonitorError("Duplicate position record: " + symbol)
        seen.add(symbol)
        quantity = decimal_value(row.get("quantity"), "position.quantity")
        if quantity == 0:
            continue
        if quantity != quantity.to_integral_value():
            raise H1MonitorError("Fractional share position cannot be auto-closed: " + symbol)
        entry = decimal_value(row.get("average_price"), "position.average_price")
        result.append({
            "symbol": symbol,
            "ticker": symbol.split("@")[0].upper(),
            "quantity": int(quantity),
            "direction": "LONG" if quantity > 0 else "SHORT",
            "entry_price": entry,
        })
    return result


def _reconcile_pending(token, state, key, position, deps):
    record = state[key]
    pending_status = record.get("status")
    if pending_status == "EXIT_SUBMISSION_ATTEMPTED":
        client_id = record.get("exit_client_order_id")
        if not client_id:
            raise H1MonitorError(position["symbol"] + ": pending exit has no client id")
        order_id = deps["find_order_by_client_id"](token, client_id)
        if not order_id:
            raise H1MonitorError(
                position["symbol"] + ": exit submission outcome unknown; no retry permitted"
            )
        final = deps["wait_for_terminal_order"](token, order_id)
    elif pending_status == "EXIT_FILLED_AWAITING_POSITION_SYNC":
        order_id = record.get("exit_order_id")
        if not order_id:
            raise H1MonitorError(position["symbol"] + ": missing terminal exit order id")
        final = deps["wait_for_terminal_order"](token, order_id)
    else:
        raise H1MonitorError(position["symbol"] + ": unsupported exit reconciliation state")
    filled = deps["decimal_value"](final.get("executed_quantity"), "exit.executed_quantity")
    account, _ = deps["get_account_info"](token)
    remaining = deps["get_position_quantity"](account, position["symbol"])
    if remaining == 0:
        record.update(status="CLOSED", exit_order_id=str(order_id),
                      exit_filled_quantity=str(filled),
                      closed_at=datetime.utcnow().isoformat() + "Z")
        deps["save_state"](state)
        deps["send_telegram_message"](
            "Position closed after order reconciliation: " + position["symbol"]
        )
        return True
    if (remaining > 0) != (position["quantity"] > 0):
        raise H1MonitorError(position["symbol"] + ": position direction changed after exit")
    requested = int(record.get("exit_quantity", abs(position["quantity"])))
    expected_remaining = Decimal(requested) - filled
    if expected_remaining < 0 or abs(remaining) != expected_remaining:
        record["status"] = "EXIT_FILLED_AWAITING_POSITION_SYNC"
        record["exit_order_id"] = str(order_id)
        record["exit_filled_quantity"] = str(filled)
        deps["save_state"](state)
        raise H1MonitorError(
            position["symbol"] + ": broker position quantity does not yet match "
            "the terminal exit fill; no second order will be sent"
        )
    record.update(status="MONITORING", quantity=int(abs(remaining)),
                  last_exit_order_id=str(order_id),
                  last_exit_filled_quantity=str(filled))
    for field in ("exit_client_order_id", "exit_reason", "exit_candle",
                  "exit_quantity", "exit_submitted_at"):
        record.pop(field, None)
    deps["save_state"](state)
    raise H1MonitorError(
        position["symbol"] + ": exit order terminal but position remains; "
        "remainder will be checked on the next run"
    )


def monitor_open_positions(token, account_data, state, dry_run, deps):
    positions = _position_rows(account_data, deps["decimal_value"])
    for pos in positions:
        symbol = pos["symbol"]
        key = position_key(symbol)
        record = state.get(key)

        if record and record.get("status") in (
            "EXIT_SUBMISSION_ATTEMPTED", "EXIT_FILLED_AWAITING_POSITION_SYNC"
        ):
            if _reconcile_pending(token, state, key, pos, deps):
                continue
            record = state[key]

        if record and record.get("status") == "CLOSED":
            record = None

        candles = fetch_closed_h1_candles(token, symbol, deps["api_get"], days=7)

        # Legacy positions are enrolled from Finam's broker-reported average price.
        # Earlier candles are deliberately not replayed because their relation to
        # the original entry time cannot be proven.
        if record is None:
            record = initialize_position_state(
                state, symbol, pos["ticker"], pos["direction"], pos["quantity"],
                pos["entry_price"], deps["save_state"], entry_time=None
            )
            record["last_processed_candle"] = candles[-1]["timestamp"]
            record["baseline_only"] = True
            deps["save_state"](state)
            deps["send_telegram_message"](
                "H1 monitoring enrolled from current closed candle: " + symbol
            )
            continue

        if record.get("status") != "MONITORING":
            raise H1MonitorError(symbol + ": unresolved monitor state")
        if record.get("direction") != pos["direction"]:
            raise H1MonitorError(symbol + ": broker position direction changed")
        entry = deps["decimal_value"](record.get("entry_price"), "monitor.entry_price")
        if entry != pos["entry_price"]:
            raise H1MonitorError(symbol + ": broker average price differs from monitor journal")
        old_qty = int(record.get("quantity", 0))
        if abs(pos["quantity"]) > old_qty:
            raise H1MonitorError(symbol + ": position size increased outside monitored executor")
        record["quantity"] = abs(pos["quantity"])

        last = record.get("last_processed_candle")
        entry_time = record.get("entry_time")
        eligible = []
        for candle in candles:
            stamp = candle["timestamp"]
            if last and stamp <= last:
                continue
            if not last and entry_time:
                candle_dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                entry_dt = datetime.fromisoformat(entry_time.replace("Z", "+00:00"))
                if candle_dt < entry_dt:
                    continue
            eligible.append(candle)

        trigger = None
        for candle in eligible:
            reason = evaluate_closed_h1_candle(entry, pos["direction"], candle)
            if reason:
                trigger = candle, reason
                break

        if trigger is None:
            if candles and candles[-1]["timestamp"] != last:
                record["last_processed_candle"] = candles[-1]["timestamp"]
                record["updated_at"] = datetime.utcnow().isoformat() + "Z"
                deps["save_state"](state)
            continue

        candle, reason = trigger
        qty = abs(pos["quantity"])
        close_side = "SIDE_SELL" if pos["direction"] == "LONG" else "SIDE_BUY"
        client_id = uuid.uuid4().hex[:20]

        if dry_run:
            deps["logger"].warning(
                "[DRY RUN] H1 %s %s candle=%s qty=%s; no order sent",
                reason, symbol, candle["timestamp"], qty
            )
            record["last_processed_candle"] = candle["timestamp"]
            record["last_dry_run_exit"] = reason
            deps["save_state"](state)
            continue

        # Durable idempotency reservation must precede the broker POST.
        record.update(
            status="EXIT_SUBMISSION_ATTEMPTED",
            exit_client_order_id=client_id,
            exit_reason=reason,
            exit_candle=candle["timestamp"],
            exit_quantity=qty,
            exit_submitted_at=datetime.utcnow().isoformat() + "Z",
        )
        deps["save_state"](state)
        result = deps["place_market_order"](
            token, symbol, qty, close_side, client_order_id=client_id
        )
        final = deps["wait_for_terminal_order"](token, result["order_id"])
        filled = deps["decimal_value"](final.get("executed_quantity"), "exit.executed_quantity")
        refreshed, _ = deps["get_account_info"](token)
        remaining = deps["get_position_quantity"](refreshed, symbol)

        if remaining == 0:
            record.update(
                status="CLOSED",
                exit_order_id=str(result["order_id"]),
                exit_filled_quantity=str(filled),
                last_processed_candle=candle["timestamp"],
                closed_at=datetime.utcnow().isoformat() + "Z",
            )
            deps["save_state"](state)
            deps["send_telegram_message"](
                "H1 exit completed: " + symbol + " " + reason +
                "; filled=" + str(filled)
            )
            continue

        if (remaining > 0) != (pos["quantity"] > 0):
            raise H1MonitorError(symbol + ": position direction changed after exit")
        record.update(
            status="EXIT_FILLED_AWAITING_POSITION_SYNC",
            exit_order_id=str(result["order_id"]),
            exit_filled_quantity=str(filled),
        )
        deps["save_state"](state)
        raise H1MonitorError(
            symbol + ": terminal exit order does not yet match the broker position; "
            "no duplicate exit will be submitted"
        )
